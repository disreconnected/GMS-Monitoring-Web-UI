#!/usr/bin/env python3
"""FastAPI WebSocket server for GMS Monitoring web dashboard."""

from __future__ import annotations

import argparse
import asyncio
import hmac
import json
import logging
import secrets
import sys
import threading
import time
from collections import deque
from ipaddress import ip_address
from pathlib import Path

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
)

SCRIPT_DIR = Path(__file__).resolve().parent
WEB_DIST = SCRIPT_DIR / "web" / "dist"

logger = logging.getLogger("gms_web_server")

VALID_WS_ACTIONS = frozenset({"pause", "resume", "traceroute", "set_window"})
TRACEROUTE_COOLDOWN_SECONDS = 10.0
DEFAULT_MAX_WS_CLIENTS = 5
TOKEN_HEADER = "x-gms-token"


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
            for scheme in ("http", "https"):
                origins.add(f"{scheme}://{host}:{self.port}")
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


def handle_ws_action(monitor: "MonitorService", security: ServerSecurity, msg: object) -> None:
    if not isinstance(msg, dict):
        return
    action = msg.get("action")
    if action not in VALID_WS_ACTIONS:
        return
    if action == "pause":
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


def _quality_label(
    recent_count: int,
    window_size: int,
    recent_loss_pct: float,
    recent_avg_ping: float | None,
    jitter_ms: float | None,
) -> str:
    if recent_count < max(20, window_size // 2) or recent_avg_ping is None:
        return tr("QUALITY_UNKNOWN")
    if recent_loss_pct < 1.0 and recent_avg_ping < 40 and (jitter_ms is None or jitter_ms < 5):
        return tr("QUALITY_EXCELLENT")
    if recent_loss_pct < 2.0 and recent_avg_ping < 80:
        return tr("QUALITY_GOOD")
    if recent_loss_pct < 5.0 and recent_avg_ping < 150:
        return tr("QUALITY_FAIR")
    return tr("QUALITY_POOR")


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


def build_snapshot(state: MonitorState, monitor: "MonitorService | None" = None) -> dict:
    with state.lock:
        target_host = state.target_host
        monitoring = state.monitoring
        last_ping_ms = state.last_ping_ms
        window_size = state.window_size
        ping_history = list(state.ping_history)
        total_sent = state.total_sent
        total_recv = state.total_recv
        total_success = state.total_success
        success_rtt_sum = state.success_rtt_sum
        jitter_sum_all = state.jitter_sum_all
        jitter_count_all = state.jitter_count_all
        bw_rx_hist = list(state.bw_rx_mbps_history)
        bw_tx_hist = list(state.bw_tx_mbps_history)
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
    base_t = now - len(ping_history)
    for i, val in enumerate(ping_history):
        ping_history_out.append(
            {
                "t": base_t + i,
                "ms": round(val, 2) if val is not None else None,
                "ok": val is not None,
            }
        )

    bw_history = []
    base_bw = now - len(bw_rx_hist)
    for i in range(len(bw_rx_hist)):
        bw_history.append(
            {
                "t": base_bw + i,
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
    return snapshot


class MonitorService:
    def __init__(self, target_host: str):
        self.state = MonitorState(target_host)
        self._threads: list[threading.Thread] = []
        self.started_at = time.time()
        self.alert_log: deque = deque(maxlen=50)
        self._previously_active: set[str] = set()

    def update_alert_log(self, alerts: list[dict]) -> None:
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


def create_app(monitor: MonitorService, security: ServerSecurity) -> FastAPI:
    app = FastAPI(title="GMS Monitoring")
    app.state.security = security

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

        server = getattr(app.state, "server", None)

        def _stop() -> None:
            if server is not None:
                server.should_exit = True

        loop = asyncio.get_event_loop()
        loop.call_later(0.3, _stop)
        return JSONResponse({"status": "stopping"})

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        origin = websocket.headers.get("origin")
        token = websocket.query_params.get("token")
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

        await websocket.accept()
        try:
            while True:
                snapshot = build_snapshot(monitor.state, monitor)
                await websocket.send_text(json.dumps(snapshot))
                try:
                    raw = await asyncio.wait_for(websocket.receive_text(), timeout=0.05)
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    handle_ws_action(monitor, security, msg)
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
    parser.add_argument("--port", type=int, default=8765, help="HTTP port")
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
    args = parser.parse_args()

    validate_bind_address(args.bind, args.allow_remote)
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
    monitor = MonitorService(args.host)
    monitor.start()
    app = create_app(monitor, security)

    import uvicorn

    config = uvicorn.Config(app, host=args.bind, port=args.port, log_level="info")
    server = uvicorn.Server(config)
    app.state.server = server
    server.run()


if __name__ == "__main__":
    main()
