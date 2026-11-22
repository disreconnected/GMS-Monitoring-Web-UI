#!/usr/bin/env python3
"""Saved Stormshield SNS sites and best-effort discovery for the web dashboard.

The operator serves at several sites, each with its own firewall (and management
IP). This module keeps a small JSON file of the firewalls seen so far and can probe
a list of candidate addresses to find which one answers like a Stormshield.

The file never stores a password: ``save_sites`` rebuilds the document from the
known schema keys only, so stray keys are dropped.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import tempfile
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from ipaddress import IPv4Address
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from gms_monitor import validate_target_host

try:
    import requests
    from urllib3.exceptions import InsecureRequestWarning
except ImportError:  # pragma: no cover - requests ships with the SNS SSL client
    requests = None  # type: ignore[assignment]
    InsecureRequestWarning = None  # type: ignore[assignment,misc]

SITES_FILENAME = "gms_sns_sites.json"
DEFAULT_SNS_USER = "gmsmonitoring"
MAX_SAVED_HOSTS = 20
MAX_LABEL_LENGTH = 64
PROBE_WORKERS = 8
_ROUTE_TIMEOUT_SECONDS = 5.0
_RESPONSE_TEXT_LIMIT = 200_000

# Serialises probe_candidates: warnings.catch_warnings() edits process-wide state.
_PROBE_LOCK = threading.Lock()


def default_sites_path() -> Path:
    return Path(__file__).resolve().parent / SITES_FILENAME


def empty_sites() -> dict[str, Any]:
    return {"user": DEFAULT_SNS_USER, "hosts": [], "last_host": None}


def is_valid_host(host: object) -> bool:
    if not isinstance(host, str):
        return False
    try:
        validate_target_host(host)
    except ValueError:
        return False
    return True


def clean_label(label: object) -> str:
    if not isinstance(label, str):
        return ""
    printable = "".join(ch for ch in label if ch.isprintable())
    return printable.strip()[:MAX_LABEL_LENGTH]


def _clean_last_seen(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _normalize(raw: object) -> dict[str, Any]:
    """Rebuild a sites document from schema keys only, dropping anything invalid."""
    out = empty_sites()
    if not isinstance(raw, dict):
        return out

    user = raw.get("user")
    if (
        isinstance(user, str)
        and user.strip()
        and len(user) <= 64
        and all(ch.isprintable() and not ch.isspace() for ch in user)
    ):
        out["user"] = user

    entries = raw.get("hosts")
    seen: set[str] = set()
    for entry in entries if isinstance(entries, list) else []:
        if isinstance(entry, str):  # tolerate a hand-edited list of plain addresses
            entry = {"host": entry}
        if not isinstance(entry, dict) or not is_valid_host(entry.get("host")):
            continue
        host = validate_target_host(entry["host"])
        key = host.lower()
        if key in seen:
            continue
        seen.add(key)
        out["hosts"].append(
            {
                "host": host,
                "label": clean_label(entry.get("label")),
                "last_seen": _clean_last_seen(entry.get("last_seen")),
            }
        )
        if len(out["hosts"]) >= MAX_SAVED_HOSTS:
            break

    last_host = raw.get("last_host")
    if isinstance(last_host, str):
        for entry in out["hosts"]:
            if entry["host"].lower() == last_host.strip().lower():
                out["last_host"] = entry["host"]
                break
    return out


def load_sites(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Read the sites file; a missing or unreadable file yields an empty document."""
    target = Path(path) if path is not None else default_sites_path()
    try:
        with open(target, "r", encoding="utf-8") as handle:
            return _normalize(json.load(handle))
    except (OSError, ValueError):
        return empty_sites()


def save_sites(path: str | os.PathLike[str], data: object) -> None:
    """Atomically write the sites document (temp file in the same dir, then replace)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(_normalize(data), indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        prefix=target.name + ".", suffix=".tmp", dir=str(target.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def remember_host(
    data: dict[str, Any],
    host: str,
    label: str = "",
    now: float | None = None,
) -> dict[str, Any]:
    """Move ``host`` to the front (deduped), stamp last_seen and make it last_host.

    Mutates and returns ``data``. An empty ``label`` keeps the label already saved.
    """
    host = validate_target_host(host)
    key = host.lower()
    existing_label = ""
    kept = []
    for entry in data.get("hosts", []):
        if str(entry.get("host", "")).lower() == key:
            existing_label = clean_label(entry.get("label"))
        else:
            kept.append(entry)
    stamp = time.time() if now is None else now
    data["hosts"] = [
        {"host": host, "label": clean_label(label) or existing_label, "last_seen": stamp}
    ] + kept
    del data["hosts"][MAX_SAVED_HOSTS:]
    data["last_host"] = host
    data.setdefault("user", DEFAULT_SNS_USER)
    return data


def forget_host(data: dict[str, Any], host: str) -> dict[str, Any]:
    """Remove ``host`` from the saved list; last_host falls back to the newest entry."""
    key = host.strip().lower()
    data["hosts"] = [
        entry for entry in data.get("hosts", []) if str(entry.get("host", "")).lower() != key
    ]
    last = data.get("last_host")
    if isinstance(last, str) and last.lower() == key:
        data["last_host"] = data["hosts"][0]["host"] if data["hosts"] else None
    return data


# --------------------------------------------------------------------------- probing


def _url_host(host: str) -> str:
    return f"[{host}]" if ":" in host and not host.startswith("[") else host


def _looks_like_stormshield(response: Any) -> bool:
    try:
        text = str(response.text or "")[:_RESPONSE_TEXT_LIMIT].lower()
    except Exception:
        text = ""
    try:
        headers = " ".join(f"{k} {v}" for k, v in response.headers.items()).lower()
    except Exception:
        headers = ""
    final_url = str(getattr(response, "url", "") or "")
    if "stormshield" in text or "stormshield" in headers or "stormshield" in final_url.lower():
        return True
    return "/auth/" in urlsplit(final_url).path.lower()


def _probe_one(host: str, port: int, timeout: float) -> dict[str, Any]:
    result: dict[str, Any] = {
        "host": host,
        "reachable": False,
        "stormshield": False,
        "latency_ms": None,
    }
    if requests is None or not is_valid_host(host):
        return result
    url = f"https://{_url_host(host.strip())}:{int(port)}/"
    started = time.monotonic()
    try:
        response = requests.get(
            url, verify=False, allow_redirects=True, timeout=timeout
        )
    except Exception:  # any failure (timeout, refused, TLS, hostile device) = unreachable
        return result
    try:
        result["reachable"] = True
        result["latency_ms"] = round((time.monotonic() - started) * 1000.0, 1)
        result["stormshield"] = _looks_like_stormshield(response)
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()
    return result


def probe_candidates(
    hosts: list[str], port: int = 443, timeout: float = 2.0
) -> list[dict[str, Any]]:
    """HTTPS-probe each candidate concurrently; results keep the input order."""
    if not hosts:
        return []
    with _PROBE_LOCK:
        with warnings.catch_warnings():
            if InsecureRequestWarning is not None:
                warnings.simplefilter("ignore", InsecureRequestWarning)
            with ThreadPoolExecutor(
                max_workers=min(PROBE_WORKERS, len(hosts)),
                thread_name_prefix="sns-probe",
            ) as pool:
                return list(pool.map(lambda h: _probe_one(h, port, timeout), hosts))


# ------------------------------------------------------------------ candidate builder


def _ordered_gateways(pairs: list[tuple[int, str]]) -> list[str]:
    out: list[str] = []
    for _metric, gateway in sorted(pairs, key=lambda pair: pair[0]):
        if gateway not in out:
            out.append(gateway)
    return out


def _usable_gateway(text: str) -> str | None:
    try:
        gateway = IPv4Address(text)
    except ValueError:
        return None
    return None if gateway.is_unspecified else str(gateway)


def _metric_or_max(text: str) -> int:
    try:
        return int(text)
    except ValueError:
        return sys.maxsize


def parse_windows_gateways(output: str) -> list[str]:
    """Default IPv4 gateways from ``route print -4``, lowest metric first."""
    pairs: list[tuple[int, str]] = []
    for line in output.splitlines():
        fields = line.split()
        if len(fields) < 3 or fields[0] != "0.0.0.0" or fields[1] != "0.0.0.0":
            continue
        gateway = _usable_gateway(fields[2])  # "On-link" is skipped here
        if gateway is not None:
            pairs.append((_metric_or_max(fields[-1]), gateway))
    return _ordered_gateways(pairs)


def parse_posix_gateways(output: str) -> list[str]:
    """Default IPv4 gateways from ``ip route show default``, lowest metric first."""
    pairs: list[tuple[int, str]] = []
    for line in output.splitlines():
        fields = line.split()
        if not fields or fields[0] != "default" or "via" not in fields:
            continue
        index = fields.index("via")
        if index + 1 >= len(fields):
            continue
        gateway = _usable_gateway(fields[index + 1])
        if gateway is None:
            continue
        metric = sys.maxsize
        if "metric" in fields and fields.index("metric") + 1 < len(fields):
            metric = _metric_or_max(fields[fields.index("metric") + 1])
        pairs.append((metric, gateway))
    return _ordered_gateways(pairs)


def _command_output(args: list[str]) -> str:
    completed = subprocess.run(
        args,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=_ROUTE_TIMEOUT_SECONDS,
        check=False,
    )
    return completed.stdout


def default_gateways() -> list[str]:
    """Default IPv4 gateway(s) of this PC; an empty list when they cannot be read."""
    try:
        if sys.platform == "win32":
            return parse_windows_gateways(_command_output(["route", "print", "-4"]))
        return parse_posix_gateways(_command_output(["ip", "route", "show", "default"]))
    except Exception:
        return []


def default_candidates(sites_data: object) -> list[str]:
    """Saved hosts (last_host first), then default gateways, then each gateway's x.y.z.1."""
    data = _normalize(sites_data)
    saved = [entry["host"] for entry in data["hosts"]]
    last_host = data["last_host"]
    if last_host in saved:
        saved.remove(last_host)
        saved.insert(0, last_host)

    gateways = default_gateways()
    guesses = [".".join(gateway.split(".")[:3] + ["1"]) for gateway in gateways]

    out: list[str] = []
    seen: set[str] = set()
    for host in saved + gateways + guesses:
        if host.lower() not in seen:
            seen.add(host.lower())
            out.append(host)
    return out
