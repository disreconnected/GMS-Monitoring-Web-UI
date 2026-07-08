import type { SessionStats, StatsBlock } from "../types/monitor";

type StatsPanelProps = {
  title: string;
  stats: (StatsBlock & { session?: SessionStats }) | SessionStats | null;
};

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-sm border border-edge bg-bg/60 p-4">
      <p className="font-mono text-2xl font-medium text-fg">{value}</p>
      <p className="mt-1 text-sm text-fg-muted">{label}</p>
    </div>
  );
}

function fmtMs(v: number | null | undefined) {
  if (v === null || v === undefined) return "-";
  return `${v.toFixed(1)} ms`;
}

export function StatsPanel({ title, stats }: StatsPanelProps) {
  const loss = stats ? `${stats.loss_pct.toFixed(1)}%` : "-";
  const jitter = stats ? fmtMs(stats.jitter_ms) : "-";
  const avg = stats ? fmtMs(stats.avg_ms) : "-";
  const p90 = stats ? fmtMs(stats.p90_ms) : "-";

  return (
    <div className="h-full rounded-sm border border-edge bg-surface/50 p-4 md:p-6">
      <h2 className="mb-4 text-lg font-medium text-fg">{title}</h2>
      <div className="grid grid-cols-2 gap-3">
        <MetricCard label="Packet loss" value={loss} />
        <MetricCard label="Average" value={avg} />
        <MetricCard label="p90" value={p90} />
        <MetricCard label="Jitter" value={jitter} />
      </div>
    </div>
  );
}
