import { useMemo } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { StormshieldInterface } from "../types/monitor";
import { getChartColors } from "../utils/chartColors";
import { formatMbps } from "../utils/formatBandwidth";

type ReportInterfaceChartProps = {
  iface: StormshieldInterface;
};

type EdgeTickProps = {
  x?: number;
  y?: number;
  index?: number;
  payload?: { value: number };
};

function formatClock(t: number, withSeconds = false) {
  return new Date(t * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    ...(withSeconds ? { second: "2-digit" } : {}),
  });
}

function formatTick(v: number): string {
  return String(Math.round(v * 10) / 10);
}

/** Title line for the panel header the chart is shown in: name, side, current rates. */
export function ReportInterfaceHeading({ iface }: { iface: StormshieldInterface }) {
  return (
    <span className="text-[10px] md:text-xs">
      <span className="font-medium text-fg">{iface.name}</span>
      <span className="text-fg-muted"> · </span>
      <span className="text-[9px] text-fg-muted md:text-[10px]">
        {iface.protected === 1 ? "LAN" : "WAN"}
      </span>
      <span className="text-fg-muted"> · </span>
      <span className="font-mono">
        <span className="text-fg-muted">In </span>
        <span className="text-accent">{formatMbps(iface.rx_mbps)}</span>
        <span className="text-fg-muted"> / Out </span>
        <span className="text-warning">{formatMbps(iface.tx_mbps)}</span>
      </span>
    </span>
  );
}

/** The plot only; the surrounding panel supplies the frame and the heading. */
export function ReportInterfaceChart({ iface }: ReportInterfaceChartProps) {
  const colors = getChartColors();
  // The history array is a new object every snapshot; key on what actually
  // changes (interface, length, newest timestamp) so recharts keeps a stable
  // data reference between polls that add no new point.
  const lastT = iface.history[iface.history.length - 1]?.t;
  const data = useMemo(
    () => iface.history,
    [iface.name, iface.history.length, lastT],
  );
  // Only the first and last timestamps are labelled, like the "1h ago ... Now"
  // axis on the firewall's own graph.
  const ticks = data.length >= 2 ? [data[0].t, data[data.length - 1].t] : [];

  // Anchor the first label to the left edge and the last to the right edge so
  // neither spills out of the plot area. The XAxis uses interval={0} because
  // recharts otherwise drops a centred edge tick as "overflowing" the axis.
  const renderTick = ({ x = 0, y = 0, index = 0, payload }: EdgeTickProps) => (
    <text
      x={x}
      y={y}
      dy="0.71em"
      textAnchor={index === 0 ? "start" : "end"}
      fill={colors.tick}
      fontSize={9}
    >
      {payload ? formatClock(payload.value) : ""}
    </text>
  );

  return (
    <div className="relative h-full min-h-0">
      {data.length < 2 ? (
        <div className="flex h-full items-center justify-center text-[10px] text-fg-muted md:text-xs">
          Waiting for history...
        </div>
      ) : (
        <div className="absolute inset-0">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke={colors.grid} strokeDasharray="3 3" vertical={false} />
              <XAxis
                dataKey="t"
                type="number"
                domain={["dataMin", "dataMax"]}
                ticks={ticks}
                interval={0}
                tick={renderTick}
                tickLine={false}
                stroke={colors.grid}
              />
              <YAxis
                stroke={colors.grid}
                tick={{ fill: colors.tick, fontSize: 9 }}
                width={40}
                domain={[0, "auto"]}
                tickCount={4}
                tickSize={3}
                tickFormatter={formatTick}
                label={{
                  value: "Mbit/s",
                  angle: -90,
                  position: "insideLeft",
                  fill: colors.tick,
                  fontSize: 9,
                }}
              />
              <Tooltip
                contentStyle={{
                  background: colors.surface,
                  border: `1px solid ${colors.grid}`,
                  borderRadius: 4,
                  color: colors.fg,
                  fontSize: 11,
                }}
                labelFormatter={(t: number) => formatClock(t, true)}
                formatter={(value: number, name: string) => [
                  formatMbps(value),
                  name === "rx" ? "Inbound" : "Outbound",
                ]}
              />
              <Area
                type="monotone"
                dataKey="rx_mbps"
                name="rx"
                stroke={colors.accent}
                strokeWidth={1.5}
                fill={colors.accent}
                fillOpacity={0.15}
                dot={false}
                isAnimationActive={false}
              />
              <Area
                type="monotone"
                dataKey="tx_mbps"
                name="tx"
                stroke={colors.warning}
                strokeWidth={1.5}
                fill={colors.warning}
                fillOpacity={0.12}
                dot={false}
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
