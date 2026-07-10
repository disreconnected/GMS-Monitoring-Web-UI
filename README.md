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
| **Security** | Per-run access token, authenticated WebSocket/shutdown, loopback-only by default |
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
3. Install frontend dependencies if needed (`npm install`)
4. Rebuild the frontend (`npm run build`) so the served UI matches the current code
5. Start the server (default bind: `127.0.0.1:8765`)

**Open the secure URL printed by the server** — not a bookmarked address. It includes a one-time access token in the URL fragment (`#token=...`). After each restart, use the new URL. Use the **Live** tab for monitoring and **Report** for a screenshot-ready summary.

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

The server prints a **secure dashboard URL** on startup. Open that exact URL in your browser. After each restart, use the new URL (the token changes every run).

| Option | Default | Description |
|--------|---------|-------------|
| `--host` | `www.youtube.com` | Target host to ping and traceroute |
| `--bind` | `127.0.0.1` | HTTP bind address (loopback only unless remote mode) |
| `--port` | `8765` | HTTP port |
| `--lang` | `en` | UI language (`en` or `id`) |
| `--allow-remote` | off | Allow non-loopback bind; requires `--access-token` |
| `--access-token` | *(generated)* | Shared control token for remote mode (min 16 chars) |
| `--allowed-origin` | — | Extra allowed browser `Origin` (repeatable; for Vite dev) |
| `--max-ws-clients` | `5` | Maximum concurrent WebSocket clients |

### Frontend development (hot reload)

Terminal 1 — API server (allow the Vite dev origin):

```bash
python gms_web_server.py --allowed-origin http://localhost:5173
```

Copy the secure URL from the server output, change the host/port to `http://localhost:5173`, and keep the `#token=...` fragment. Example:

```
http://localhost:5173/#token=<token-from-server-output>
```

Terminal 2 — Vite dev server (proxies `/api` and `/ws`):

```bash
cd web
npm install
npm run dev
```

Open the modified secure URL above (not a bare `http://localhost:5173/`).

---

## Project layout

```
gmsmonitoring/
├── gms_monitor.py           # Core monitor + TUI
├── gms_web_server.py        # FastAPI server + WebSocket (with auth)
├── test_gms_web_security.py # Security regression tests
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

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/` | GET | — | Serves the React app (when `web/dist` exists) |
| `/ws?token=...` | WebSocket | `token` query param + allowed `Origin` (or loopback client in local mode) | Live monitor snapshots (~1 Hz); accepts control JSON |
| `/api/shutdown` | POST | `X-GMS-Token` header + loopback client | Gracefully stops the uvicorn server |

### WebSocket control messages

Send JSON on an authenticated `/ws` connection:

```json
{ "action": "pause" }
{ "action": "resume" }
{ "action": "traceroute" }
{ "action": "set_window", "size": 60 }
```

---

## Security

The web server is a **local monitoring tool** with a per-run control token and authenticated control plane.

### What was hardened

| Area | Protection |
|------|------------|
| **WebSocket `/ws`** | Requires valid per-run token; validates browser `Origin` (with loopback fallback for embedded browsers) |
| **Shutdown `/api/shutdown`** | Requires `X-GMS-Token` header; loopback-only in local mode |
| **Network bind** | Non-loopback addresses blocked unless `--allow-remote` + `--access-token` |
| **Control commands** | Input validation, traceroute throttle (10 s), max 5 WebSocket clients |
| **Frontend delivery** | `index.html` served with no-cache headers; launcher rebuilds UI on every start |
| **Stop script** | `stop_gms_web.bat` only kills `gms_web_server.py` processes on the target port |

### Default (local) mode

- Binds to **loopback only** (`127.0.0.1:8765`). Non-loopback addresses are rejected unless remote mode is enabled.
- Generates a random **access token** on each startup.
- Prints a secure dashboard URL: `http://127.0.0.1:8765/#token=<token>`
- The token lives in the URL **fragment** (not sent in HTTP requests or server logs).
- The React client reads the fragment once, keeps the token in memory, and sends it as:
  - WebSocket query param: `/ws?token=...`
  - HTTP header for shutdown: `X-GMS-Token`
- WebSocket handshakes require a matching browser `Origin`, or a loopback client when `Origin` is omitted (common in embedded/IDE browsers).
- Shutdown is allowed only from **loopback** clients with a valid token.
- Manual traceroute requests are throttled (10 s cooldown).
- WebSocket clients are capped (default: 5).

### Remote / LAN mode

Explicit opt-in only:

```bash
python gms_web_server.py --allow-remote --bind 0.0.0.0 --access-token "your-long-secret-token"
```

- Requires an operator-provided token (minimum 16 characters).
- Prints a prominent exposure warning.
- Does **not** print the token in the dashboard URL.
- Shutdown remains token-gated (loopback restriction is lifted in remote mode).
- Missing `Origin` is **not** allowed in remote mode.

### Stop script scope

`stop_gms_web.bat` only terminates processes whose command line contains `gms_web_server.py`. It will not kill unrelated services sharing the same port.

### Running security tests

```bash
python -m unittest test_gms_web_security.py -v
```

### Threat model

This hardening blocks casual localhost CSRF, cross-site WebSocket hijacking (CSWSH), and accidental LAN exposure. It does **not** replace full authentication for internet-facing deployments — use a reverse proxy with auth and firewall rules for that.

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
| "Unauthorized" banner | Open the secure URL printed at server startup; after restart, use the new URL |
| Stuck on "Connecting..." / WebSocket 403 | Hard-refresh (`Ctrl+Shift+R`), or restart via `run_gms_web.bat` and open the fresh secure URL |
| Vite dev won't connect | Start server with `--allowed-origin http://localhost:5173` and open `http://localhost:5173/#token=...` |
| WebSocket disconnected | Confirm `gms_web_server.py` is running; check firewall for non-loopback binds |
| Ping always times out | Verify the target host is reachable; on Windows, ICMP may need elevated rights for some targets |

---

## License

See repository license file if present; otherwise treat as project-internal tooling unless otherwise specified by the maintainer.
