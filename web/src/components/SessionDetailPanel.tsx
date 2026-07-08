import type { SessionInfo } from "../types/monitor";

type SessionDetailPanelProps = {
  session: SessionInfo | null;
  compact?: boolean;
};

function formatUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-sm border border-edge bg-bg/60 p-3">
      <p className="font-mono text-lg font-medium text-fg">{value}</p>
      <p className="mt-0.5 text-xs text-fg-muted">{label}</p>
    </div>
  );
}

export function SessionDetailPanel({ session, compact = false }: SessionDetailPanelProps) {
  const minRtt =
    session?.min_rtt_ms !== null && session?.min_rtt_ms !== undefined
      ? `${session.min_rtt_ms.toFixed(1)} ms`
      : "-";
  const maxRtt =
    session?.max_rtt_ms !== null && session?.max_rtt_ms !== undefined
      ? `${session.max_rtt_ms.toFixed(1)} ms`
      : "-";
  const uptime = session ? formatUptime(session.uptime_seconds) : "-";

  return (
    <div className={`rounded-sm border border-edge bg-surface/50 ${compact ? "p-3" : "p-4 md:p-6"}`}>
      <h2 className={`font-medium text-fg ${compact ? "mb-2 text-sm" : "mb-4 text-lg"}`}>
        Session details
      </h2>
      <div className={`grid grid-cols-2 gap-2 ${compact ? "" : "gap-3"}`}>
        <MetricCard label="Min RTT" value={minRtt} />
        <MetricCard label="Max RTT" value={maxRtt} />
        <MetricCard
          label="RTO bursts"
          value={session ? String(session.rto_burst_count) : "-"}
        />
        <MetricCard
          label="Current timeout streak"
          value={session ? String(session.consecutive_rto) : "-"}
        />
        <MetricCard label="Session uptime" value={uptime} />
        <MetricCard
          label="Max consecutive RTO"
          value={session ? String(session.max_consecutive_rto) : "-"}
        />
      </div>
    </div>
  );
}
