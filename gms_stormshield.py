#!/usr/bin/env python3
"""Stormshield SNS SSL API poller for interface and host monitoring."""

from __future__ import annotations

import functools
import logging
import math
import queue
import re
import shlex
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from concurrent.futures import Future, TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from typing import Any

try:  # optional dependency, only needed with --sns-host
    from stormshield.sns.sslclient import AuthenticationError, TOTPNeededError
except ImportError:  # pragma: no cover - package absent; _ensure_client reports it

    class AuthenticationError(Exception):  # type: ignore[no-redef]
        pass

    class TOTPNeededError(Exception):  # type: ignore[no-redef]
        pass


logger = logging.getLogger("gms_stormshield")

HISTORY_SECONDS = 3600
DEFAULT_POLL_INTERVAL = 5.0
DEFAULT_TOP_HOSTS = 15
DEFAULT_SNS_PORT = 443
DEFAULT_SNS_TIMEOUT = 10.0
RECONNECT_BACKOFF_SECONDS = 15.0
RECONNECT_BACKOFF_MAX_SECONDS = 120.0
# Wrong password / TOTP: retrying quickly trips the appliance's brute-force block.
AUTH_RETRY_SECONDS = 600.0
BRUTE_FORCE_MIN_WAIT_SECONDS = 60.0
STOP_JOIN_SECONDS = 5.0
# requests' read timeout never fires while the appliance trickles bytes, so every SNS
# call also gets a hard deadline, after which its session is abandoned.
DEFAULT_COMMAND_DEADLINE = 30.0
# MONITOR HOST walks the appliance's host table and is far slower than the rest.
DEFAULT_HOST_COMMAND_DEADLINE = 60.0
# After a MONITOR HOST timeout the interface is skipped for this long, doubling per
# consecutive timeout up to the cap, so a slow big list cannot starve the fast ones.
HOST_IFACE_BACKOFF_SECONDS = 120.0
HOST_IFACE_BACKOFF_MAX_SECONDS = 600.0
# A login that times out means the appliance is not opening new serverd sessions
# (seen while the web admin's existing session kept working). Each attempt may leave
# another half-open session behind, so neither loop logs in again for this long,
# doubling per consecutive stalled login up to the cap.
LOGIN_STALL_BACKOFF_SECONDS = 120.0
LOGIN_STALL_BACKOFF_MAX_SECONDS = 1800.0
DISCONNECT_DEADLINE_SECONDS = 5.0
CALL_ABORT_POLL_SECONDS = 0.25
ABANDONED_CALL_WAIT_SECONDS = 60.0
HOST_POLL_MIN_INTERVAL = 10.0
HOST_IFACE_WAIT_SECONDS = 2.0
AUTH_FAILED_ERROR = "authentication failed; check GMS_SNS_PASSWORD"
AUTH_BLOCKED_ERROR = "authentication blocked by firewall (brute-force protection); waiting"
TOTP_NEEDED_ERROR = "TOTP required; use an account without TOTP"

_SESSIONID_RE = re.compile(r"sessionid=[^&\s'\"]+")
_BRUTE_FORCE_DELAY_RE = re.compile(r"try again after (\d+) seconds", re.IGNORECASE)


def _sanitize_error(exc: BaseException) -> str:
    """Short, secret-free text for logs and the dashboard (API URLs carry ``sessionid=``)."""
    try:
        from requests import exceptions as req_exc
    except ImportError:
        req_exc = None
    if req_exc is not None and not isinstance(exc, req_exc.SSLError):
        if isinstance(exc, req_exc.Timeout):  # ConnectTimeout is also a ConnectionError
            return "connection timed out"
        if isinstance(exc, req_exc.ConnectionError):
            return "connection refused/unreachable"
    return _SESSIONID_RE.sub("sessionid=***", str(exc))[:200]


def _parse_kv_line(line: str) -> dict[str, str]:
    """Parse a serverd section_line into key/value pairs."""
    result: dict[str, str] = {}
    tokens = line.split()
    if '"' in line:  # the SNS library quotes values containing spaces: name="My PC"
        try:
            tokens = shlex.split(line, posix=True)
        except ValueError:
            pass
    for token in tokens:
        if "=" not in token:
            continue
        key, _, value = token.partition("=")
        if key:
            result[key] = value
    return result


def _parse_int(value: str | None, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        return int(float(value.split(",")[0]))
    except (TypeError, ValueError):
        return default


def _parse_throughput_bits(raw: str | None) -> float:
    """Extract current throughput in bits/s from SNS throughput fields.

    Formats seen in the wild:
      - single value: ``12345``
      - host current,max: ``0,71``
      - interface mac,current,max,userdefined: ``0,25000000,40000000,0``
    """
    if not raw:
        return 0.0
    parts = [p.strip() for p in raw.split(",") if p.strip() != ""]
    if not parts:
        return 0.0
    try:
        numbers = [float(p) for p in parts]
    except ValueError:
        return 0.0
    if len(numbers) >= 4:
        return numbers[1]
    return numbers[0]


def bits_to_mbps(bits_per_sec: float) -> float:
    return bits_per_sec / 1_000_000.0


def _parse_link_mbps(raw: str | None) -> float:
    """Link speed in Mbit/s: first field of an interface ``mac,current,max,userdefined`` value."""
    if not raw:
        return 0.0
    parts = [p.strip() for p in raw.split(",") if p.strip() != ""]
    try:
        numbers = [float(p) for p in parts]
    except ValueError:
        return 0.0
    if len(numbers) < 4:
        return 0.0
    return round(bits_to_mbps(numbers[0]), 3)


def compute_rate_bps(prev_bytes: int | None, curr_bytes: int, dt: float) -> float | None:
    """Bytes delta → bits/s. Returns None when rate cannot be computed."""
    if prev_bytes is None or dt <= 0:
        return None
    delta = curr_bytes - prev_bytes
    if delta < 0:
        # Counter reset on firewall reboot / stats clear.
        return None
    return (delta * 8.0) / dt


def parse_monitor_interface(output: str) -> list[dict[str, Any]]:
    """Parse ``MONITOR INTERFACE`` section_line text into interface records."""
    interfaces: list[dict[str, Any]] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line[0].isdigit() and "name=" not in line:
            # Skip status lines like "101 begin" / "100 conf" unless they embed data.
            if "name=" not in line:
                continue
        if "name=" not in line:
            continue
        kv = _parse_kv_line(line)
        name = kv.get("name", "")
        if not name:
            continue
        # name may be "user,real" — keep full string, also expose user label.
        user_name, _, real_name = name.partition(",")
        rx_bits = _parse_throughput_bits(kv.get("throughput"))
        tx_bits = _parse_throughput_bits(kv.get("throughput_out"))
        interfaces.append(
            {
                "name": user_name or name,
                "real_name": real_name or user_name or name,
                "type": kv.get("type", ""),
                "addr": kv.get("addr", ""),
                "state": _parse_int(kv.get("state"), 0),
                "plugged": _parse_int(kv.get("plugged"), 0),
                "protected": _parse_int(kv.get("protected"), 0),
                "link_mbps": _parse_link_mbps(kv.get("throughput")),
                "rx_bps": rx_bits,
                "tx_bps": tx_bits,
                "rx_mbps": round(bits_to_mbps(rx_bits), 3),
                "tx_mbps": round(bits_to_mbps(tx_bits), 3),
                "tcp_conn": _parse_int(kv.get("tcpconncount")),
                "udp_conn": _parse_int(kv.get("udpconncount")),
                "bytes_in": _parse_int(kv.get("byte")),
                "bytes_out": _parse_int(kv.get("byte_out")),
            }
        )
    return interfaces


def parse_monitor_host(output: str) -> list[dict[str, Any]]:
    """Parse ``MONITOR HOST`` section_line text into host records."""
    hosts: list[dict[str, Any]] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if "addr=" not in line:
            continue
        kv = _parse_kv_line(line)
        addr = kv.get("addr", "")
        if not addr:
            continue
        rx_bits = _parse_throughput_bits(kv.get("throughput"))
        tx_bits = _parse_throughput_bits(kv.get("throughput_out"))
        hosts.append(
            {
                "addr": addr,
                "mac": kv.get("mac_addr", ""),
                "name": kv.get("name") or addr,
                "interface": kv.get("interface", ""),
                "protected": _parse_int(kv.get("protected"), 0),
                "packets": _parse_int(kv.get("packet")),
                "bytes_in": _parse_int(kv.get("byte")),
                "bytes_out": _parse_int(kv.get("byte_out", kv.get("byte_count"))),
                "rx_bps": rx_bits,
                "tx_bps": tx_bits,
                "rx_mbps": round(bits_to_mbps(rx_bits), 3),
                "tx_mbps": round(bits_to_mbps(tx_bits), 3),
                "reputation": _parse_int(kv.get("hostrep")),
                "geo": kv.get("geo", ""),
                "state": kv.get("state", ""),
            }
        )
    return hosts


def rank_top_hosts(
    hosts: list[dict[str, Any]],
    *,
    limit: int = DEFAULT_TOP_HOSTS,
) -> list[dict[str, Any]]:
    """Return top hosts sorted by total bandwidth (rx + tx Mbps), then total bytes."""
    ranked = sorted(
        hosts,
        key=lambda h: (
            float(h.get("rx_mbps") or 0.0) + float(h.get("tx_mbps") or 0.0),
            int(h.get("bytes_in") or 0) + int(h.get("bytes_out") or 0),
        ),
        reverse=True,
    )
    return ranked[: max(0, limit)]


def apply_host_rate_deltas(
    hosts: list[dict[str, Any]],
    previous: dict[str, tuple[int, int, float]],
    now: float,
) -> dict[str, tuple[int, int, float]]:
    """Fill rx/tx Mbps from byte deltas when API throughput is zero/missing.

    ``previous`` maps addr → (bytes_in, bytes_out, timestamp).
    Returns the updated previous map for the next poll.
    """
    updated: dict[str, tuple[int, int, float]] = {}
    for host in hosts:
        addr = str(host.get("addr", ""))
        bytes_in = int(host.get("bytes_in") or 0)
        bytes_out = int(host.get("bytes_out") or 0)
        updated[addr] = (bytes_in, bytes_out, now)

        api_rx = float(host.get("rx_mbps") or 0.0)
        api_tx = float(host.get("tx_mbps") or 0.0)
        if api_rx > 0 or api_tx > 0:
            continue
        if addr not in previous:
            continue
        prev_in, prev_out, prev_t = previous[addr]
        dt = now - prev_t
        rx_bps = compute_rate_bps(prev_in, bytes_in, dt)
        tx_bps = compute_rate_bps(prev_out, bytes_out, dt)
        if rx_bps is not None:
            host["rx_bps"] = rx_bps
            host["rx_mbps"] = round(bits_to_mbps(rx_bps), 3)
        if tx_bps is not None:
            host["tx_bps"] = tx_bps
            host["tx_mbps"] = round(bits_to_mbps(tx_bps), 3)
    return updated


@dataclass
class StormshieldConfig:
    host: str
    user: str
    password: str = field(repr=False)
    port: int = DEFAULT_SNS_PORT
    interval: float = DEFAULT_POLL_INTERVAL
    sslverifyhost: bool = False
    sslverifypeer: bool = False
    cabundle: str | None = None
    top_hosts: int = DEFAULT_TOP_HOSTS
    timeout: float = DEFAULT_SNS_TIMEOUT
    host_interfaces: list[str] | None = None
    command_deadline: float = DEFAULT_COMMAND_DEADLINE
    host_command_deadline: float = DEFAULT_HOST_COMMAND_DEADLINE

    @property
    def history_points(self) -> int:
        """Points kept per interface so history spans ~1 hour at the poll interval."""
        return max(60, math.ceil(HISTORY_SECONDS / max(1.0, self.interval)))


@dataclass
class _InterfaceHistory:
    history: deque


class CommandTimeout(RuntimeError):
    """An SNS call outlived its deadline; its session was abandoned."""


class LoginTimeout(CommandTimeout):
    """The login itself outlived its deadline: the appliance is not opening sessions."""


class LoginBlocked(RuntimeError):
    """A login was refused locally because the shared login block is still running."""

    def __init__(self, remaining: float) -> None:
        super().__init__(f"login blocked for {remaining:.0f} s")
        self.remaining = remaining


class _DaemonExecutor:
    """Single-worker executor running on a daemon thread.

    ThreadPoolExecutor workers are joined at interpreter exit, so one SNS call stuck
    on a trickled response would keep the whole server process from exiting.
    """

    def __init__(self, name: str) -> None:
        self._name = name
        self._queue: queue.SimpleQueue[Any] = queue.SimpleQueue()
        self._thread: threading.Thread | None = None

    def submit(self, fn: Callable[[], Any]) -> Future:
        future: Future = Future()
        self._queue.put((future, fn))
        if self._thread is None:
            self._thread = threading.Thread(target=self._work, name=self._name, daemon=True)
            self._thread.start()
        return future

    def shutdown(self) -> None:
        """Let the worker exit once its current call, if any, returns."""
        self._queue.put(None)

    def _work(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            future, fn = item
            if not future.set_running_or_notify_cancel():
                continue
            try:
                result = fn()
            except BaseException as exc:  # noqa: BLE001 - delivered to the caller
                future.set_exception(exc)
            else:
                future.set_result(result)


def _reap_abandoned(future: Future, client: Any, login: bool) -> None:
    """Log out an abandoned session once its stuck call finally returns."""
    try:
        result = future.result()
    except BaseException:  # noqa: BLE001 - the stuck call failed; still log out
        result = None
    if login:
        client = result  # a login that finished late: log its new session out
    disconnect = getattr(client, "disconnect", None)
    if not callable(disconnect):
        return
    try:
        disconnect()
    except Exception:  # noqa: BLE001
        pass


class _Session:
    """One SNS API login with its own client, call worker, backoff and stuck calls."""

    def __init__(self, role: str) -> None:
        self.role = role
        self.client: Any = None
        self.backoff = RECONNECT_BACKOFF_SECONDS
        self.abandoned: list[Future] = []
        self.executor = _DaemonExecutor(f"stormshield-{role}-call")

    def call(
        self,
        fn: Callable[[], Any],
        *,
        label: str,
        deadline: float,
        abort: Callable[[], bool] | None = None,
        client: Any = None,
        login: bool = False,
    ) -> Any:
        """Run ``fn`` on the session worker, giving up after ``deadline`` seconds.

        On timeout (or ``abort()``) the session is abandoned and CommandTimeout raised;
        ``client`` (or the late login's client) is logged out when the call returns.
        """
        future = self.executor.submit(fn)
        end = time.monotonic() + deadline
        while True:
            remaining = end - time.monotonic()
            try:
                return future.result(timeout=max(0.0, min(remaining, CALL_ABORT_POLL_SECONDS)))
            except FutureTimeout:
                pass
            if abort is not None and abort():
                message = f"{label} abandoned (poller stopping)"
                break
            if remaining <= CALL_ABORT_POLL_SECONDS:
                message = f"{label} exceeded {deadline:g}s (firewall busy)"
                break
        self.abandon(future, client, login)
        raise CommandTimeout(message)

    def abandon(self, future: Future, client: Any, login: bool) -> None:
        self.client = None
        self.reset_executor()
        self.abandoned = [f for f in self.abandoned if not f.done()] + [future]
        threading.Thread(
            target=_reap_abandoned,
            args=(future, client, login),
            name=f"stormshield-{self.role}-reaper",
            daemon=True,
        ).start()

    def reset_executor(self) -> None:
        """Retire the worker (it exits after any stuck call); a fresh one starts lazily."""
        self.executor.shutdown()
        self.executor = _DaemonExecutor(f"stormshield-{self.role}-call")


class StormshieldPoller:
    """Background poller for SNS MONITOR INTERFACE / MONITOR HOST.

    Interfaces and hosts are polled by two threads with separate API sessions, so a
    slow MONITOR HOST can never hold the interface graph hostage.
    """

    def __init__(self, config: StormshieldConfig) -> None:
        self.config = config
        self.lock = threading.Lock()
        self._running = True
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._host_thread: threading.Thread | None = None
        self._iface_session = _Session("ifaces")
        self._host_session = _Session("hosts")
        # Shared: after one rejected login neither loop retries before this time.
        self._auth_blocked_until = 0.0
        self._auth_error: str | None = None
        # Consecutive timed-out logins (either loop); reset by any successful login.
        self._login_stalls = 0
        # One login at a time: the block is checked, and a failed login's block set,
        # while holding it, so the other loop cannot start a login in between.
        self._login_gate = threading.Lock()

        self.connected = False
        self.last_error: str | None = None
        self.model: str | None = None
        self.version: str | None = None
        self.last_poll_at: float | None = None
        self.interfaces: list[dict[str, Any]] = []
        self.hosts: list[dict[str, Any]] = []
        self.host_interfaces: list[str] = []
        self.hosts_error: str | None = None
        self.hosts_updated_at: float | None = None
        # Per-interface circuit breaker for MONITOR HOST (guarded by ``lock``):
        # name -> monotonic time until which it is skipped, and its consecutive timeouts.
        self._host_iface_backoff: dict[str, float] = {}
        self._host_iface_timeouts: dict[str, int] = {}
        self._iface_histories: dict[str, _InterfaceHistory] = {}
        self._host_byte_prev: dict[str, tuple[int, int, float]] = {}
        self._wan_override_warned: set[str] = set()

    @property
    def _client(self) -> Any:
        """The interface session's SSLClient."""
        return self._iface_session.client

    @_client.setter
    def _client(self, client: Any) -> None:
        self._iface_session.client = client

    def start(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(
                target=self._run, name="stormshield-ifaces", daemon=True
            )
            self._thread.start()
        if self._host_thread is None or not self._host_thread.is_alive():
            self._host_thread = threading.Thread(
                target=self._run_hosts, name="stormshield-hosts", daemon=True
            )
            self._host_thread.start()

    def stop(self, wait: bool = False) -> None:
        """Ask both poller threads to exit; they log out of the API on the way out."""
        with self.lock:
            self._running = False
        self._stop_event.set()
        if not wait:
            return
        end = time.monotonic() + STOP_JOIN_SECONDS
        for thread in (self._thread, self._host_thread):
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=max(0.0, end - time.monotonic()))

    def _is_running(self) -> bool:
        with self.lock:
            return self._running

    def _auth_block_remaining(self) -> float:
        with self.lock:
            return self._auth_blocked_until - time.monotonic()

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            interfaces_out = []
            for iface in self.interfaces:
                name = iface["name"]
                hist = self._iface_histories.get(name)
                plugged = iface.get("plugged", 0) == 1
                history = list(hist.history) if hist and plugged else []
                window = history[-60:] if history else []
                avg_rx = (
                    sum(p["rx_mbps"] for p in window) / len(window) if window else 0.0
                )
                avg_tx = (
                    sum(p["tx_mbps"] for p in window) / len(window) if window else 0.0
                )
                interfaces_out.append(
                    {
                        "name": iface["name"],
                        "real_name": iface.get("real_name", iface["name"]),
                        "type": iface.get("type", ""),
                        "addr": iface.get("addr", ""),
                        "state": iface.get("state", 0),
                        "plugged": iface.get("plugged", 0),
                        "protected": iface.get("protected", 0),
                        "link_mbps": iface.get("link_mbps", 0.0),
                        "rx_mbps": iface.get("rx_mbps", 0.0),
                        "tx_mbps": iface.get("tx_mbps", 0.0),
                        "avg_rx_mbps": round(avg_rx, 3),
                        "avg_tx_mbps": round(avg_tx, 3),
                        "tcp_conn": iface.get("tcp_conn", 0),
                        "udp_conn": iface.get("udp_conn", 0),
                        "history": history,
                    }
                )

            hosts_out = [
                {
                    "addr": h["addr"],
                    "mac": h.get("mac", ""),
                    "name": h.get("name", h["addr"]),
                    "interface": h.get("interface", ""),
                    "packets": h.get("packets", 0),
                    "bytes_in": h.get("bytes_in", 0),
                    "bytes_out": h.get("bytes_out", 0),
                    "rx_mbps": h.get("rx_mbps", 0.0),
                    "tx_mbps": h.get("tx_mbps", 0.0),
                    "reputation": h.get("reputation", 0),
                    "geo": h.get("geo", ""),
                }
                for h in self.hosts
            ]

            # retry_at is wall-clock epoch seconds, like hosts_updated_at.
            mono = time.monotonic()
            wall = time.time()
            hosts_slow = [
                {"name": name, "retry_at": wall + (until - mono)}
                for name, until in sorted(
                    self._host_iface_backoff.items(), key=lambda item: item[1]
                )
                if until > mono
            ]

            return {
                "connected": self.connected,
                "error": self.last_error,
                "model": self.model,
                "version": self.version,
                "host": self.config.host,
                "last_poll": self.last_poll_at,
                "interfaces": interfaces_out,
                "hosts": hosts_out,
                "host_interfaces": list(self.host_interfaces),
                "hosts_error": self.hosts_error,
                "hosts_updated_at": self.hosts_updated_at,
                "hosts_slow": hosts_slow,
                "command_deadline": self.config.command_deadline,
                "host_command_deadline": self.config.host_command_deadline,
            }

    def _run(self) -> None:
        """Interface loop: SYSTEM PROPERTY once per login, then MONITOR INTERFACE."""
        session = self._iface_session
        while self._is_running():
            try:
                blocked = self._auth_block_remaining() if session.client is None else 0.0
                if blocked > 0:
                    # The host loop's login was rejected: do not trip brute-force too.
                    with self.lock:
                        self.connected = False
                        self.last_error = self._auth_error
                    wait = blocked
                else:
                    self._ensure_client()
                    if not self._is_running():
                        break
                    self._poll_once()
                    with self.lock:
                        self.connected = True
                        self.last_error = None
                    session.backoff = RECONNECT_BACKOFF_SECONDS
                    wait = max(1.0, self.config.interval)
            except (AuthenticationError, TOTPNeededError) as exc:
                wait = self._record_auth_failure(exc)
            except LoginTimeout as exc:
                wait = self._record_login_stall(exc)
            except LoginBlocked as exc:
                with self.lock:
                    self.connected = False
                    self.last_error = self._auth_error
                wait = exc.remaining
            except Exception as exc:  # noqa: BLE001 - keep dashboard alive on any SNS failure
                error = _sanitize_error(exc)
                logger.warning("Stormshield poll failed: %s", error)
                with self.lock:
                    self.connected = False
                    self.last_error = error
                self._disconnect()
                wait = session.backoff
                session.backoff = min(session.backoff * 2, RECONNECT_BACKOFF_MAX_SECONDS)
            self._stop_event.wait(wait)
        self._disconnect()
        session.reset_executor()

    def _run_hosts(self) -> None:
        """Host loop: MONITOR HOST per LAN interface on its own API session."""
        session = self._host_session
        while self._is_running():
            try:
                blocked = self._auth_block_remaining() if session.client is None else 0.0
                if blocked > 0:
                    with self.lock:
                        self.hosts_error = self._auth_error
                    wait = blocked
                elif not self._host_query_names():
                    wait = HOST_IFACE_WAIT_SECONDS  # interface loop not connected yet
                else:
                    self._ensure_host_client()
                    if not self._is_running():
                        break
                    self._poll_hosts_once()
                    session.backoff = RECONNECT_BACKOFF_SECONDS
                    wait = max(self.config.interval, HOST_POLL_MIN_INTERVAL)
            except (AuthenticationError, TOTPNeededError) as exc:
                wait = self._record_auth_failure(exc, self._host_session)
            except LoginTimeout as exc:
                wait = self._record_login_stall(exc, self._host_session)
            except LoginBlocked as exc:
                with self.lock:
                    self.hosts_error = self._auth_error
                wait = exc.remaining
            except Exception as exc:  # noqa: BLE001 - keep the previous host list
                error = _sanitize_error(exc)
                logger.warning("Stormshield host poll failed: %s", error)
                with self.lock:
                    self.hosts_error = error
                self._disconnect_hosts()
                wait = session.backoff
                session.backoff = min(session.backoff * 2, RECONNECT_BACKOFF_MAX_SECONDS)
            self._stop_event.wait(wait)
        self._disconnect_hosts()
        session.reset_executor()

    @staticmethod
    def _auth_failure_wait(exc: BaseException) -> tuple[float, str]:
        """How long to leave the appliance alone after a rejected login, and why."""
        wait = AUTH_RETRY_SECONDS
        if isinstance(exc, TOTPNeededError):
            error = TOTP_NEEDED_ERROR
        else:
            error = AUTH_FAILED_ERROR
            match = _BRUTE_FORCE_DELAY_RE.search(str(exc))
            if match:
                error = AUTH_BLOCKED_ERROR
                wait = max(float(match.group(1)), BRUTE_FORCE_MIN_WAIT_SECONDS)
        return wait, error

    def _block_logins(self, wait: float, error: str) -> None:
        """Extend the shared login block; the text follows whichever block ends last."""
        with self.lock:
            until = time.monotonic() + wait
            if until > self._auth_blocked_until:
                self._auth_blocked_until = until
                self._auth_error = error

    def _record_auth_failure(self, exc: BaseException, session: _Session | None = None) -> float:
        """Record a rejected login and return how long to leave the appliance alone."""
        wait, error = self._auth_failure_wait(exc)
        logger.warning("Stormshield login failed: %s (next attempt in %.0f s)", error, wait)
        session = session or self._iface_session
        self._block_logins(wait, error)
        with self.lock:
            if session is self._host_session:
                self.hosts_error = error
            else:
                self.connected = False
                self.last_error = error
        self._disconnect_session(session)
        return wait

    def _note_login_stall(self, exc: CommandTimeout) -> None:
        """Block logins after a timed-out one, longer for each consecutive stall."""
        with self.lock:
            self._login_stalls += 1
            stalls = self._login_stalls
        wait = min(
            LOGIN_STALL_BACKOFF_SECONDS * 2 ** (stalls - 1), LOGIN_STALL_BACKOFF_MAX_SECONDS
        )
        self._block_logins(
            wait,
            f"{exc}: the firewall is not opening new API sessions; "
            f"next login attempt in {wait / 60:.0f} min",
        )

    def _record_login_stall(self, exc: LoginTimeout, session: _Session | None = None) -> float:
        """Show a timed-out login (its block is already set) and return the wait."""
        session = session or self._iface_session
        with self.lock:
            error = self._auth_error or str(exc)
            wait = max(self._auth_blocked_until - time.monotonic(), CALL_ABORT_POLL_SECONDS)
            if session is self._host_session:
                self.hosts_error = error
            else:
                self.connected = False
                self.last_error = error
        logger.warning("Stormshield %s", error)
        self._disconnect_session(session)
        return wait

    def _ensure_client(self) -> None:
        self._ensure_session(self._iface_session)

    def _ensure_host_client(self) -> None:
        self._ensure_session(self._host_session)

    def _ensure_session(self, session: _Session) -> None:
        if session.client is not None:
            return
        self._wait_for_abandoned(session)
        try:
            from stormshield.sns.sslclient import SSLClient
        except ImportError as exc:
            raise RuntimeError(
                "stormshield.sns.sslclient is not installed. "
                "Install requirements_web.txt."
            ) from exc

        kwargs: dict[str, Any] = {
            "host": self.config.host,
            "port": self.config.port,
            "user": self.config.user,
            "password": self.config.password,
            "sslverifyhost": self.config.sslverifyhost,
            "sslverifypeer": self.config.sslverifypeer,
            "timeout": self.config.timeout,
        }
        if self.config.cabundle:
            kwargs["cabundle"] = self.config.cabundle

        self._acquire_login_gate()
        try:
            # Checked here, not only at the top of the loop: the other loop may have
            # set the block while this one waited, or this is a mid-poll re-login.
            if not self._is_running():
                raise CommandTimeout("login abandoned (poller stopping)")
            remaining = self._auth_block_remaining()
            if remaining > 0:
                raise LoginBlocked(remaining)
            try:
                client = session.call(
                    functools.partial(SSLClient, **kwargs),
                    label="login",
                    deadline=self.config.command_deadline,
                    abort=self._is_stopping,
                    login=True,
                )
            except CommandTimeout as exc:
                if not self._is_running():
                    raise
                self._note_login_stall(exc)
                raise LoginTimeout(str(exc)) from exc
            except (AuthenticationError, TOTPNeededError) as exc:
                self._block_logins(*self._auth_failure_wait(exc))
                raise
        finally:
            self._login_gate.release()
        session.client = client
        with self.lock:
            self._login_stalls = 0
        if not self._is_running():
            # stop() arrived while the login was in flight; do not leak the API session.
            self._disconnect_session(session)
            return
        if session is self._iface_session:
            self._fetch_system_property()

    def _is_stopping(self) -> bool:
        return not self._is_running()

    def _acquire_login_gate(self) -> None:
        while not self._login_gate.acquire(timeout=CALL_ABORT_POLL_SECONDS):
            if not self._is_running():
                raise CommandTimeout("login abandoned (poller stopping)")

    def _wait_for_abandoned(self, session: _Session) -> None:
        """Hold a reconnect while an abandoned call of this session is still stuck.

        Waits until those calls return or ``max(backoff, 60 s)`` passed, so at most a
        couple of stuck calls (and their threads) exist at any time.
        """
        pending = [f for f in session.abandoned if not f.done()]
        session.abandoned = pending
        if not pending:
            return
        logger.info("Waiting for a stuck SNS %s call before logging in again", session.role)
        end = time.monotonic() + max(session.backoff, ABANDONED_CALL_WAIT_SECONDS)
        while self._is_running() and any(not f.done() for f in pending):
            remaining = end - time.monotonic()
            if remaining <= 0:
                break
            self._stop_event.wait(min(remaining, 0.5))

    def _fetch_system_property(self) -> None:
        session = self._iface_session
        client = session.client
        if client is None:
            return
        try:
            response = session.call(
                functools.partial(client.send_command, "SYSTEM PROPERTY"),
                label="SYSTEM PROPERTY",
                deadline=self.config.command_deadline,
                abort=self._is_stopping,
                client=client,
            )
        except CommandTimeout:
            raise  # the session was abandoned; let the loop report and back off
        except Exception as exc:  # noqa: BLE001
            logger.debug("SYSTEM PROPERTY failed: %s", _sanitize_error(exc))
            return
        if not response:
            return
        # Response.data is a requests CaseInsensitiveDict, not a dict subclass.
        data = getattr(response, "data", None) or {}
        result = data.get("Result") if isinstance(data, Mapping) else None
        if isinstance(result, Mapping):
            with self.lock:
                self.model = result.get("Model") or self.model
                self.version = result.get("Version") or self.version

    def _send_command(self, command: str) -> str:
        """Send ``command`` on the interface session."""
        return self._session_command(
            self._iface_session, command, self.config.command_deadline
        )

    def _send_host_command(self, command: str) -> str:
        """Send ``command`` on the host session."""
        return self._session_command(
            self._host_session, command, self.config.host_command_deadline
        )

    def _session_command(self, session: _Session, command: str, deadline: float) -> str:
        client = session.client
        if client is None:
            raise RuntimeError("SNS client is not connected")
        response = session.call(
            functools.partial(client.send_command, command),
            label=command,
            deadline=deadline,
            abort=self._is_stopping,
            client=client,
        )
        if not response:
            output = getattr(response, "output", None) or "command failed"
            raise RuntimeError(f"{command} failed: {output}")
        output = getattr(response, "output", None)
        if output is None:
            # Fall back to stringifying data when output is absent.
            data = getattr(response, "data", None)
            if isinstance(data, Mapping):
                lines = []
                for section, rows in data.items():
                    if isinstance(rows, list):
                        for row in rows:
                            if isinstance(row, Mapping):
                                lines.append(
                                    " ".join(f"{k}={v}" for k, v in row.items())
                                )
                    elif isinstance(rows, Mapping):
                        lines.append(" ".join(f"{k}={v}" for k, v in rows.items()))
                    else:
                        lines.append(f"{section}={rows}")
                return "\n".join(lines)
            return str(data or "")
        return str(output)

    def _poll_once(self) -> None:
        now = time.time()
        iface_text = self._send_command("MONITOR INTERFACE")
        interfaces = parse_monitor_interface(iface_text)

        with self.lock:
            self.interfaces = interfaces
            self.last_poll_at = now

            for iface in interfaces:
                name = iface["name"]
                hist = self._iface_histories.get(name)
                if hist is None:
                    hist = _InterfaceHistory(deque(maxlen=self.config.history_points))
                    self._iface_histories[name] = hist
                hist.history.append(
                    {
                        "t": int(now),
                        "rx_mbps": iface["rx_mbps"],
                        "tx_mbps": iface["tx_mbps"],
                    }
                )

            # Drop histories for interfaces that disappeared.
            active = {i["name"] for i in interfaces}
            for key in list(self._iface_histories):
                if key not in active:
                    del self._iface_histories[key]

    def _host_query_names(self) -> list[str]:
        """Interfaces to query for hosts, from the interface loop's latest poll."""
        with self.lock:
            interfaces = list(self.interfaces)
        # Unfiltered MONITOR HOST never returns on busy appliances (huge public-host
        # tables), so always query per interface, and only plugged LAN ones by default.
        if self.config.host_interfaces:
            return self._override_host_interfaces(interfaces)
        return [i["name"] for i in interfaces if i["plugged"] == 1 and i["protected"] == 1]

    def _poll_hosts_once(self) -> bool:
        """Refresh the top-host list; False when no interface is known yet.

        An interface whose MONITOR HOST times out is skipped for a while (circuit
        breaker) and the hosts of the others are still published. Interfaces that timed
        out before are queried last, so a slow one cannot hold the fast ones up.
        """
        host_ifaces = self._host_query_names()
        if not host_ifaces:
            return False
        now = time.time()
        hosts: list[dict[str, Any]] = []
        queried: list[str] = []
        mono = time.monotonic()
        # sorted() is stable: ties keep the interface order.
        due = sorted(
            (n for n in host_ifaces if self._host_iface_backoff.get(n, 0.0) <= mono),
            key=lambda n: self._host_iface_timeouts.get(n, 0),
        )
        reconnect_error: Exception | None = None
        for position, name in enumerate(due):
            try:
                host_text = self._send_host_command(f"MONITOR HOST iface={name}")
            except CommandTimeout:
                if not self._is_running():
                    raise  # poller stopping: the call was aborted, it was not slow
                with self.lock:
                    streak = self._host_iface_timeouts.get(name, 0) + 1
                    self._host_iface_timeouts[name] = streak
                    skip = min(
                        HOST_IFACE_BACKOFF_SECONDS * 2 ** (streak - 1),
                        HOST_IFACE_BACKOFF_MAX_SECONDS,
                    )
                    self._host_iface_backoff[name] = time.monotonic() + skip
                logger.warning(
                    "MONITOR HOST iface=%s exceeded %gs; skipping it for %.0f s",
                    name,
                    self.config.host_command_deadline,
                    skip,
                )
                if position + 1 < len(due):
                    # The timeout abandoned the host session: log in again for the rest.
                    try:
                        self._ensure_host_client()
                    except Exception as exc:  # noqa: BLE001 - publish what we have first
                        reconnect_error = exc
                        break
                    if not self._is_running():
                        break
                continue
            except Exception as exc:  # noqa: BLE001 - one bad interface must not stop the poll
                logger.warning(
                    "MONITOR HOST iface=%s failed: %s", name, _sanitize_error(exc)
                )
                continue
            hosts.extend(parse_monitor_host(host_text))
            queried.append(name)
            with self.lock:
                self._host_iface_backoff.pop(name, None)
                self._host_iface_timeouts.pop(name, None)

        with self.lock:
            mono = time.monotonic()
            slow = [n for n in host_ifaces if self._host_iface_backoff.get(n, 0.0) > mono]
            slow_error = (
                f"{', '.join(slow)}: exceeded "
                f"{self.config.host_command_deadline:g}s (firewall busy)"
            )
            if slow and not queried:
                self.hosts_error = slow_error  # nothing answered: keep the previous list
            else:
                self._host_byte_prev = apply_host_rate_deltas(
                    hosts, self._host_byte_prev, now
                )
                self.hosts = rank_top_hosts(hosts, limit=self.config.top_hosts)
                self.host_interfaces = queried
                self.hosts_error = (
                    f"{slow_error}; showing hosts from {', '.join(queried)}"
                    if slow
                    else None
                )
                self.hosts_updated_at = now
        if reconnect_error is not None:
            raise reconnect_error  # the loop records the failed login and backs off
        return True

    def _override_host_interfaces(self, interfaces: list[dict[str, Any]]) -> list[str]:
        """Apply ``host_interfaces``: unknown names are ignored, WAN ones are refused."""
        by_name = {i["name"]: i for i in interfaces}
        allowed: list[str] = []
        for name in self.config.host_interfaces or []:
            iface = by_name.get(name)
            if iface is None:
                continue
            if iface["protected"] == 0:
                if name not in self._wan_override_warned:
                    self._wan_override_warned.add(name)
                    logger.warning(
                        "Ignoring WAN interface %s in host interface override "
                        "(MONITOR HOST on WAN interfaces hangs)",
                        name,
                    )
                continue
            allowed.append(name)
        return allowed

    def _disconnect(self) -> None:
        self._disconnect_session(self._iface_session)

    def _disconnect_hosts(self) -> None:
        self._disconnect_session(self._host_session)

    def _disconnect_session(self, session: _Session) -> None:
        client = session.client
        session.client = None
        if client is None:
            return
        disconnect = getattr(client, "disconnect", None)
        if not callable(disconnect):
            return
        try:
            # A hung logout must not block shutdown: short deadline, then abandon.
            session.call(disconnect, label="logout", deadline=DISCONNECT_DEADLINE_SECONDS)
        except Exception:  # noqa: BLE001
            pass
