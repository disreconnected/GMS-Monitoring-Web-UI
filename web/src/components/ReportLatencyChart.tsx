import { useMemo } from "react";
import {
  CartesianGrid,
  LabelList,
  Line,
  LineChart,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { PingPoint } from "../types/monitor";
import { getChartColors } from "../utils/chartColors";
import { LatencyTooltip, bucketLatency } from "./BentoCharts";

type ReportLatencyChartProps = {
  pingHistory: PingPoint[];
};

// The "1h" scale in BentoCharts buckets at one-hour *width*, which would fold
// the whole ~3600-sample history into one or two points. The report shows the
// last hour, so bucket at 10 s instead (max RTT per bucket, <= 360 points).
const BUCKET_SECONDS = 10;

const Y_TICKS = [0, 50, 100, 150];

/** Right-hand caption for the panel header the chart is shown in. */
export function ReportLatencyCaption() {
  return (
    <span className="text-[9px] text-fg-muted md:text-[10px]">
      max per {BUCKET_SECONDS} s · capped at 150 ms
    </span>
  );
}

/** The plot only; the surrounding panel supplies the frame and the "Latency (1h)" title. */
export function ReportLatencyChart({ pingHistory }: ReportLatencyChartProps) {
  const colors = getChartColors();
  const data = useMemo(() => bucketLatency(pingHistory, BUCKET_SECONDS), [pingHistory]);

  return (
    <div className="relative h-full min-h-0">
      <div className="absolute inset-0">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 12, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid stroke={colors.grid} strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="label"
              tick={{ fill: colors.tick, fontSize: 9 }}
              interval="preserveStartEnd"
              minTickGap={80}
            />
            <YAxis
              stroke={colors.tick}
              tick={{ fill: colors.tick, fontSize: 9 }}
              width={30}
              domain={[0, 150]}
              ticks={Y_TICKS}
            />
            <ReferenceArea y1={0} y2={100} fill="#22c55e" fillOpacity={0.06} />
            <ReferenceArea y1={100} y2={150} fill="#f59e0b" fillOpacity={0.08} />
            <Tooltip content={<LatencyTooltip />} />
            <Line
              type="monotone"
              dataKey="msDisplay"
              stroke={colors.accent}
              strokeWidth={1.5}
              dot={{ r: 1, strokeWidth: 0 }}
              connectNulls={false}
              isAnimationActive={false}
            >
              <LabelList
                dataKey="spikeLabel"
                position="top"
                fill={colors.warning}
                fontSize={9}
                fontFamily="var(--font-mono)"
              />
            </Line>
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
