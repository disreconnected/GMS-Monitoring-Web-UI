import type { PingPoint } from "../types/monitor";

type RecentPingsTableProps = {
  pingHistory: PingPoint[];
  compact?: boolean;
};

function formatTime(t: number) {
  return new Date(t * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function latencyClass(ms: number | null, ok: boolean): string {
  if (!ok || ms === null) return "text-danger";
  if (ms < 100) return "text-accent";
  if (ms < 200) return "text-warning";
  return "text-danger";
}

export function RecentPingsTable({ pingHistory, compact = false }: RecentPingsTableProps) {
  const recent = pingHistory.slice(-10).reverse();

  return (
    <div className={`rounded-sm border border-edge bg-surface/50 ${compact ? "p-3" : "p-4 md:p-6"}`}>
      <h2 className={`font-medium text-fg ${compact ? "mb-2 text-sm" : "mb-4 text-lg"}`}>
        Recent pings
      </h2>
      <div className="overflow-x-auto">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-edge text-xs text-fg-muted">
              <th className="pb-2 pr-4 font-medium">Time</th>
              <th className="pb-2 pr-4 font-medium">Latency</th>
              <th className="pb-2 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {recent.length === 0 ? (
              <tr>
                <td colSpan={3} className="py-4 text-sm text-fg-muted">
                  Waiting for ping data...
                </td>
              </tr>
            ) : (
              recent.map((p, i) => (
                <tr key={`${p.t}-${i}`} className="border-b border-edge/50 last:border-0">
                  <td className="py-1.5 pr-4 font-mono text-xs text-fg-muted">
                    {formatTime(p.t)}
                  </td>
                  <td
                    className={`py-1.5 pr-4 font-mono text-xs ${latencyClass(p.ms, p.ok)}`}
                  >
                    {p.ok && p.ms !== null ? `${p.ms.toFixed(1)} ms` : "timeout"}
                  </td>
                  <td className="py-1.5 text-xs">
                    <span
                      className={`inline-block rounded-full px-2 py-0.5 ${
                        p.ok
                          ? "bg-accent/15 text-accent"
                          : "bg-danger/15 text-danger"
                      }`}
                    >
                      {p.ok ? "OK" : "RTO"}
                    </span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
