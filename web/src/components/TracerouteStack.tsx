import { ArrowClockwise } from "@phosphor-icons/react";
import type { MonitorSnapshot } from "../types/monitor";

type TracerouteStackProps = {
  snapshot: MonitorSnapshot | null;
  onRerun: () => void;
};

function hopLabel(hop: { host: string; ip: string }) {
  if (hop.host === "?" && !hop.ip) return "timeout";
  if (hop.ip && hop.ip !== hop.host) return `${hop.host} (${hop.ip})`;
  return hop.host;
}

export function TracerouteStack({ snapshot, onRerun }: TracerouteStackProps) {
  const hops = [...(snapshot?.traceroute.hops ?? [])].sort((a, b) => b.hop - a.hop);
  const running = snapshot?.traceroute.running ?? false;

  return (
    <section className="px-4 py-12 md:px-8">
      <div className="mx-auto grid max-w-7xl gap-8 md:grid-cols-[1fr_1.4fr]">
        <div className="md:sticky md:top-28 md:self-start">
          <h2 className="text-2xl font-medium tracking-tight text-fg">Path to host</h2>
          <p className="mt-2 max-w-md text-sm text-fg-muted">
            {running
              ? "Traceroute is running..."
              : snapshot?.traceroute.summary || "Hop-by-hop route to the monitored target."}
          </p>
          <button
            type="button"
            onClick={onRerun}
            disabled={running}
            className="mt-4 inline-flex items-center gap-2 rounded-full bg-accent px-4 py-2 text-sm font-medium text-white transition active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50"
          >
            <ArrowClockwise size={16} />
            Re-run
          </button>
          {snapshot?.traceroute.error && (
            <p className="mt-3 text-sm text-danger">{snapshot.traceroute.error}</p>
          )}
        </div>

        <div className="rounded-sm border border-edge bg-surface/50 p-3 md:p-4">
          {hops.length === 0 ? (
            <p className="py-6 text-sm text-fg-muted">Waiting for traceroute data...</p>
          ) : (
            <div className="max-h-[min(70vh,32rem)] overflow-y-auto">
              <table className="w-full text-left">
                <thead className="sticky top-0 bg-surface">
                  <tr className="border-b border-edge text-xs text-fg-muted">
                    <th className="pb-2 pr-3 font-medium">#</th>
                    <th className="pb-2 pr-3 font-medium">Host</th>
                    <th className="pb-2 pr-3 font-medium">Avg ms</th>
                    <th className="pb-2 font-medium">Samples</th>
                  </tr>
                </thead>
                <tbody>
                  {hops.map((hop) => {
                    const avg =
                      hop.ms.length > 0
                        ? hop.ms.reduce((a, b) => a + b, 0) / hop.ms.length
                        : null;
                    return (
                      <tr key={hop.hop} className="border-b border-edge/50 last:border-0">
                        <td className="py-1.5 pr-3 font-mono text-xs text-fg-muted">
                          {hop.hop}
                        </td>
                        <td className="max-w-[200px] truncate py-1.5 pr-3 text-xs text-fg">
                          {hopLabel(hop)}
                        </td>
                        <td
                          className={`py-1.5 pr-3 font-mono text-xs ${
                            hop.timeout ? "text-danger" : "text-accent"
                          }`}
                        >
                          {hop.timeout ? "timeout" : `${avg?.toFixed(1)} ms`}
                        </td>
                        <td className="py-1.5 font-mono text-[10px] text-fg-muted">
                          {!hop.timeout && hop.ms.length > 0
                            ? hop.ms.map((m) => m.toFixed(1)).join(", ")
                            : "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
