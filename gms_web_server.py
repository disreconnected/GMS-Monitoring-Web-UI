#!/usr/bin/env python3
"""FastAPI WebSocket server for GMS Monitoring web dashboard."""

from __future__ import annotations

import argparse
import asyncio
import hmac
import json
import logging
import os
import secrets
import sys
import threading
import time
from collections import deque
from ipaddress import ip_address
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, Header, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from gms_monitor import (
    DEFAULT_TARGET_HOST,
    MIN_WINDOW_SIZE,
    PING_HISTORY_LENGTH,
    PING_INTERVAL_SECONDS,
    SHORT_WINDOW_SIZE,
    MonitorState,
    bandwidth_anomaly_message,
    bandwidth_worker,
    compute_recent_stats,
    parse_traceroute_hops,
    percentile,
    ping_worker,
    set_language,
    traceroute_worker,
    tr,
    validate_target_host,
)
from gms_sns_sites import (
    default_candidates,
    default_sites_path,
    empty_sites,
    forget_host,
    load_sites,
    probe_candidates,
    remember_host,
    save_sites,
)
from gms_stormshield import (
    DEFAULT_POLL_INTERVAL,
    DEFAULT_SNS_PORT,
    StormshieldConfig,
    StormshieldPoller,
)

SCRIPT_DIR = Path(__file__).resolve().parent
WEB_DIST = SCRIPT_DIR / "web" / "dist"

logger = logging.getLogger("gms_web_server")

SNS_WS_ACTIONS = frozenset({"sns_connect", "sns_disconnect", "sns_detect", "sns_forget"})
VALID_WS_ACTIONS = frozenset({"pause", "resume", "traceroute", "set_window"}) | SNS_WS_ACTIONS
SNS_PASSWORD_ENV = "GMS_SNS_PASSWORD"
MAX_SNS_HOST_LENGTH = 253
MAX_SNS_PASSWORD_LENGTH = 256
MAX_SNS_LABEL_INPUT_LENGTH = 256
TRACEROUTE_COOLDOWN_SECONDS = 10.0
DEFAULT_MAX_WS_CLIENTS = 5
TOKEN_HEADER = "x-gms-token"
WS_APP_PROTOCOL = "gms-monitoring"
WS_TOKEN_PREFIX = "gms-token."


def extract_ws_token(websocket: WebSocket) -> str | None:
    header = websocket.headers.get("sec-websocket-protocol", "")
    for part in header.split(","):
        candidate = part.strip()
        if candidate.startswith(WS_TOKEN_PREFIX):
            return candidate[len(WS_TOKEN_PREFIX) :]
    return None


def _normalize_origin_host(host: str) -> str:
    if ":" in host and not host.startswith("["):
        return f"[{host}]"
    return host


def is_loopback_address(addr: str | None) -> bool:
    if not addr:
        return False
    try:
        return ip_address(addr).is_loopback
    except ValueError:
        return False


def validate_bind_address(bind: str, allow_remote: bool) -> None:
    if allow_remote:
        return
    if bind in {"0.0.0.0", "::"}:
        raise SystemExit(
            "Binding to all interfaces requires --allow-remote and --access-token."
        )
    if not is_loopback_address(bind):
        raise SystemExit(
            f"Bind address {bind!r} is not loopback. "
            "Use --allow-remote with --access-token to expose the server."
        )


class ServerSecurity:
    """Per-process auth, origin policy, and WebSocket admission control."""

    def __init__(
        self,
        bind: str,
        port: int,
        *,
        allow_remote: bool = False,
        access_token: str | None = None,
        allowed_origins: list[str] | None = None,
        max_ws_clients: int = DEFAULT_MAX_WS_CLIENTS,
        traceroute_cooldown: float = TRACEROUTE_COOLDOWN_SECONDS,
    ) -> None:
        self.bind = bind
        self.port = port
        self.remote_mode = allow_remote
        self.max_ws_clients = max(1, max_ws_clients)
        self.traceroute_cooldown = traceroute_cooldown
        self._ws_lock = threading.Lock()
        self._traceroute_lock = threading.Lock()
        self._ws_clients = 0
        self._last_traceroute_request = 0.0

        if allow_remote:
            if not access_token or len(access_token) < 16:
                raise SystemExit(
                    "--allow-remote requires --access-token with at least 16 characters."
                )
            self.token = access_token
        else:
            self.token = secrets.token_urlsafe(32)

        self.allowed_origins = self._build_allowed_origins(allowed_origins or [])

    def _build_allowed_origins(self, extra_origins: list[str]) -> set[str]:
        origins: set[str] = set(extra_origins)
        display_hosts = {self.bind, "localhost", "127.0.0.1"}
        if self.bind in {"0.0.0.0", "::"}:
            display_hosts.update({"localhost", "127.0.0.1"})
        for host in display_hosts:
            normalized = _normalize_origin_host(host)
            for scheme in ("http", "https"):
                origins.add(f"{scheme}://{normalized}:{self.port}")
        return origins

    def verify_token(self, token: str | None) -> bool:
        if not token:
            return False
        return hmac.compare_digest(token, self.token)

    def verify_origin(self, origin: str | None, client_host: str | None = None) -> bool:
        if origin:
            return origin in self.allowed_origins
        # Some embedded/IDE browsers omit Origin on loopback WebSockets.
        if not self.remote_mode and is_loopback_address(client_host):
            return True
        return False

    def verify_loopback_peer(self, client_host: str | None) -> bool:
        if self.remote_mode:
            return True
        return is_loopback_address(client_host)

    def try_acquire_ws_slot(self) -> bool:
        with self._ws_lock:
            if self._ws_clients >= self.max_ws_clients:
                return False
            self._ws_clients += 1
            return True

    def release_ws_slot(self) -> None:
        with self._ws_lock:
            self._ws_clients = max(0, self._ws_clients - 1)

    def can_trigger_traceroute(self) -> bool:
        with self._traceroute_lock:
            now = time.time()
            if now - self._last_traceroute_request < self.traceroute_cooldown:
                return False
            self._last_traceroute_request = now
            return True

    def dashboard_url(self) -> str:
        host = "127.0.0.1" if self.bind in {"0.0.0.0", "::"} else self.bind
        base = f"http://{host}:{self.port}/"
        if self.remote_mode:
            return base
        return f"{base}#token={self.token}"

    def print_startup_banner(self) -> None:
        print("=" * 60, file=sys.stderr)
        if self.remote_mode:
            print("WARNING: Remote mode enabled. Server is exposed on the network.", file=sys.stderr)
            print(f"Dashboard: {self.dashboard_url()}", file=sys.stderr)
            print("All control operations require --access-token.", file=sys.stderr)
        else:
            print(f"GMS Monitoring dashboard: {self.dashboard_url()}", file=sys.stderr)
            print("Open the URL above in your browser (token is in the URL fragment).", file=sys.stderr)
        print("=" * 60, file=sys.stderr)


class SnsManager:
    """Owns the replaceable Stormshield poller, its password and the saved sites.

    Long operations (connect, disconnect, detect, autoconnect) run on one worker
    thread at a time so the WebSocket loop never blocks; a second request while one
    is running is refused with a message. The password lives only in this object's
    memory: it is never logged, written to the sites file or put in a snapshot.
    """

    def __init__(
        self,
        *,
        sites_path: Path | None = None,
        password: str = "",
        user: str | None = None,
        port: int = DEFAULT_SNS_PORT,
        interval: float = DEFAULT_POLL_INTERVAL,
        cabundle: str | None = None,
        host_interfaces: list[str] | None = None,
        poller_factory: Callable[[StormshieldConfig], Any] | None = None,
        on_poller_change: Callable[[Any], None] | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._sites_path = sites_path
        self._sites = load_sites(sites_path) if sites_path is not None else empty_sites()
        self._password = password
        self._password_from_env = bool(password)
        self._user = user or self._sites["user"]
        self._port = port
        self._interval = interval
        self._cabundle = cabundle
        self._host_interfaces = list(host_interfaces) if host_interfaces else None
        self._factory = poller_factory or StormshieldPoller
        self.on_poller_change = on_poller_change
        self._poller: Any = None
        self._active_host: str | None = None
        self._candidates: list[dict] = []
        self._probed_at: float | None = None
        self._busy = False
        self._closed = False
        self._message: str | None = None
        self._worker: threading.Thread | None = None
        self._tls_warned = False

    @property
    def poller(self) -> Any:
        with self._lock:
            return self._poller

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "active_host": self._active_host,
                "password_set": bool(self._password),
                "saved_hosts": [
                    {
                        "host": entry["host"],
                        "label": entry["label"],
                        "last_seen": entry["last_seen"],
                    }
                    for entry in self._sites["hosts"]
                ],
                "candidates": [dict(candidate) for candidate in self._candidates],
                "probed_at": self._probed_at,
                "busy": self._busy,
                "message": self._message,
            }

    def join(self, timeout: float | None = 5.0) -> None:
        """Wait for the running worker thread (used by tests and shutdown)."""
        worker = self._worker
        if worker is not None:
            worker.join(timeout)

    # -- worker plumbing -------------------------------------------------------

    def _begin(self, message: str) -> bool:
        with self._lock:
            if self._closed:
                return False
            if self._busy:
                self._message = "another firewall operation is still running"
                return False
            self._busy = True
            self._message = message
            return True

    def _spawn(self, work: Callable[[], str | None]) -> None:
        def run() -> None:
            message: str | None = None
            try:
                message = work()
            except Exception:
                logger.exception("Stormshield operation failed")
                message = "firewall operation failed (see server log)"
            finally:
                with self._lock:
                    self._busy = False
                    self._message = message

        self._worker = threading.Thread(target=run, name="sns-manager", daemon=True)
        self._worker.start()

    def _publish(self, poller: Any) -> None:
        if self.on_poller_change is not None:
            self.on_poller_change(poller)

    def _save_sites(self) -> None:
        if self._sites_path is None:
            return
        try:
            save_sites(self._sites_path, self._sites)
        except OSError as exc:
            logger.warning("Could not save %s: %s", self._sites_path, exc)

    def _make_config(self, host: str, password: str) -> StormshieldConfig:
        return StormshieldConfig(
            host=host,
            user=self._user,
            password=password,
            port=self._port,
            interval=max(1.0, self._interval),
            # Factory SNS certificates use the serial number as CN, not the IP/hostname.
            sslverifyhost=False,
            sslverifypeer=bool(self._cabundle),
            cabundle=self._cabundle,
            host_interfaces=self._host_interfaces,
        )

    def _detach_poller(self) -> Any:
        """Take the current poller out of service; the caller stops it."""
        with self._lock:
            old = self._poller
            self._poller = None
            self._active_host = None
            self._publish(None)
            return old

    # -- poller lifecycle ------------------------------------------------------

    def adopt(self, poller: Any) -> None:
        """Use an already built poller as the current one (no sites bookkeeping)."""
        with self._lock:
            self._poller = poller
            self._active_host = getattr(getattr(poller, "config", None), "host", None)
            self._publish(poller)

    def activate(self, host: str, label: str = "") -> None:
        """Replace the current poller with one for ``host``; blocks while the old one stops."""
        old = self._detach_poller()
        if old is not None:
            old.stop(True)
        with self._lock:
            password = self._password
            warn_tls = not self._cabundle and not self._tls_warned
            self._tls_warned = self._tls_warned or warn_tls
        if warn_tls:
            logger.warning(
                "SNS TLS certificate is not verified (use --sns-cabundle to verify)"
            )
        poller = self._factory(self._make_config(host, password))
        poller.start()
        with self._lock:
            closed = self._closed
            if not closed:
                self._poller = poller
                self._active_host = host
                self._publish(poller)
                remember_host(self._sites, host, label)
                self._save_sites()
        if closed:
            poller.stop(True)

    def connect(self, host: str, password: str | None = None, label: str = "") -> bool:
        """Start (in a thread) a poller for ``host``. Returns False when refused."""
        host = host.strip()
        try:
            if not host or len(host) > MAX_SNS_HOST_LENGTH:
                raise ValueError
            host = validate_target_host(host)
        except ValueError:
            with self._lock:
                self._message = "invalid firewall address"
            return False
        with self._lock:
            if password and self._password_from_env:
                self._message = f"the password is set by {SNS_PASSWORD_ENV} and cannot be changed here"
                return False
            if not password and not self._password:
                self._message = "enter the firewall password to connect"
                return False
            if not self._begin(f"connecting to {host}"):
                return False
            if password:
                self._password = password
        self._spawn(lambda: self._connect_work(host, label))
        return True

    def _connect_work(self, host: str, label: str) -> str | None:
        self.activate(host, label)
        return None

    def disconnect(self) -> bool:
        """Stop the poller (in a thread) and forget a memory-only password."""
        if not self._begin("disconnecting"):
            return False
        self._spawn(self._disconnect_work)
        return True

    def _disconnect_work(self) -> str | None:
        old = self._detach_poller()
        with self._lock:
            if not self._password_from_env:
                self._password = ""
        if old is not None:
            old.stop(True)
        return None

    def forget(self, host: str) -> None:
        with self._lock:
            forget_host(self._sites, host)
            self._save_sites()

    def shutdown(self) -> None:
        """Stop the poller and refuse further connects (server is exiting)."""
        with self._lock:
            self._closed = True
        old = self._detach_poller()
        if old is not None:
            old.stop(True)

    # -- discovery -------------------------------------------------------------

    def _probe(self) -> list[dict]:
        with self._lock:
            sites = {
                "user": self._sites["user"],
                "hosts": [dict(entry) for entry in self._sites["hosts"]],
                "last_host": self._sites["last_host"],
            }
        candidates = default_candidates(sites)
        results = probe_candidates(candidates, port=self._port) if candidates else []
        with self._lock:
            self._candidates = results
            self._probed_at = time.time()
        return results

    def detect(self) -> bool:
        """Probe saved hosts and the default gateway (in a thread) for Stormshield pages."""
        if not self._begin("scanning for Stormshield firewalls"):
            return False
        self._spawn(self._detect_work)
        return True

    def _detect_work(self) -> str | None:
        results = self._probe()
        if not results:
            return "no candidate addresses to probe"
        if not any(result["stormshield"] for result in results):
            return f"no Stormshield found among {len(results)} candidates"
        return None

    def autoconnect(self, announce: Callable[[str], None] | None = None) -> bool:
        """At startup: connect to the first SAVED site that answers as a Stormshield.

        Gateway guesses are probed for the UI's candidate list but never chosen
        here, so the stored password only ever goes to a site the user saved.
        """
        say = announce or logger.info
        with self._lock:
            if self._poller is not None or not self._password or not self._sites["hosts"]:
                return False
            saved_hosts = {entry["host"] for entry in self._sites["hosts"]}
        if not self._begin("looking for a saved Stormshield site"):
            return False

        def work() -> str | None:
            results = self._probe()
            chosen = next(
                (r["host"] for r in results if r["stormshield"] and r["host"] in saved_hosts),
                None,
            )
            if chosen is None:
                say("Stormshield autoconnect: no saved Stormshield site reachable")
                return f"no Stormshield found among {len(results)} candidates"
            say(f"Stormshield autoconnect: connecting to {chosen}")
            self.activate(chosen)
            return None

        self._spawn(work)
        return True


def _handle_sns_action(sns: SnsManager | None, action: str, msg: dict) -> None:
    if sns is None:
        return
    if action == "sns_connect":
        host = msg.get("host")
        password = msg.get("password")
        label = msg.get("label")
        if not isinstance(host, str):
            return
        if password is not None and (
            not isinstance(password, str) or len(password) > MAX_SNS_PASSWORD_LENGTH
        ):
            return
        if label is not None and (
            not isinstance(label, str) or len(label) > MAX_SNS_LABEL_INPUT_LENGTH
        ):
            return
        sns.connect(host, password or None, label or "")
    elif action == "sns_disconnect":
        sns.disconnect()
    elif action == "sns_detect":
        sns.detect()
    elif action == "sns_forget":
        host = msg.get("host")
        if isinstance(host, str):
            sns.forget(host)


def handle_ws_action(
    monitor: "MonitorService",
    security: ServerSecurity,
    msg: object,
    sns: SnsManager | None = None,
) -> None:
    if not isinstance(msg, dict):
        return
    action = msg.get("action")
    if action not in VALID_WS_ACTIONS:
        return
    if action in SNS_WS_ACTIONS:
        _handle_sns_action(sns, action, msg)
    elif action == "pause":
        monitor.pause()
    elif action == "resume":
        monitor.resume()
    elif action == "traceroute":
        if security.can_trigger_traceroute():
            monitor.rerun_traceroute()
    elif action == "set_window":
        try:
            size = int(msg.get("size", 60))
        except (TypeError, ValueError):
            return
        monitor.set_window_size(size)


def _quality_code(
    recent_count: int,
    window_size: int,
    recent_loss_pct: float,
    recent_avg_ping: float | None,
    jitter_ms: float | None,
) -> str:
    if recent_count < max(20, window_size // 2) or recent_avg_ping is None:
        return "unknown"
    if recent_loss_pct < 1.0 and recent_avg_ping < 40 and (jitter_ms is None or jitter_ms < 5):
        return "excellent"
    if recent_loss_pct < 2.0 and recent_avg_ping < 80:
        return "good"
    if recent_loss_pct < 5.0 and recent_avg_ping < 150:
        return "fair"
    return "poor"


def _quality_label(
    recent_count: int,
    window_size: int,
    recent_loss_pct: float,
    recent_avg_ping: float | None,
    jitter_ms: float | None,
) -> str:
    code = _quality_code(
        recent_count, window_size, recent_loss_pct, recent_avg_ping, jitter_ms
    )
    key_map = {
        "unknown": "QUALITY_UNKNOWN",
        "excellent": "QUALITY_EXCELLENT",
        "good": "QUALITY_GOOD",
        "fair": "QUALITY_FAIR",
        "poor": "QUALITY_POOR",
    }
    return tr(key_map[code])


def _build_stats_block(
    ping_history: list,
    window_size: int,
    total_sent: int,
    total_recv: int,
    total_success: int,
    success_rtt_sum: float,
    jitter_sum_all: float,
    jitter_count_all: int,
) -> dict:
    (
        recent_loss_pct,
        recent_avg_ping,
        recent_count,
        recent_lost,
        _recent_min,
        _recent_max,
        jitter_ms,
    ) = compute_recent_stats(ping_history, window_size)

    window_successes = [v for v in ping_history[-window_size:] if v is not None]
    session_successes = [v for v in ping_history if v is not None]

    overall_loss_pct = 0.0 if total_sent == 0 else (1.0 - (total_recv / total_sent)) * 100.0
    avg_rtt_all = success_rtt_sum / total_success if total_success > 0 else None
    jitter_all = jitter_sum_all / jitter_count_all if jitter_count_all > 0 else None

    return {
        "loss_pct": round(recent_loss_pct, 2),
        "lost": recent_lost,
        "count": recent_count,
        "avg_ms": round(recent_avg_ping, 2) if recent_avg_ping is not None else None,
        "p90_ms": round(percentile(window_successes, 90.0), 2) if window_successes else None,
        "p99_ms": round(percentile(window_successes, 99.0), 2) if window_successes else None,
        "jitter_ms": round(jitter_ms, 2) if jitter_ms is not None else None,
        "session": {
            "loss_pct": round(overall_loss_pct, 2),
            "lost": total_sent - total_recv,
            "sent": total_sent,
            "avg_ms": round(avg_rtt_all, 2) if avg_rtt_all is not None else None,
            "p90_ms": round(percentile(session_successes, 90.0), 2) if session_successes else None,
            "p99_ms": round(percentile(session_successes, 99.0), 2) if session_successes else None,
            "jitter_ms": round(jitter_all, 2) if jitter_all is not None else None,
        },
    }


def _collect_alerts(state: MonitorState, snapshot: dict) -> list[dict]:
    alerts: list[dict] = []
    now = time.time()

    with state.lock:
        ping_history = list(state.ping_history)
        window_size = state.window_size
        bw_rx_hist = list(state.bw_rx_mbps_history)
        bw_tx_hist = list(state.bw_tx_mbps_history)
        consecutive_rto = state.consecutive_rto
        rto_burst_threshold = state.rto_burst_threshold
        rto_history = list(state.rto_history)
        source_error = state.source_error

    if source_error:
        alerts.append({"time": now, "level": "error", "msg": source_error})

    short_loss_pct, short_avg_ping, short_count, _, _, short_max_ping, _ = compute_recent_stats(
        ping_history, SHORT_WINDOW_SIZE
    )

    if (
        short_count >= max(5, SHORT_WINDOW_SIZE // 2)
        and short_avg_ping is not None
        and short_max_ping is not None
        and short_max_ping > 3.0 * short_avg_ping
        and (short_max_ping - short_avg_ping) > 100.0
    ):
        alerts.append({"time": now, "level": "warning", "msg": tr("ALERT_DELAY_SPIKE")})
    elif short_count >= max(5, SHORT_WINDOW_SIZE // 2) and short_loss_pct >= 10.0:
        alerts.append({"time": now, "level": "error", "msg": tr("ALERT_HIGH_LOSS")})

    bw_alert = bandwidth_anomaly_message(bw_rx_hist, bw_tx_hist, window_size)
    if bw_alert:
        alerts.append({"time": now, "level": "warning", "msg": bw_alert})

    window_rto = rto_history[-window_size:] if window_size > 0 else []
    bursts_in_window = 0
    streak = 0
    for timed_out in window_rto:
        if timed_out:
            streak += 1
        else:
            if streak >= rto_burst_threshold:
                bursts_in_window += 1
            streak = 0
    if streak >= rto_burst_threshold:
        bursts_in_window += 1

    if consecutive_rto >= rto_burst_threshold and bursts_in_window > 1:
        alerts.append(
            {
                "time": now,
                "level": "error",
                "msg": tr(
                    "ALERT_CONSEC_RTO_RECURRING",
                    count=consecutive_rto,
                    bursts=bursts_in_window,
                ),
            }
        )
    elif consecutive_rto >= rto_burst_threshold:
        alerts.append(
            {
                "time": now,
                "level": "error",
                "msg": tr("ALERT_CONSEC_RTO", count=consecutive_rto),
            }
        )
    elif bursts_in_window > 1:
        alerts.append(
            {
                "time": now,
                "level": "warning",
                "msg": tr("ALERT_RTO_BURSTS", bursts=bursts_in_window),
            }
        )

    return alerts


def build_snapshot(
    state: MonitorState,
    monitor: "MonitorService | None" = None,
    stormshield: StormshieldPoller | None = None,
    sns: SnsManager | None = None,
) -> dict:
    with state.lock:
        target_host = state.target_host
        monitoring = state.monitoring
        last_ping_ms = state.last_ping_ms
        window_size = state.window_size
        ping_history = list(state.ping_history)
        ping_timestamps = list(state.ping_timestamps)
        total_sent = state.total_sent
        total_recv = state.total_recv
        total_success = state.total_success
        success_rtt_sum = state.success_rtt_sum
        jitter_sum_all = state.jitter_sum_all
        jitter_count_all = state.jitter_count_all
        bw_rx_hist = list(state.bw_rx_mbps_history)
        bw_tx_hist = list(state.bw_tx_mbps_history)
        bw_timestamps = list(state.bw_timestamps)
        bw_last_error = state.bw_last_error
        traceroute_lines = list(state.traceroute_lines)
        traceroute_running = state.traceroute_running
        traceroute_error = state.last_traceroute_error
        traceroute_summary = state.traceroute_summary
        last_traceroute_ts = state.last_traceroute_ts
        max_consecutive_rto = state.max_consecutive_rto
        min_rtt_all = state.min_rtt_all
        max_rtt_all = state.max_rtt_all
        consecutive_rto = state.consecutive_rto
        rto_burst_count = state.rto_burst_count

    (
        recent_loss_pct,
        recent_avg_ping,
        recent_count,
        _,
        _,
        _,
        jitter_ms,
    ) = compute_recent_stats(ping_history, window_size)

    window_stats = _build_stats_block(
        ping_history,
        window_size,
        total_sent,
        total_recv,
        total_success,
        success_rtt_sum,
        jitter_sum_all,
        jitter_count_all,
    )

    now = time.time()
    ping_history_out = []
    for i, val in enumerate(ping_history):
        sample_t = ping_timestamps[i] if i < len(ping_timestamps) else now
        ping_history_out.append(
            {
                "t": sample_t,
                "ms": round(val, 2) if val is not None else None,
                "ok": val is not None,
            }
        )

    bw_history = []
    for i in range(len(bw_rx_hist)):
        sample_t = bw_timestamps[i] if i < len(bw_timestamps) else now
        bw_history.append(
            {
                "t": sample_t,
                "rx_mbps": round(bw_rx_hist[i], 2),
                "tx_mbps": round(bw_tx_hist[i], 2) if i < len(bw_tx_hist) else 0.0,
            }
        )

    rx_now = bw_rx_hist[-1] if bw_rx_hist else 0.0
    tx_now = bw_tx_hist[-1] if bw_tx_hist else 0.0

    window_bw_rx = bw_rx_hist[-window_size:] if window_size > 0 else bw_rx_hist
    window_bw_tx = bw_tx_hist[-window_size:] if window_size > 0 else bw_tx_hist
    avg_rx = sum(window_bw_rx) / len(window_bw_rx) if window_bw_rx else 0.0
    avg_tx = sum(window_bw_tx) / len(window_bw_tx) if window_bw_tx else 0.0

    uptime_seconds = time.time() - monitor.started_at if monitor else 0.0

    snapshot = {
        "host": target_host,
        "timestamp": now,
        "current_ping": round(last_ping_ms, 2) if last_ping_ms is not None else None,
        "quality": _quality_label(
            recent_count, window_size, recent_loss_pct, recent_avg_ping, jitter_ms
        ),
        "quality_code": _quality_code(
            recent_count, window_size, recent_loss_pct, recent_avg_ping, jitter_ms
        ),
        "paused": not monitoring,
        "window_size": window_size,
        "window_stats": window_stats,
        "session_stats": window_stats["session"],
        "ping_history": ping_history_out[-3600:],
        "bandwidth": {
            "rx_mbps": round(rx_now, 2),
            "tx_mbps": round(tx_now, 2),
            "avg_rx_mbps": round(avg_rx, 2),
            "avg_tx_mbps": round(avg_tx, 2),
            "error": bw_last_error,
            "history": bw_history[-3600:],
        },
        "traceroute": {
            "running": traceroute_running,
            "error": traceroute_error,
            "summary": traceroute_summary,
            "last_run": last_traceroute_ts,
            "hops": parse_traceroute_hops(traceroute_lines),
        },
        "session": {
            "total_sent": total_sent,
            "total_recv": total_recv,
            "max_consecutive_rto": max_consecutive_rto,
            "min_rtt_ms": round(min_rtt_all, 2) if min_rtt_all is not None else None,
            "max_rtt_ms": round(max_rtt_all, 2) if max_rtt_all is not None else None,
            "rto_burst_count": rto_burst_count,
            "consecutive_rto": consecutive_rto,
            "uptime_seconds": round(uptime_seconds, 1),
        },
    }
    snapshot["alerts"] = _collect_alerts(state, snapshot)
    if monitor is not None:
        monitor.update_alert_log(snapshot["alerts"])
        snapshot["alert_log"] = list(monitor.alert_log)
    else:
        snapshot["alert_log"] = []
    if stormshield is not None:
        snapshot["stormshield"] = stormshield.snapshot()
    if sns is not None:
        snapshot["sns"] = sns.snapshot()
    return snapshot


class MonitorService:
    def __init__(self, target_host: str, source_interface: str | None = None):
        self.state = MonitorState(validate_target_host(target_host))
        self.state.source_interface = source_interface
        self._threads: list[threading.Thread] = []
        self.started_at = time.time()
        self.alert_log: deque = deque(maxlen=50)
        self._previously_active: set[str] = set()
        self._alert_lock = threading.Lock()

    def update_alert_log(self, alerts: list[dict]) -> None:
        with self._alert_lock:
            current_msgs = {a["msg"] for a in alerts}
            for alert in alerts:
                if alert["msg"] not in self._previously_active:
                    self.alert_log.appendleft(
                        {
                            "time": alert["time"],
                            "level": alert["level"],
                            "msg": alert["msg"],
                        }
                    )
            self._previously_active = current_msgs

    def start(self) -> None:
        self._threads = [
            threading.Thread(
                target=ping_worker,
                args=(self.state, PING_INTERVAL_SECONDS),
                daemon=True,
            ),
            threading.Thread(target=bandwidth_worker, args=(self.state,), daemon=True),
            threading.Thread(target=traceroute_worker, args=(self.state,), daemon=True),
        ]
        for t in self._threads:
            t.start()

    def pause(self) -> None:
        with self.state.lock:
            self.state.monitoring = False

    def resume(self) -> None:
        with self.state.lock:
            self.state.monitoring = True

    def rerun_traceroute(self) -> None:
        with self.state.lock:
            running = self.state.traceroute_running
        if not running:
            threading.Thread(
                target=traceroute_worker,
                args=(self.state,),
                daemon=True,
            ).start()

    def set_window_size(self, size: int) -> None:
        with self.state.lock:
            self.state.window_size = max(MIN_WINDOW_SIZE, min(size, PING_HISTORY_LENGTH))

    def stop(self) -> None:
        with self.state.lock:
            self.state.running = False


def create_app(
    monitor: MonitorService,
    security: ServerSecurity,
    stormshield: StormshieldPoller | None = None,
    sns: SnsManager | None = None,
) -> FastAPI:
    app = FastAPI(title="GMS Monitoring")
    if sns is None:
        sns = SnsManager()  # in-memory sites: nothing is written to disk
    # The poller is replaced at runtime; the manager keeps app.state.stormshield current.
    sns.on_poller_change = lambda poller: setattr(app.state, "stormshield", poller)
    if stormshield is not None:
        sns.adopt(stormshield)
    app.state.security = security
    app.state.sns = sns
    app.state.stormshield = sns.poller

    @app.post("/api/shutdown")
    async def shutdown_server(
        request: Request,
        x_gms_token: str | None = Header(default=None, alias=TOKEN_HEADER),
    ) -> JSONResponse:
        client_host = request.client.host if request.client else None
        if not security.verify_token(x_gms_token):
            return JSONResponse({"detail": "Unauthorized"}, status_code=403)
        if not security.verify_loopback_peer(client_host):
            return JSONResponse(
                {"detail": "Shutdown allowed from loopback only"},
                status_code=403,
            )

        monitor.stop()
        await asyncio.to_thread(sns.shutdown)
        server = getattr(app.state, "server", None)

        def _stop() -> None:
            if server is not None:
                server.should_exit = True

        loop = asyncio.get_running_loop()
        loop.call_later(0.3, _stop)
        return JSONResponse({"status": "stopping"})

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        origin = websocket.headers.get("origin")
        token = extract_ws_token(websocket)
        client_host = websocket.client.host if websocket.client else None

        if not security.verify_token(token):
            logger.warning("WebSocket rejected: invalid or missing token from %s", client_host)
            await websocket.close(code=1008, reason="Unauthorized")
            return
        if not security.verify_origin(origin, client_host):
            logger.warning(
                "WebSocket rejected: origin %r not allowed from %s",
                origin,
                client_host,
            )
            await websocket.close(code=1008, reason="Origin not allowed")
            return
        if not security.try_acquire_ws_slot():
            await websocket.close(code=1008, reason="Too many clients")
            return

        await websocket.accept(subprotocol=WS_APP_PROTOCOL)
        try:
            while True:
                snapshot = build_snapshot(
                    monitor.state, monitor, app.state.stormshield, sns
                )
                await websocket.send_text(json.dumps(snapshot))
                try:
                    raw = await asyncio.wait_for(websocket.receive_text(), timeout=0.05)
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    handle_ws_action(monitor, security, msg, sns)
                except asyncio.TimeoutError:
                    pass
                await asyncio.sleep(1.0)
        except WebSocketDisconnect:
            return
        finally:
            security.release_ws_slot()

    if WEB_DIST.is_dir():
        assets_dir = WEB_DIST / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str):
            if full_path == "ws":
                return {"detail": "Use WebSocket"}
            index = WEB_DIST / "index.html"
            if index.is_file():
                return FileResponse(
                    index,
                    headers={
                        "Cache-Control": "no-store, no-cache, must-revalidate",
                        "Pragma": "no-cache",
                    },
                )
            return {"detail": "Frontend not built. Run: cd web && npm run build"}

    else:

        @app.get("/")
        async def root():
            return {
                "message": "GMS Monitoring API",
                "websocket": "/ws",
                "hint": "Build frontend: cd web && npm install && npm run build",
            }

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="GMS Monitoring web server")
    parser.add_argument("--host", default=DEFAULT_TARGET_HOST, help="target host to monitor")
    parser.add_argument("--bind", default="127.0.0.1", help="bind address")
    parser.add_argument("--port", type=int, default=9847, help="HTTP port")
    parser.add_argument("--lang", default="en", choices=["en", "id"], help="UI language")
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="allow non-loopback bind; requires --access-token",
    )
    parser.add_argument(
        "--access-token",
        default=None,
        help="shared control token for remote mode (min 16 chars)",
    )
    parser.add_argument(
        "--allowed-origin",
        action="append",
        default=[],
        dest="allowed_origins",
        metavar="ORIGIN",
        help="extra allowed browser Origin (repeatable; e.g. http://localhost:5173)",
    )
    parser.add_argument(
        "--max-ws-clients",
        type=int,
        default=DEFAULT_MAX_WS_CLIENTS,
        help="maximum concurrent WebSocket clients",
    )
    parser.add_argument(
        "--sns-host",
        default=None,
        help="Stormshield SNS appliance hostname/IP (enables firewall monitoring)",
    )
    parser.add_argument(
        "--sns-user",
        default=None,
        help=(
            "SNS API username (read-only account recommended; "
            "default: 'user' from the sites file, else gmsmonitoring)"
        ),
    )
    parser.add_argument(
        "--sns-port",
        type=int,
        default=DEFAULT_SNS_PORT,
        help="SNS SSL API port (default 443)",
    )
    parser.add_argument(
        "--sns-interval",
        type=float,
        default=DEFAULT_POLL_INTERVAL,
        help="SNS poll interval in seconds (default 5)",
    )
    parser.add_argument(
        "--sns-cabundle",
        default=None,
        help="Optional CA bundle PEM for SNS TLS verification",
    )
    parser.add_argument(
        "--sns-host-ifaces",
        default=None,
        help=(
            "Comma-separated SNS interface names to query for hosts "
            "(default: every plugged LAN/protected interface)"
        ),
    )
    parser.add_argument(
        "--sns-sites",
        default=None,
        help=(
            "JSON file of saved Stormshield sites "
            "(default: gms_sns_sites.json next to this script; never stores a password)"
        ),
    )
    parser.add_argument(
        "--no-sns-autoconnect",
        action="store_true",
        help=(
            "do not probe saved sites and connect automatically at startup "
            "(autoconnect needs GMS_SNS_PASSWORD and a non-empty sites file)"
        ),
    )
    parser.add_argument(
        "--source-interface",
        default=None,
        help=(
            'Windows adapter name (as in "Wi-Fi") to send pings and traceroute from and '
            "to count throughput on, whatever the routing table prefers; an empty value "
            "follows the routing table"
        ),
    )
    args = parser.parse_args()

    validate_bind_address(args.bind, args.allow_remote)
    try:
        target_host = validate_target_host(args.host)
    except ValueError as exc:
        parser.error(str(exc))
    source_interface = (args.source_interface or "").strip() or None
    if source_interface:
        if not sys.platform.startswith("win"):
            parser.error("--source-interface is supported on Windows only")
        if ":" in target_host:
            parser.error(
                "--source-interface sends from the adapter's IPv4 address; "
                "give --host a name or an IPv4 address, or pass --source-interface \"\""
            )
        import psutil

        known = list(psutil.net_if_stats())
        if source_interface not in known:
            parser.error(
                f"--source-interface: no adapter named {source_interface!r}; "
                f"adapters: {', '.join(known)}"
            )

    sns_password = os.environ.get(SNS_PASSWORD_ENV, "")
    # Keep the password out of the environment inherited by ping/tracert children.
    os.environ.pop(SNS_PASSWORD_ENV, None)
    if args.sns_cabundle and not os.path.isfile(args.sns_cabundle):
        parser.error(f"--sns-cabundle file not found: {args.sns_cabundle}")
    if args.sns_host:
        try:
            args.sns_host = validate_target_host(args.sns_host)
        except ValueError as exc:
            parser.error(f"--sns-host: {exc}")
        if not sns_password:
            parser.error(
                "--sns-host requires GMS_SNS_PASSWORD environment variable "
                "(password is never accepted as a CLI argument)."
            )
    sns = SnsManager(
        sites_path=Path(args.sns_sites) if args.sns_sites else default_sites_path(),
        password=sns_password,
        user=args.sns_user,
        port=args.sns_port,
        interval=args.sns_interval,
        cabundle=args.sns_cabundle,
        host_interfaces=[
            name.strip()
            for name in (args.sns_host_ifaces or "").split(",")
            if name.strip()
        ]
        or None,
    )

    security = ServerSecurity(
        args.bind,
        args.port,
        allow_remote=args.allow_remote,
        access_token=args.access_token,
        allowed_origins=args.allowed_origins,
        max_ws_clients=args.max_ws_clients,
    )
    security.print_startup_banner()

    set_language(args.lang)
    monitor = MonitorService(target_host, source_interface)
    if source_interface:
        print(
            f"Pings, traceroute and throughput use adapter {source_interface!r} only",
            file=sys.stderr,
        )
    monitor.start()
    app = create_app(monitor, security, None, sns)
    if args.sns_host:
        # An explicit --sns-host wins over saved sites and autoconnect.
        sns.activate(args.sns_host)
        print(
            f"Stormshield monitoring enabled for {args.sns_host}:{args.sns_port}",
            file=sys.stderr,
        )
    elif not args.no_sns_autoconnect:
        # Probes in a background thread; never delays server startup.
        sns.autoconnect(announce=lambda line: print(line, file=sys.stderr))

    import uvicorn

    config = uvicorn.Config(app, host=args.bind, port=args.port, log_level="info")
    server = uvicorn.Server(config)
    app.state.server = server
    try:
        server.run()
    finally:
        sns.shutdown()


if __name__ == "__main__":
    main()
