import type { MonitorSnapshot } from "../types/monitor";
import { RecentPingsTable } from "./RecentPingsTable";

type ReportViewProps = {
  snapshot: MonitorSnapshot | null;
  isStale: boolean;
};

function formatTime(t: number) {
  return new Date(t * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function qualityClass(code: MonitorSnapshot["quality_code"] | undefined): string {
  switch (code) {
    case "excellent":
      return "bg-accent/20 text-accent border-accent/30";
    case "good":
      return "bg-emerald-500/20 text-emerald-600 border-emerald-500/30";
    case "fair":
      return "bg-warning/20 text-warning border-warning/30";
    case "poor":
      return "bg-danger/20 text-danger border-danger/30";
    default:
      return "bg-surface text-fg-muted border-edge";
  }
}

function hopLabel(hop: { host: string; ip: string }) {
  if (hop.host === "?" && !hop.ip) return "timeout";
  if (hop.ip && hop.ip !== hop.host) return `${hop.host} (${hop.ip})`;
  return hop.host;
}

function levelClass(level: string): string {
  if (level === "error") return "text-danger";
  if (level === "warning") return "text-warning";
  return "text-accent";
}

export function ReportView({ snapshot, isStale }: ReportViewProps) {
  if (!snapshot) {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center bg-bg text-fg-muted">
        Waiting for monitor data...
      </div>
    );
  }

  const hops = snapshot.traceroute?.hops ?? [];
  const recentAlerts = snapshot.alert_log.slice(0, 5);
  const session = snapshot.session;

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-bg text-fg">
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between border-b border-edge px-4 py-2 md:px-6">
        <div>
          <h1 className="text-base font-medium md:text-lg">GMS Network Report</h1>
          <p className="font-mono text-xs text-fg-muted">{snapshot.host}</p>
        </div>
        <div className="flex items-center gap-2 md:gap-3">
          <span
            className={`rounded-full border px-2 py-0.5 text-xs font-medium ${qualityClass(snapshot.quality_code)}`}
          >
            {snapshot.quality}
          </span>
          {isStale && (
            <span className="rounded-full border border-warning/30 bg-warning/10 px-2 py-0.5 text-xs text-warning">
              Stale
            </span>
          )}
          <div className="text-right">
            <p className="font-mono text-[10px] text-fg-muted md:text-xs">
              As of {formatTime(snapshot.timestamp)}
            </p>
            <p className="font-mono text-[10px] text-fg-muted md:text-xs">
              Uptime {formatUptime(session.uptime_seconds)}
            </p>
          </div>
        </div>
      </div>

      {/* Metrics strip */}
      <div className="grid shrink-0 grid-cols-5 gap-1 border-b border-edge px-3 py-1.5 md:gap-2 md:px-6 md:py-2">
        <div className="rounded-sm border border-edge bg-surface/50 p-1.5 text-center">
          <p className="font-mono text-xs font-medium md:text-sm">
            {snapshot.window_stats.loss_pct.toFixed(1)}%
          </p>
          <p className="text-[9px] text-fg-muted md:text-[10px]">Loss</p>
        </div>
        <div className="rounded-sm border border-edge bg-surface/50 p-1.5 text-center">
          <p className="font-mono text-xs font-medium md:text-sm">
            {snapshot.window_stats.avg_ms?.toFixed(1) ?? "-"}
          </p>
          <p className="text-[9px] text-fg-muted md:text-[10px]">Avg</p>
        </div>
        <div className="rounded-sm border border-edge bg-surface/50 p-1.5 text-center">
          <p className="font-mono text-xs font-medium md:text-sm">
            {snapshot.window_stats.p90_ms?.toFixed(1) ?? "-"}
          </p>
          <p className="text-[9px] text-fg-muted md:text-[10px]">p90</p>
        </div>
        <div className="rounded-sm border border-edge bg-surface/50 p-1.5 text-center">
          <p className="font-mono text-xs font-medium md:text-sm">
            {snapshot.window_stats.p99_ms?.toFixed(1) ?? "-"}
          </p>
          <p className="text-[9px] text-fg-muted md:text-[10px]">p99</p>
        </div>
        <div className="rounded-sm border border-edge bg-surface/50 p-1.5 text-center">
          <p className="font-mono text-xs font-medium md:text-sm">
            {snapshot.window_stats.jitter_ms?.toFixed(1) ?? "-"}
          </p>
          <p className="text-[9px] text-fg-muted md:text-[10px]">Jitter</p>
        </div>
      </div>

      {/* Compact summary strip: bandwidth + session */}
      <div className="grid shrink-0 grid-cols-2 gap-1 border-b border-edge px-3 py-1.5 text-[10px] md:grid-cols-4 md:gap-2 md:px-6 md:py-2 md:text-xs">
        <div className="rounded-sm border border-edge bg-surface/40 px-2 py-1">
          <span className="text-fg-muted">RX </span>
          <span className="font-mono text-accent">{snapshot.bandwidth.rx_mbps.toFixed(2)}</span>
          <span className="text-fg-muted"> / avg {snapshot.bandwidth.avg_rx_mbps.toFixed(2)} Mbps</span>
        </div>
        <div className="rounded-sm border border-edge bg-surface/40 px-2 py-1">
          <span className="text-fg-muted">TX </span>
          <span className="font-mono text-warning">{snapshot.bandwidth.tx_mbps.toFixed(2)}</span>
          <span className="text-fg-muted"> / avg {snapshot.bandwidth.avg_tx_mbps.toFixed(2)} Mbps</span>
        </div>
        <div className="rounded-sm border border-edge bg-surface/40 px-2 py-1">
          <span className="text-fg-muted">Min/Max RTT </span>
          <span className="font-mono">
            {session.min_rtt_ms?.toFixed(1) ?? "-"} / {session.max_rtt_ms?.toFixed(1) ?? "-"} ms
          </span>
        </div>
        <div className="rounded-sm border border-edge bg-surface/40 px-2 py-1">
          <span className="text-fg-muted">RTO </span>
          <span className="font-mono">
            bursts {session.rto_burst_count}, streak {session.consecutive_rto}
          </span>
        </div>
      </div>

      {/* Body — constrained scroll areas only */}
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-2 overflow-hidden p-2 md:grid-cols-2 md:gap-3 md:p-3">
        <div className="flex min-h-0 flex-col overflow-hidden">
          <div className="min-h-0 flex-1 overflow-y-auto">
            <RecentPingsTable pingHistory={snapshot.ping_history} compact />
          </div>
        </div>

        <div className="flex min-h-0 flex-col overflow-hidden rounded-sm border border-edge bg-surface/50 p-2 md:p-3">
          <h2 className="mb-1 shrink-0 text-xs font-medium text-fg md:text-sm">Traceroute</h2>
          <div className="min-h-0 flex-1 overflow-y-auto">
            <table className="w-full text-left">
              <thead className="sticky top-0 bg-surface">
                <tr className="border-b border-edge text-[10px] text-fg-muted">
                  <th className="pb-1 pr-2 font-medium">#</th>
                  <th className="pb-1 pr-2 font-medium">Host</th>
                  <th className="pb-1 font-medium">Avg ms</th>
                </tr>
              </thead>
              <tbody>
                {hops.length === 0 ? (
                  <tr>
                    <td colSpan={3} className="py-3 text-xs text-fg-muted">
                      No traceroute data
                    </td>
                  </tr>
                ) : (
                  hops.map((hop) => {
                    const avg =
                      hop.ms.length > 0
                        ? hop.ms.reduce((a, b) => a + b, 0) / hop.ms.length
                        : null;
                    return (
                      <tr key={hop.hop} className="border-b border-edge/50 last:border-0">
                        <td className="py-0.5 pr-2 font-mono text-[10px] text-fg-muted md:text-xs">
                          {hop.hop}
                        </td>
                        <td className="max-w-[140px] truncate py-0.5 pr-2 text-[10px] text-fg md:text-xs">
                          {hopLabel(hop)}
                        </td>
                        <td
                          className={`py-0.5 font-mono text-[10px] md:text-xs ${
                            hop.timeout ? "text-danger" : "text-accent"
                          }`}
                        >
                          {hop.timeout ? "timeout" : `${avg?.toFixed(1)} ms`}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Footer - alerts */}
      <div className="shrink-0 overflow-hidden border-t border-edge bg-bg px-3 py-1.5 md:px-6 md:py-2">
        <p className="mb-0.5 text-[9px] font-medium uppercase tracking-wider text-fg-muted md:text-[10px]">
          Recent alerts
        </p>
        {recentAlerts.length === 0 ? (
          <p className="truncate text-[10px] text-fg-muted md:text-xs">No active alerts</p>
        ) : (
          <div className="flex flex-wrap gap-x-3 gap-y-0.5 overflow-hidden">
            {recentAlerts.map((alert, i) => (
              <span key={`${alert.time}-${i}`} className="truncate text-[10px] md:text-xs">
                <span className="font-mono text-fg-muted">{formatTime(alert.time)}</span>{" "}
                <span className={levelClass(alert.level)}>{alert.msg}</span>
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
