import type { Alert } from "../types/monitor";

type AlertHistoryPanelProps = {
  alertLog: Alert[];
  compact?: boolean;
  maxHeight?: string;
};

function formatTime(t: number) {
  return new Date(t * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function levelClass(level: Alert["level"]): string {
  if (level === "error") return "text-danger";
  if (level === "warning") return "text-warning";
  return "text-accent";
}

export function AlertHistoryPanel({
  alertLog,
  compact = false,
  maxHeight = "12rem",
}: AlertHistoryPanelProps) {
  return (
    <div className={`rounded-sm border border-edge bg-surface/50 ${compact ? "p-3" : "p-4 md:p-6"}`}>
      <h2 className={`font-medium text-fg ${compact ? "mb-2 text-sm" : "mb-4 text-lg"}`}>
        Alert history
      </h2>
      <div className="overflow-y-auto" style={{ maxHeight }}>
        {alertLog.length === 0 ? (
          <p className="text-sm text-fg-muted">No alerts recorded this session.</p>
        ) : (
          <ul className="space-y-2">
            {alertLog.map((alert, i) => (
              <li
                key={`${alert.time}-${alert.msg}-${i}`}
                className="flex items-start gap-3 border-b border-edge/50 pb-2 last:border-0"
              >
                <span className="shrink-0 font-mono text-xs text-fg-muted">
                  {formatTime(alert.time)}
                </span>
                <span className={`text-xs font-medium uppercase ${levelClass(alert.level)}`}>
                  {alert.level}
                </span>
                <span className="text-sm text-fg">{alert.msg}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
