import type { MonitorSnapshot } from "../types/monitor";
import { formatTime } from "../utils/formatTime";
import { ReportGrid, ReportLayoutControls, useReportGrid } from "./ReportGrid";

type ReportViewProps = {
  snapshot: MonitorSnapshot | null;
  isStale: boolean;
};

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

export function ReportView({ snapshot, isStale }: ReportViewProps) {
  const grid = useReportGrid(snapshot);

  if (!snapshot) {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center bg-bg text-fg-muted">
        Waiting for monitor data...
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-bg text-fg">
      {/* Header */}
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-edge px-4 py-2 md:px-6">
        <div>
          <h1 className="text-base font-medium md:text-lg">GMS Network Report</h1>
          <p className="font-mono text-xs text-fg-muted">{snapshot.host}</p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2 md:gap-3">
          <ReportLayoutControls grid={grid} />
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
              Uptime {formatUptime(snapshot.session.uptime_seconds)}
            </p>
          </div>
        </div>
      </div>

      {/*
        Body: a drag-and-resize grid of panels. From md up the default layout
        fills the screen exactly; below that the panels stack and the body scrolls.
      */}
      <ReportGrid snapshot={snapshot} grid={grid} />
    </div>
  );
}
