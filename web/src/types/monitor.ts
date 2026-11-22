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

export type StormshieldBandwidthPoint = {
  t: number;
  rx_mbps: number;
  tx_mbps: number;
};

export type StormshieldInterface = {
  name: string;
  real_name: string;
  type: string;
  addr: string;
  state: number;
  plugged: number;
  protected: number;
  link_mbps: number;
  rx_mbps: number;
  tx_mbps: number;
  avg_rx_mbps: number;
  avg_tx_mbps: number;
  tcp_conn: number;
  udp_conn: number;
  history: StormshieldBandwidthPoint[];
};

export type StormshieldHost = {
  addr: string;
  mac: string;
  name: string;
  interface: string;
  packets: number;
  bytes_in: number;
  bytes_out: number;
  rx_mbps: number;
  tx_mbps: number;
  reputation: number;
  geo: string;
};

export type StormshieldInfo = {
  connected: boolean;
  error: string | null;
  model: string | null;
  version: string | null;
  host: string;
  last_poll: number | null;
  interfaces: StormshieldInterface[];
  hosts: StormshieldHost[];
  host_interfaces: string[];
  hosts_error: string | null;
  hosts_updated_at: number | null;
  /** Interfaces whose host query timed out; retried after retry_at (unix seconds). */
  hosts_slow?: { name: string; retry_at: number }[];
};

export type SnsSavedHost = {
  host: string;
  label: string;
  last_seen: number | null;
};

export type SnsCandidate = {
  host: string;
  reachable: boolean;
  stormshield: boolean;
  latency_ms: number | null;
};

export type SnsState = {
  active_host: string | null;
  password_set: boolean;
  saved_hosts: SnsSavedHost[];
  candidates: SnsCandidate[];
  probed_at: number | null;
  busy: boolean;
  message: string | null;
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
  stormshield?: StormshieldInfo;
  sns?: SnsState;
};

export type ConnectionStatus =
  | "connecting"
  | "connected"
  | "disconnected"
  | "auth_error"
  | "origin_error"
  | "client_limit";

export type AppView = "live" | "report";
