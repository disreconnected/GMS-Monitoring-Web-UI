#!/usr/bin/env python3
"""FastAPI WebSocket server for GMS Monitoring web dashboard."""

from __future__ import annotations

import argparse
import asyncio
import json
import threading
import time
from collections import deque
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
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


def create_app(monitor: MonitorService) -> FastAPI:
    app = FastAPI(title="GMS Monitoring")

    @app.post("/api/shutdown")
    async def shutdown_server() -> JSONResponse:
        server = getattr(app.state, "server", None)

        def _stop() -> None:
            if server is not None:
                server.should_exit = True

        loop = asyncio.get_event_loop()
        loop.call_later(0.3, _stop)
        return JSONResponse({"status": "stopping"})

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            while True:
                snapshot = build_snapshot(monitor.state, monitor)
                await websocket.send_text(json.dumps(snapshot))
                try:
                    raw = await asyncio.wait_for(websocket.receive_text(), timeout=0.05)
                    msg = json.loads(raw)
                    action = msg.get("action")
                    if action == "pause":
                        monitor.pause()
                    elif action == "resume":
                        monitor.resume()
                    elif action == "traceroute":
                        monitor.rerun_traceroute()
                    elif action == "set_window":
                        size = int(msg.get("size", 60))
                        monitor.set_window_size(size)
                except asyncio.TimeoutError:
                    pass
                await asyncio.sleep(1.0)
        except WebSocketDisconnect:
            return

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
                return FileResponse(index)
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
    args = parser.parse_args()

    set_language(args.lang)
    monitor = MonitorService(args.host)
    monitor.start()
    app = create_app(monitor)

    import uvicorn

    config = uvicorn.Config(app, host=args.bind, port=args.port, log_level="info")
    server = uvicorn.Server(config)
    app.state.server = server
    server.run()


if __name__ == "__main__":
    main()
