import type { ReactNode } from "react";
import type {
  MonitorSnapshot,
  StormshieldInfo,
  StormshieldInterface,
} from "../types/monitor";
import { formatMbps } from "../utils/formatBandwidth";
import { formatHostsSlow, formatTime } from "../utils/formatTime";
import { RecentPingsTable } from "./RecentPingsTable";

// ---------------------------------------------------------------------------
// Panel frame
// ---------------------------------------------------------------------------

type ReportPanelProps = {
  /** A plain string gets the standard panel-title style; a node is rendered as given. */
  title: ReactNode;
  /** Right-aligned header content (captions); truncates when the panel is narrow. */
  extra?: ReactNode;
  /** Edit mode: shows the drag grip. */
  editing?: boolean;
  /** Edit mode: when set, shows a button that removes the panel from the grid. */
  onHide?: () => void;
  /** Charts size themselves to the body and must not scroll; text panels scroll when short. */
  scroll?: boolean;
  children: ReactNode;
};

function GripIcon() {
  return (
    <svg viewBox="0 0 10 14" width="10" height="14" fill="currentColor" aria-hidden="true">
      <circle cx="2.5" cy="2.5" r="1.2" />
      <circle cx="7.5" cy="2.5" r="1.2" />
      <circle cx="2.5" cy="7" r="1.2" />
      <circle cx="7.5" cy="7" r="1.2" />
      <circle cx="2.5" cy="11.5" r="1.2" />
      <circle cx="7.5" cy="11.5" r="1.2" />
    </svg>
  );
}

/**
 * Bordered card with a small header row. The body is a size container, so
 * content can reflow with the panel's own width (`@min-[...]:` variants).
 */
export function ReportPanel({
  title,
  extra,
  editing = false,
  onHide,
  scroll = true,
  children,
}: ReportPanelProps) {
  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-sm border border-edge bg-surface/50 p-2">
      <header className="mb-1 flex shrink-0 items-center gap-1.5">
        {editing && (
          <span
            className="panel-drag flex h-4 w-4 shrink-0 cursor-move touch-none items-center justify-center text-fg-muted hover:text-fg"
            title="Drag to move"
          >
            <GripIcon />
          </span>
        )}
        <h2 className={`min-w-0 truncate ${extra ? "shrink-0" : "flex-1"}`}>
          {typeof title === "string" ? (
            <span className="text-xs font-medium text-fg md:text-sm">{title}</span>
          ) : (
            title
          )}
        </h2>
        {extra && <div className="min-w-0 flex-1 truncate text-right">{extra}</div>}
        {editing && onHide && (
          <button
            type="button"
            onClick={onHide}
            className="flex h-4 w-4 shrink-0 items-center justify-center rounded-sm text-sm leading-none text-fg-muted hover:text-fg"
            aria-label="Hide panel"
            title="Hide panel"
          >
            ×
          </button>
        )}
      </header>
      <div className={`@container min-h-0 flex-1 ${scroll ? "overflow-y-auto" : "overflow-hidden"}`}>
        {children}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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

function firewallPillClass(connected: boolean): string {
  return connected
    ? "bg-accent/20 text-accent border-accent/30"
    : "bg-warning/20 text-warning border-warning/30";
}

const SMALL_LABEL =
  "text-[9px] font-medium uppercase tracking-wider text-fg-muted md:text-[10px]";

// ---------------------------------------------------------------------------
// Panel bodies
// ---------------------------------------------------------------------------

export function MetricsBody({ snapshot }: { snapshot: MonitorSnapshot }) {
  const stats = snapshot.window_stats;
  const tiles = [
    { label: "Loss", value: `${stats.loss_pct.toFixed(1)}%` },
    { label: "Avg", value: stats.avg_ms?.toFixed(1) ?? "-" },
    { label: "p90", value: stats.p90_ms?.toFixed(1) ?? "-" },
    { label: "p99", value: stats.p99_ms?.toFixed(1) ?? "-" },
    { label: "Jitter", value: stats.jitter_ms?.toFixed(1) ?? "-" },
  ];
  return (
    <div className="grid grid-cols-2 gap-1 @min-[200px]:grid-cols-3 @min-[300px]:grid-cols-5 md:gap-2">
      {tiles.map((tile) => (
        <div
          key={tile.label}
          className="rounded-sm border border-edge bg-surface/50 p-1.5 text-center"
        >
          <p className="font-mono text-xs font-medium md:text-sm">{tile.value}</p>
          <p className="text-[9px] text-fg-muted md:text-[10px]">{tile.label}</p>
        </div>
      ))}
    </div>
  );
}

export function SummaryBody({ snapshot }: { snapshot: MonitorSnapshot }) {
  const session = snapshot.session;
  return (
    <div className="grid grid-cols-2 gap-1 text-[10px] @min-[720px]:grid-cols-4 md:gap-2 md:text-xs">
      <div className="rounded-sm border border-edge bg-surface/40 px-2 py-1">
        <span className="text-fg-muted">RX </span>
        <span className="font-mono text-accent">{snapshot.bandwidth.rx_mbps.toFixed(2)}</span>
        <span className="text-fg-muted">
          {" "}
          / avg {snapshot.bandwidth.avg_rx_mbps.toFixed(2)} Mbps
        </span>
      </div>
      <div className="rounded-sm border border-edge bg-surface/40 px-2 py-1">
        <span className="text-fg-muted">TX </span>
        <span className="font-mono text-warning">{snapshot.bandwidth.tx_mbps.toFixed(2)}</span>
        <span className="text-fg-muted">
          {" "}
          / avg {snapshot.bandwidth.avg_tx_mbps.toFixed(2)} Mbps
        </span>
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
  );
}

/** Connection state plus one compact chip per plugged interface. */
export function FirewallBody({
  firewall,
  interfaces,
}: {
  firewall: StormshieldInfo;
  interfaces: StormshieldInterface[];
}) {
  const meta = [firewall.host, firewall.model, firewall.version].filter(Boolean).join(" · ");
  return (
    <div className="h-full overflow-y-auto">
      <div className="mb-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5">
        <span
          className={`shrink-0 rounded-full border px-2 py-0.5 text-xs font-medium ${firewallPillClass(firewall.connected)}`}
        >
          {firewall.connected ? "Connected" : "Disconnected"}
        </span>
        {meta && (
          <span className="min-w-0 truncate font-mono text-[10px] text-fg-muted md:text-xs">
            {meta}
          </span>
        )}
        {firewall.error && (
          <span
            className="min-w-0 flex-1 truncate text-[10px] text-warning md:text-xs"
            title={firewall.error}
          >
            {firewall.error}
          </span>
        )}
      </div>
      {interfaces.length === 0 ? (
        <p className="text-[10px] text-fg-muted md:text-xs">No active interfaces</p>
      ) : (
        <div className="flex flex-wrap gap-1">
          {interfaces.map((iface) => (
            <div
              key={iface.name}
              className="whitespace-nowrap rounded-sm border border-edge bg-surface/40 px-1.5 py-0.5 text-[10px]"
            >
              <span className="font-medium text-fg">{iface.name}</span>{" "}
              <span className="text-[9px] text-fg-muted">
                {iface.protected === 1 ? "LAN" : "WAN"}
              </span>{" "}
              <span className="font-mono">
                <span className="text-fg-muted">In </span>
                <span className="text-accent">{formatMbps(iface.rx_mbps)}</span>
                <span className="text-fg-muted"> / Out </span>
                <span className="text-warning">{formatMbps(iface.tx_mbps)}</span>
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function TracerouteBody({ snapshot }: { snapshot: MonitorSnapshot }) {
  const hops = snapshot.traceroute?.hops ?? [];
  return (
    <div className="h-full overflow-y-auto">
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
                hop.ms.length > 0 ? hop.ms.reduce((a, b) => a + b, 0) / hop.ms.length : null;
              return (
                <tr key={hop.hop} className="border-b border-edge/50 last:border-0">
                  <td className="py-0.5 pr-2 font-mono text-[10px] text-fg-muted md:text-xs">
                    {hop.hop}
                  </td>
                  <td className="max-w-[140px] truncate py-0.5 pr-2 text-[10px] text-fg md:max-w-[260px] md:text-xs">
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
  );
}

/**
 * RecentPingsTable draws its own card and heading, which the panel frame already
 * provides; strip the inner ones with child selectors rather than fork the table.
 */
export function PingsBody({ snapshot }: { snapshot: MonitorSnapshot }) {
  return (
    <div className="h-full overflow-y-auto [&>div]:border-0 [&>div]:bg-transparent [&>div]:p-0 [&>div>h2]:hidden">
      <RecentPingsTable pingHistory={snapshot.ping_history} compact />
    </div>
  );
}

export function HostsBody({ firewall }: { firewall: StormshieldInfo }) {
  const hosts = firewall.hosts.slice(0, 10);
  const slow = formatHostsSlow(firewall.hosts_slow);
  return (
    <div className="flex h-full min-h-0 flex-col">
      {firewall.hosts_error && (
        <p className="shrink-0 truncate text-[10px] text-warning" title={firewall.hosts_error}>
          {firewall.hosts_error}
        </p>
      )}
      {slow && <p className="shrink-0 truncate font-mono text-[10px] text-fg-muted">{slow}</p>}
      {(firewall.hosts_error || slow) && <div className="mb-1 shrink-0" />}
      <div className="min-h-0 flex-1 overflow-y-auto">
        <table className="w-full text-left">
          <thead className="sticky top-0 bg-surface">
            <tr className="border-b border-edge text-[10px] text-fg-muted">
              <th className="pb-1 pr-2 font-medium">Host</th>
              <th className="pb-1 pr-2 font-medium">Interface</th>
              <th className="pb-1 pr-2 font-medium">In</th>
              <th className="pb-1 font-medium">Out</th>
            </tr>
          </thead>
          <tbody>
            {hosts.length === 0 ? (
              <tr>
                <td colSpan={4} className="py-3 text-xs text-fg-muted">
                  Waiting for host data...
                </td>
              </tr>
            ) : (
              hosts.map((host, i) => (
                <tr key={`${host.addr}-${i}`} className="border-b border-edge/50 last:border-0">
                  <td className="max-w-[140px] py-0.5 pr-2 md:max-w-[260px]">
                    <div className="truncate text-[10px] text-fg md:text-xs">
                      {host.name || host.addr}
                    </div>
                    {host.addr && host.name !== host.addr && (
                      <div className="truncate font-mono text-[10px] text-fg-muted">
                        {host.addr}
                      </div>
                    )}
                  </td>
                  <td className="py-0.5 pr-2 text-[10px] text-fg-muted md:text-xs">
                    {host.interface || "-"}
                  </td>
                  <td className="whitespace-nowrap py-0.5 pr-2 font-mono text-[10px] text-accent md:text-xs">
                    {formatMbps(host.rx_mbps)}
                  </td>
                  <td className="whitespace-nowrap py-0.5 font-mono text-[10px] text-warning md:text-xs">
                    {formatMbps(host.tx_mbps)}
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

export function AlertsBody({ snapshot }: { snapshot: MonitorSnapshot }) {
  const recentAlerts = snapshot.alert_log.slice(0, 5);
  if (recentAlerts.length === 0) {
    return <p className="truncate text-[10px] text-fg-muted md:text-xs">No active alerts</p>;
  }
  return (
    <div className="flex h-full flex-wrap content-start gap-x-3 gap-y-0.5 overflow-y-auto">
      {recentAlerts.map((alert, i) => (
        <span key={`${alert.time}-${i}`} className="truncate text-[10px] md:text-xs">
          <span className="font-mono text-fg-muted">{formatTime(alert.time)}</span>{" "}
          <span className={levelClass(alert.level)}>{alert.msg}</span>
        </span>
      ))}
    </div>
  );
}

/** Title for panels that keep the report's original small uppercase label. */
export function SmallLabel({ children }: { children: ReactNode }) {
  return <span className={SMALL_LABEL}>{children}</span>;
}
