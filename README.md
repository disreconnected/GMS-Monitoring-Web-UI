# GMS Monitoring Web UI

Real-time network monitoring dashboard for ICMP ping, packet loss, latency, jitter, bandwidth, and traceroute — built for technical reporting during service ministry sessions.

The project includes:

- **Web dashboard** — React live dashboard plus a single-screen **Report** view for screenshots
- **Terminal UI** — original `gms_monitor.py` curses TUI (still available)

Default monitor target: `www.youtube.com` (configurable).

---

## Features

### Web dashboard

| Area | What it shows |
|------|----------------|
| **Live view** | Real-time metrics, latency & bandwidth charts, traceroute hops, last 10 pings, session details, alert ticker & history |
| **Report view** | One-screen layout designed for a single screenshot — key metrics, recent pings, full traceroute table, alerts |
| **Charts** | Shared time scale: **Live** (per ping), 1m, 5m, 10m, 15m, 30m, 1h — bucketed by max value per interval |
| **Latency chart** | Y-axis capped at 150 ms; spikes above 150 ms are labeled with the real value |
| **Controls** | Pause / resume monitoring, re-run traceroute, stop server |
| **Theme** | Light / dark toggle (persisted in browser) |
| **Languages** | English and Indonesian (`--lang en` / `--lang id`) |

### Core monitoring (shared with TUI)

- Periodic ICMP ping (1 Hz) to a configurable host
- Packet loss, average latency, p90 / p99, jitter
- Quality rating: Excellent / Good / Fair / Poor
- Bandwidth RX/TX sampling and anomaly alerts
- Traceroute with hop-by-hop RTT
- Consecutive RTO (timeout) tracking
- Alert log for spikes and loss events

### Terminal UI

`gms_monitor.py` remains the original curses-based monitor. See [Terminal usage](#terminal-usage-tui) below.

---

## Requirements

### Runtime (web server)

| Requirement | Notes |
|-------------|--------|
| **Python 3.10+** | 3.11 recommended |
| **Node.js 18+** | Required to build the frontend (`npm` on PATH) |
| **ICMP ping** | Windows: built-in `ping`; macOS/Linux: `ping` in PATH |
| **Traceroute** | Windows: `tracert`; macOS/Linux: `traceroute` |
| **OS** | Developed and tested on **Windows**; TUI and probes also work on Unix-like systems |

### Python packages

Installed automatically by `run_gms_web.bat`:

```
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
websockets>=12.0
```

### Frontend stack

React 19, Vite 6, TypeScript, Tailwind CSS v4, Recharts, GSAP, Motion — see `web/package.json`.

---

## Quick start (Windows)

From the repository root:

```bat
run_gms_web.bat
```

This script will:

1. Resolve Python (via `_resolve_python.bat`)
2. Install `requirements_web.txt`
3. Build the frontend if `web/dist/` is missing (`npm install` + `npm run build`)
4. Start the server at **http://127.0.0.1:8765**

Open that URL in your browser. Use the **Live** tab for monitoring and **Report** for a screenshot-ready summary.

### Stop the server

**From the UI:** Top bar → **Stop** (confirmation required).

**From the command line:**

```bat
stop_gms_web.bat
```

Optional custom port:

```bat
stop_gms_web.bat 9000
```

---

## Manual setup

### 1. Python backend

```bash
pip install -r requirements_web.txt
```

### 2. Frontend build

```bash
cd web
npm install
npm run build
```

### 3. Start server

```bash
python gms_web_server.py
```

With options:

```bash
python gms_web_server.py --host example.com --bind 127.0.0.1 --port 8765 --lang id
```

| Option | Default | Description |
|--------|---------|-------------|
| `--host` | `www.youtube.com` | Target host to ping and traceroute |
| `--bind` | `127.0.0.1` | HTTP bind address |
| `--port` | `8765` | HTTP port |
| `--lang` | `en` | UI language (`en` or `id`) |

### Frontend development (hot reload)

Terminal 1 — API server:

```bash
python gms_web_server.py
```

Terminal 2 — Vite dev server (proxies `/api` and `/ws`):

```bash
cd web
npm install
npm run dev
```

Open the Vite URL (usually http://localhost:5173).

---

## Project layout

```
gmsmonitoring/
├── gms_monitor.py        # Core monitor + TUI
├── gms_web_server.py     # FastAPI server + WebSocket
├── requirements_web.txt
├── run_gms_web.bat       # Start web server (Windows)
├── stop_gms_web.bat      # Stop process on port (Windows)
├── lang_en.txt           # English strings
├── lang_id.txt           # Indonesian strings
└── web/
    ├── src/              # React source
    ├── dist/             # Production build (generated)
    └── package.json
```

---

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Serves the React app (when `web/dist` exists) |
| `/ws` | WebSocket | Live monitor snapshots (~1 Hz); accepts control JSON |
| `/api/shutdown` | POST | Gracefully stops the uvicorn server |

### WebSocket control messages

Send JSON on `/ws`:

```json
{ "action": "pause" }
{ "action": "resume" }
{ "action": "traceroute" }
{ "action": "set_window", "size": 60 }
```

---

## Security notes

The web server is intended as a **local monitoring tool**:

- Default bind is **loopback only** (`127.0.0.1:8765`).
- There is **no authentication** on `/ws` or `/api/shutdown`.
- Binding to `0.0.0.0` or a LAN address (`run_gms_web.bat --bind 0.0.0.0`) exposes control and telemetry to the network — avoid unless you understand the risk and add your own access controls.

For shared or remote deployments, place the service behind a reverse proxy with authentication and firewall rules.

---

## Terminal usage (TUI)

```bash
python gms_monitor.py [--lang LANG] [--host HOST]
```

| Key | Action |
|-----|--------|
| `P` | Pause monitoring |
| `R` | Resume monitoring |
| `T` | Run traceroute |
| `F` | Toggle traceroute summary / full table |
| `L` | Cycle language |
| `+` / `-` | Increase / decrease stats window |
| `Q` | Quit |

Localization files: `lang_en.txt`, `lang_id.txt`. Add a new `lang_xx.txt` and register the code in `SUPPORTED_LANGS` inside `gms_monitor.py`.

---

## Troubleshooting

| Problem | What to try |
|---------|-------------|
| `npm not found` | Install [Node.js](https://nodejs.org/) and re-run `run_gms_web.bat`, or build manually under `web/` |
| Blank page / "Frontend not built" | `cd web && npm install && npm run build` |
| Port already in use | `stop_gms_web.bat` or pass `--port` with a different value |
| WebSocket disconnected | Confirm `gms_web_server.py` is running; check firewall for non-loopback binds |
| Ping always times out | Verify the target host is reachable; on Windows, ICMP may need elevated rights for some targets |

---

## License

See repository license file if present; otherwise treat as project-internal tooling unless otherwise specified by the maintainer.
