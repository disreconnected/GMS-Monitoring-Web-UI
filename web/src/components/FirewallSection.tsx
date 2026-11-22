import { useEffect, useMemo, useState, type KeyboardEvent } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type {
  SnsCandidate,
  SnsState,
  StormshieldBandwidthPoint,
  StormshieldHost,
  StormshieldInfo,
  StormshieldInterface,
} from "../types/monitor";
import { getChartColors } from "../utils/chartColors";
import { formatBytes, formatMbps } from "../utils/formatBandwidth";
import { formatHostsSlow } from "../utils/formatTime";

type FirewallSectionProps = {
  stormshield: StormshieldInfo | null;
  sns: SnsState;
  controlsEnabled: boolean;
  onConnect: (host: string, password?: string, label?: string) => void;
  onDisconnect: () => void;
  onDetect: () => void;
  onForget: (host: string) => void;
};

const NO_INTERFACES: StormshieldInterface[] = [];

function formatTime(t: number) {
  return new Date(t * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatLink(mbps: number): string {
  if (mbps >= 1000) return `${mbps / 1000} Gbit/s link`;
  return `${mbps} Mbit/s link`;
}

function toChartData(history: StormshieldBandwidthPoint[]) {
  return history.map((point) => ({
    t: point.t,
    label: formatTime(point.t),
    rx: point.rx_mbps,
    tx: point.tx_mbps,
  }));
}

function InterfaceChart({ iface }: { iface: StormshieldInterface }) {
  const colors = getChartColors();
  // The history array is a new object every snapshot; key on what actually
  // changes (interface, length, newest timestamp) to avoid re-formatting ~720
  // labels each second. An empty history yields an empty chart.
  const lastT = iface.history[iface.history.length - 1]?.t;
  const data = useMemo(
    () => toChartData(iface.history),
    [iface.name, iface.history.length, lastT],
  );

  return (
    <div className="rounded-sm border border-edge bg-surface/50 p-4 md:p-6">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h3 className="text-lg font-medium text-fg">
            {iface.name}
            {iface.real_name && iface.real_name !== iface.name ? (
              <span className="ml-2 text-sm font-normal text-fg-muted">
                ({iface.real_name})
              </span>
            ) : null}
          </h3>
          <p className="mt-1 font-mono text-xs text-fg-muted">
            {[
              iface.addr || "no address",
              iface.state === 1 ? "up" : "down",
              iface.protected === 1 ? "LAN" : "WAN",
              ...(iface.link_mbps > 0 ? [formatLink(iface.link_mbps)] : []),
              `TCP ${iface.tcp_conn}`,
              `UDP ${iface.udp_conn}`,
            ].join(" · ")}
          </p>
        </div>
        <div className="flex gap-4 text-xs text-fg-muted">
          <span>
            In{" "}
            <span className="font-mono text-accent">{formatMbps(iface.rx_mbps)}</span>
          </span>
          <span>
            Out{" "}
            <span className="font-mono text-warning">{formatMbps(iface.tx_mbps)}</span>
          </span>
        </div>
      </div>
      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data}>
            <CartesianGrid stroke={colors.grid} strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="label"
              tick={{ fill: colors.tick, fontSize: 9 }}
              interval="preserveStartEnd"
              minTickGap={40}
            />
            <YAxis
              stroke={colors.tick}
              tick={{ fill: colors.tick, fontSize: 11 }}
              width={48}
              unit=""
              tickFormatter={(v: number) => `${v}`}
              label={{
                value: "Mbit/s",
                angle: -90,
                position: "insideLeft",
                fill: colors.tick,
                fontSize: 10,
              }}
            />
            <Tooltip
              contentStyle={{
                background: colors.surface,
                border: `1px solid ${colors.grid}`,
                borderRadius: 4,
                color: colors.fg,
              }}
              formatter={(value: number, name: string) => [
                formatMbps(value),
                name === "rx" ? "Inbound" : "Outbound",
              ]}
            />
            <Area
              type="monotone"
              dataKey="rx"
              name="rx"
              stroke={colors.accent}
              fill={colors.accent}
              fillOpacity={0.15}
              isAnimationActive={false}
            />
            <Area
              type="monotone"
              dataKey="tx"
              name="tx"
              stroke={colors.warning}
              fill={colors.warning}
              fillOpacity={0.12}
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-2 flex gap-4 text-xs text-fg-muted">
        <span>
          In avg:{" "}
          <span className="font-mono text-accent">{formatMbps(iface.avg_rx_mbps)}</span>
        </span>
        <span>
          Out avg:{" "}
          <span className="font-mono text-warning">{formatMbps(iface.avg_tx_mbps)}</span>
        </span>
      </div>
    </div>
  );
}

function HostsTable({
  hosts,
  interfaces,
  error,
  updatedAt,
  slow,
  emptyText = "Waiting for host data from the firewall...",
}: {
  hosts: StormshieldHost[];
  interfaces: string[];
  error: string | null;
  updatedAt: number | null;
  slow?: string | null;
  emptyText?: string;
}) {
  // Older saved snapshots lack these fields; treat undefined like null.
  const updatedAgeSeconds =
    typeof updatedAt === "number" ? Date.now() / 1000 - updatedAt : null;

  return (
    <div className="rounded-sm border border-edge bg-surface/50 p-4 md:p-6">
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-lg font-medium text-fg">Top hosts</h3>
        <div className="flex flex-wrap items-baseline gap-3">
          {error ? <span className="text-xs text-warning">{error}</span> : null}
          {slow ? <span className="font-mono text-xs text-fg-muted">{slow}</span> : null}
          {updatedAgeSeconds !== null ? (
            <span className="font-mono text-xs text-fg-muted">
              hosts updated {Math.max(0, Math.round(updatedAgeSeconds))}s ago
            </span>
          ) : null}
          {interfaces.length > 0 ? (
            <span className="font-mono text-xs text-fg-muted">on {interfaces.join(", ")}</span>
          ) : null}
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-edge text-xs text-fg-muted">
              <th className="pb-2 pr-3 font-medium">Host</th>
              <th className="pb-2 pr-3 font-medium">Interface</th>
              <th className="pb-2 pr-3 font-medium">Bytes in</th>
              <th className="pb-2 pr-3 font-medium">Bytes out</th>
              <th className="pb-2 pr-3 font-medium">Incoming</th>
              <th className="pb-2 font-medium">Outgoing</th>
            </tr>
          </thead>
          <tbody>
            {hosts.length === 0 ? (
              <tr>
                <td colSpan={6} className="py-4 text-sm text-fg-muted">
                  {emptyText}
                </td>
              </tr>
            ) : (
              hosts.map((host, index) => (
                <tr
                  key={`${host.addr}-${index}`}
                  className={`border-b border-edge/50 last:border-0 ${
                    index === 0 ? "bg-accent/5" : ""
                  }`}
                >
                  <td className="py-1.5 pr-3">
                    <div className="font-mono text-xs text-fg">{host.name}</div>
                    {host.name !== host.addr ? (
                      <div className="font-mono text-[10px] text-fg-muted">{host.addr}</div>
                    ) : null}
                    {host.mac ? (
                      <div className="font-mono text-[10px] text-fg-muted">{host.mac}</div>
                    ) : null}
                  </td>
                  <td className="py-1.5 pr-3 text-xs text-fg-muted">{host.interface || "—"}</td>
                  <td className="py-1.5 pr-3 font-mono text-xs text-fg-muted">
                    {formatBytes(host.bytes_in)}
                  </td>
                  <td className="py-1.5 pr-3 font-mono text-xs text-fg-muted">
                    {formatBytes(host.bytes_out)}
                  </td>
                  <td
                    className={`py-1.5 pr-3 font-mono text-xs ${
                      index === 0 ? "text-accent" : "text-fg"
                    }`}
                  >
                    {formatMbps(host.rx_mbps)}
                  </td>
                  <td className="py-1.5 font-mono text-xs text-fg">
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

function formatPollAge(ageSeconds: number): string {
  return `last poll ${Math.max(0, Math.round(ageSeconds))}s ago`;
}

function formatSeen(lastSeen: number | null): string | null {
  if (lastSeen === null) return null;
  const age = Math.max(0, Date.now() / 1000 - lastSeen);
  if (age < 60) return "seen just now";
  if (age < 3600) return `seen ${Math.floor(age / 60)}m ago`;
  if (age < 86400) return `seen ${Math.floor(age / 3600)}h ago`;
  return `seen ${Math.floor(age / 86400)}d ago`;
}

const INPUT_CLASS =
  "rounded-sm border border-edge bg-surface px-3 py-1.5 font-mono text-sm text-fg outline-none focus:border-accent disabled:cursor-not-allowed disabled:opacity-50";
const PRIMARY_BUTTON_CLASS =
  "rounded-full bg-accent px-4 py-1.5 text-sm font-medium text-white transition active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50";
const SECONDARY_BUTTON_CLASS =
  "rounded-full border border-edge bg-surface px-4 py-1.5 text-sm text-fg transition hover:border-fg-muted active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50";

function CandidateChip({
  candidate,
  onPick,
}: {
  candidate: SnsCandidate;
  onPick: (host: string) => void;
}) {
  const latency =
    candidate.latency_ms !== null ? `${Math.round(candidate.latency_ms)} ms` : undefined;
  if (candidate.stormshield) {
    return (
      <button
        type="button"
        title={latency ? `Use ${candidate.host} (${latency})` : `Use ${candidate.host}`}
        onClick={() => onPick(candidate.host)}
        className="inline-flex items-center gap-2 rounded-full border border-accent/40 bg-accent/10 px-3 py-1 font-mono text-xs text-fg transition hover:bg-accent/20"
      >
        {candidate.host}
        <span className="rounded-full bg-accent/15 px-2 py-0.5 font-sans text-[10px] font-medium text-accent">
          Stormshield
        </span>
      </button>
    );
  }
  return (
    <span
      title={latency}
      className="inline-flex items-center gap-2 rounded-full border border-edge px-3 py-1 font-mono text-xs text-fg-muted"
    >
      {candidate.host}
      <span
        className={`font-sans text-[10px] ${
          candidate.reachable ? "text-fg-muted" : "text-danger"
        }`}
      >
        {candidate.reachable ? "reachable" : "unreachable"}
      </span>
    </span>
  );
}

function SnsBar({
  sns,
  controlsEnabled,
  onConnect,
  onDisconnect,
  onDetect,
  onForget,
}: Omit<FirewallSectionProps, "stormshield">) {
  const [selected, setSelected] = useState("");
  const [newHost, setNewHost] = useState("");
  const [label, setLabel] = useState("");
  const [password, setPassword] = useState("");

  const savedHosts = sns.saved_hosts;
  useEffect(() => {
    if (!savedHosts.some((item) => item.host === selected)) {
      setSelected(
        savedHosts.find((item) => item.host === sns.active_host)?.host ??
          savedHosts[0]?.host ??
          "",
      );
    }
  }, [savedHosts, sns.active_host, selected]);

  // A successful connect switches the active host: drop what was typed for it.
  useEffect(() => {
    setNewHost("");
    setLabel("");
  }, [sns.active_host]);

  // The server keeps the password in memory once accepted; stop holding it here.
  useEffect(() => {
    if (sns.password_set) setPassword("");
  }, [sns.password_set]);

  const typedHost = newHost.trim();
  const targetHost = typedHost || selected;
  const needsPassword = !sns.password_set;
  const disabled = sns.busy || !controlsEnabled;
  const canConnect = !disabled && targetHost !== "" && (!needsPassword || password !== "");
  const seen = formatSeen(savedHosts.find((item) => item.host === selected)?.last_seen ?? null);

  const connect = () => {
    if (!canConnect) return;
    onConnect(
      targetHost,
      needsPassword ? password : undefined,
      label.trim() || undefined,
    );
  };
  const connectOnEnter = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") connect();
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label="Saved firewalls"
          className={`${INPUT_CLASS} max-w-[16rem]`}
          value={selected}
          disabled={disabled || savedHosts.length === 0}
          onChange={(event) => {
            setSelected(event.target.value);
            setNewHost("");
            setLabel("");
          }}
        >
          {savedHosts.length === 0 ? (
            <option value="">No saved firewalls</option>
          ) : (
            savedHosts.map((item) => (
              <option key={item.host} value={item.host}>
                {item.label || item.host}
              </option>
            ))
          )}
        </select>
        {seen ? <span className="text-xs text-fg-muted">{seen}</span> : null}
        <button
          type="button"
          aria-label="Forget this saved firewall"
          title="Forget this saved firewall"
          disabled={disabled || selected === ""}
          onClick={() => onForget(selected)}
          className="rounded-full border border-edge px-2.5 py-1 text-sm leading-none text-fg-muted transition hover:border-danger hover:text-danger disabled:cursor-not-allowed disabled:opacity-50"
        >
          ×
        </button>
        <input
          type="text"
          aria-label="New firewall address"
          placeholder="or new address"
          autoComplete="off"
          spellCheck={false}
          maxLength={253}
          className={`${INPUT_CLASS} w-40`}
          value={newHost}
          disabled={disabled}
          onChange={(event) => setNewHost(event.target.value)}
          onKeyDown={connectOnEnter}
        />
        <input
          type="text"
          aria-label="Label (optional)"
          placeholder="label (optional)"
          autoComplete="off"
          maxLength={64}
          className={`${INPUT_CLASS} w-36`}
          value={label}
          disabled={disabled}
          onChange={(event) => setLabel(event.target.value)}
          onKeyDown={connectOnEnter}
        />
        {needsPassword ? (
          <input
            type="password"
            aria-label="Firewall password"
            placeholder="password"
            autoComplete="off"
            maxLength={256}
            className={`${INPUT_CLASS} w-36`}
            value={password}
            disabled={disabled}
            onChange={(event) => setPassword(event.target.value)}
            onKeyDown={connectOnEnter}
          />
        ) : null}
        <button
          type="button"
          onClick={connect}
          disabled={!canConnect}
          className={PRIMARY_BUTTON_CLASS}
        >
          Connect
        </button>
        <button
          type="button"
          onClick={onDetect}
          disabled={disabled}
          className={SECONDARY_BUTTON_CLASS}
        >
          Detect
        </button>
        {sns.active_host ? (
          <button
            type="button"
            onClick={onDisconnect}
            disabled={disabled}
            className={SECONDARY_BUTTON_CLASS}
          >
            Disconnect
          </button>
        ) : null}
      </div>
      {needsPassword ? (
        <p className="text-xs text-fg-muted">
          The password is kept in memory for this run only.
        </p>
      ) : null}
      {sns.message ? (
        <p role="status" className={`text-sm ${sns.busy ? "text-fg-muted" : "text-warning"}`}>
          {sns.message}
        </p>
      ) : null}
      {sns.candidates.length > 0 ? (
        <div className="flex flex-wrap items-center gap-2">
          {sns.candidates.map((candidate) => (
            <CandidateChip
              key={candidate.host}
              candidate={candidate}
              onPick={(host) => {
                setNewHost(host);
                setLabel("");
              }}
            />
          ))}
          {sns.probed_at !== null ? (
            <span className="text-xs text-fg-muted">
              scanned {new Date(sns.probed_at * 1000).toLocaleTimeString()}
            </span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export function FirewallSection({
  stormshield,
  sns,
  controlsEnabled,
  onConnect,
  onDisconnect,
  onDetect,
  onForget,
}: FirewallSectionProps) {
  const interfaces = stormshield?.interfaces ?? NO_INTERFACES;
  const pluggedInterfaces = useMemo(
    () => interfaces.filter((iface) => iface.plugged === 1),
    [interfaces],
  );
  const selectable = pluggedInterfaces.length > 0 ? pluggedInterfaces : interfaces;
  const [selectedName, setSelectedName] = useState<string>("");

  useEffect(() => {
    if (selectable.length === 0) {
      setSelectedName("");
      return;
    }
    if (!selectable.some((iface) => iface.name === selectedName)) {
      const busiest = selectable.reduce((best, iface) =>
        iface.rx_mbps + iface.tx_mbps > best.rx_mbps + best.tx_mbps ? iface : best,
      );
      setSelectedName(busiest.name);
    }
  }, [selectable, selectedName]);

  const selected = selectable.find((iface) => iface.name === selectedName) ?? null;

  const pollAgeSeconds =
    stormshield && stormshield.last_poll !== null
      ? Date.now() / 1000 - stormshield.last_poll
      : null;

  const titleBits = stormshield
    ? [stormshield.model, stormshield.version].filter(Boolean).join(" · ")
    : "";
  const subtitle = stormshield
    ? stormshield.host
      ? `${stormshield.host}${titleBits ? ` · ${titleBits}` : ""}`
      : titleBits || "Stormshield SNS"
    : (sns.active_host ?? "No firewall selected");

  return (
    <section className="px-4 py-16 md:px-8">
      <div className="mx-auto mb-6 flex max-w-7xl flex-wrap items-end justify-between gap-4">
        <div>
          <div className="mb-2 flex items-center gap-3">
            <h2 className="text-2xl font-medium text-fg">Firewall</h2>
            <span
              className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${
                stormshield?.connected
                  ? "bg-accent/15 text-accent"
                  : stormshield
                    ? "bg-warning/15 text-warning"
                    : "bg-edge/40 text-fg-muted"
              }`}
            >
              {stormshield
                ? stormshield.connected
                  ? "Connected"
                  : "Disconnected"
                : sns.active_host
                  ? "Connecting"
                  : "Not connected"}
            </span>
            {pollAgeSeconds !== null ? (
              <span
                className={`font-mono text-xs ${
                  pollAgeSeconds > 30 ? "text-warning" : "text-fg-muted"
                }`}
              >
                {formatPollAge(pollAgeSeconds)}
              </span>
            ) : null}
          </div>
          <p className="text-sm text-fg-muted">{subtitle}</p>
          {stormshield?.error ? (
            <p className="mt-2 text-sm text-warning">{stormshield.error}</p>
          ) : null}
        </div>
        {selectable.length > 1 ? (
          <label className="flex items-center gap-2 text-sm text-fg-muted">
            Interface
            <select
              className="rounded-sm border border-edge bg-surface px-3 py-1.5 font-mono text-sm text-fg"
              value={selectedName}
              onChange={(event) => setSelectedName(event.target.value)}
            >
              {selectable.map((iface) => (
                <option key={iface.name} value={iface.name}>
                  {iface.name}
                </option>
              ))}
            </select>
          </label>
        ) : null}
      </div>

      <div className="mx-auto mb-6 max-w-7xl">
        <SnsBar
          sns={sns}
          controlsEnabled={controlsEnabled}
          onConnect={onConnect}
          onDisconnect={onDisconnect}
          onDetect={onDetect}
          onForget={onForget}
        />
      </div>

      <div className="mx-auto grid max-w-7xl grid-cols-1 gap-4">
        {selected ? (
          <InterfaceChart iface={selected} />
        ) : (
          <div className="rounded-sm border border-edge bg-surface/50 p-6 text-sm text-fg-muted">
            {stormshield
              ? "No interface data yet. Waiting for the SNS poller..."
              : "No interface data yet. Pick a firewall above and press Connect."}
          </div>
        )}
        <HostsTable
          hosts={stormshield?.hosts ?? []}
          interfaces={stormshield?.host_interfaces ?? []}
          error={stormshield?.hosts_error ?? null}
          updatedAt={stormshield?.hosts_updated_at ?? null}
          slow={formatHostsSlow(stormshield?.hosts_slow)}
          emptyText={
            stormshield
              ? undefined
              : "No host data yet. Pick a firewall above and press Connect."
          }
        />
      </div>
    </section>
  );
}
