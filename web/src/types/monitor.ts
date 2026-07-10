export type StatsBlock = {
  loss_pct: number;
  lost: number;
  count: number;
  avg_ms: number | null;
  p90_ms: number | null;
  p99_ms: number | null;
  jitter_ms: number | null;
};

export type SessionStats = StatsBlock & {
  sent?: number;
};

export type PingPoint = {
  t: number;
  ms: number | null;
  ok: boolean;
};

export type BandwidthPoint = {
  t: number;
  rx_mbps: number;
  tx_mbps: number;
};

export type Alert = {
  time: number;
  level: "warning" | "error" | "info";
  msg: string;
};

export type TracerouteHop = {
  hop: number;
  host: string;
  ip: string;
  ms: number[];
  timeout: boolean;
};

export type SessionInfo = {
  total_sent: number;
  total_recv: number;
  max_consecutive_rto: number;
  min_rtt_ms: number | null;
  max_rtt_ms: number | null;
  rto_burst_count: number;
  consecutive_rto: number;
  uptime_seconds: number;
};

export type MonitorSnapshot = {
  host: string;
  timestamp: number;
  current_ping: number | null;
  quality: string;
  quality_code: "unknown" | "excellent" | "good" | "fair" | "poor";
  paused: boolean;
  window_size: number;
  window_stats: StatsBlock & { session: SessionStats };
  session_stats: SessionStats;
  ping_history: PingPoint[];
  bandwidth: {
    rx_mbps: number;
    tx_mbps: number;
    avg_rx_mbps: number;
    avg_tx_mbps: number;
    error: string | null;
    history: BandwidthPoint[];
  };
  alerts: Alert[];
  alert_log: Alert[];
  traceroute: {
    running: boolean;
    error: string | null;
    summary: string | null;
    last_run: number | null;
    hops: TracerouteHop[];
  };
  session: SessionInfo;
};

export type ConnectionStatus =
  | "connecting"
  | "connected"
  | "disconnected"
  | "auth_error"
  | "origin_error"
  | "client_limit";

export type AppView = "live" | "report";
