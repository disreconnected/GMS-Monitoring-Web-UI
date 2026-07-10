import { useEffect, useMemo, useRef, useState } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import {
  Area,
  AreaChart,
  CartesianGrid,
  LabelList,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { BandwidthPoint, MonitorSnapshot } from "../types/monitor";
import { StatsPanel } from "./StatsPanel";
import { getChartColors } from "../utils/chartColors";

gsap.registerPlugin(ScrollTrigger);

export type ChartScale = "live" | "1m" | "5m" | "10m" | "15m" | "30m" | "1h";

const SCALE_SECONDS: Record<Exclude<ChartScale, "live">, number> = {
  "1m": 60,
  "5m": 300,
  "10m": 600,
  "15m": 900,
  "30m": 1800,
  "1h": 3600,
};

const SCALE_LABELS: ChartScale[] = ["live", "1m", "5m", "10m", "15m", "30m", "1h"];

type LatencyBucket = {
  t: number;
  label: string;
  msReal: number | null;
  msDisplay: number | null;
  spikeLabel: string;
};

type BandwidthBucket = {
  t: number;
  label: string;
  rx: number;
  tx: number;
};

type BentoChartsProps = {
  snapshot: MonitorSnapshot | null;
  isStale?: boolean;
};

function formatTime(t: number) {
  return new Date(t * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function bucketStart(t: number, scaleSeconds: number) {
  return Math.floor(t / scaleSeconds) * scaleSeconds;
}

function bucketLatency(
  points: MonitorSnapshot["ping_history"],
  scaleSeconds: number,
): LatencyBucket[] {
  const buckets = new Map<number, { ms: number | null; hadTimeout: boolean }>();
  for (const point of points) {
    const start = bucketStart(point.t, scaleSeconds);
    const current = buckets.get(start) ?? { ms: null, hadTimeout: false };
    if (point.ms === null) {
      buckets.set(start, { ms: current.ms, hadTimeout: true });
      continue;
    }
    const nextMs =
      current.ms === null ? point.ms : Math.max(current.ms, point.ms);
    buckets.set(start, { ms: nextMs, hadTimeout: current.hadTimeout });
  }

  return [...buckets.entries()]
    .sort(([a], [b]) => a - b)
    .map(([t, bucket]) => ({
      t,
      label: formatTime(t),
      msReal: bucket.ms,
      msDisplay: bucket.ms === null ? null : Math.min(bucket.ms, 150),
      spikeLabel:
        bucket.hadTimeout && bucket.ms === null
          ? "timeout"
          : bucket.ms !== null && bucket.ms > 150
            ? `${Math.round(bucket.ms)}ms`
            : "",
    }));
}

function liveLatency(points: MonitorSnapshot["ping_history"]): LatencyBucket[] {
  return points.map((point) => ({
    t: point.t,
    label: formatTime(point.t),
    msReal: point.ms,
    msDisplay: point.ms === null ? null : Math.min(point.ms, 150),
    spikeLabel: point.ms !== null && point.ms > 150 ? `${Math.round(point.ms)}ms` : "",
  }));
}

function bucketBandwidth(points: BandwidthPoint[], scaleSeconds: number): BandwidthBucket[] {
  const buckets = new Map<number, { rx: number; tx: number }>();
  for (const point of points) {
    const start = bucketStart(point.t, scaleSeconds);
    const current = buckets.get(start) ?? { rx: 0, tx: 0 };
    buckets.set(start, {
      rx: Math.max(current.rx, point.rx_mbps),
      tx: Math.max(current.tx, point.tx_mbps),
    });
  }

  return [...buckets.entries()]
    .sort(([a], [b]) => a - b)
    .map(([t, values]) => ({
      t,
      label: formatTime(t),
      rx: values.rx,
      tx: values.tx,
    }));
}

function liveBandwidth(points: BandwidthPoint[]): BandwidthBucket[] {
  return points.map((point) => ({
    t: point.t,
    label: formatTime(point.t),
    rx: point.rx_mbps,
    tx: point.tx_mbps,
  }));
}

function LatencyTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ payload: LatencyBucket }>;
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;
  const valueText = point.msReal === null ? "timeout" : `${point.msReal.toFixed(1)} ms`;
  return (
    <div className="rounded-sm border border-edge bg-surface px-3 py-2 text-xs text-fg shadow-lg">
      <p className="font-mono text-fg-muted">{label}</p>
      <p className="mt-1">
        RTT: <span className="font-mono text-accent">{valueText}</span>
      </p>
      {point.msReal !== null && point.msReal > 150 && (
        <p className="mt-1 text-warning">Plotted at 150ms cap</p>
      )}
    </div>
  );
}

function ChartScaleToggle({
  scale,
  onChange,
}: {
  scale: ChartScale;
  onChange: (r: ChartScale) => void;
}) {
  return (
    <div className="inline-flex rounded-full border border-edge bg-bg/60 p-0.5">
      {SCALE_LABELS.map((r) => (
        <button
          key={r}
          type="button"
          onClick={() => onChange(r)}
          className={`rounded-full px-2 py-0.5 text-[10px] font-medium transition md:px-2.5 md:text-xs ${
            scale === r ? "bg-accent text-white" : "text-fg-muted hover:text-fg"
          }`}
        >
          {r === "live" ? "Live" : r}
        </button>
      ))}
    </div>
  );
}

function RTTChart({
  snapshot,
  scale,
}: {
  snapshot: MonitorSnapshot | null;
  scale: ChartScale;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const colors = getChartColors();

  const data = useMemo(() => {
    const raw = snapshot?.ping_history ?? [];
    return scale === "live" ? liveLatency(raw) : bucketLatency(raw, SCALE_SECONDS[scale]);
  }, [snapshot?.ping_history, scale]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) return;

    const ctx = gsap.context(() => {
      gsap.fromTo(
        el,
        { opacity: 0, scale: 0.95 },
        {
          opacity: 1,
          scale: 1,
          duration: 0.8,
          ease: "power2.out",
          scrollTrigger: {
            trigger: el,
            start: "top 85%",
            toggleActions: "play none none reverse",
          },
        },
      );
    }, el);
    return () => ctx.revert();
  }, []);

  return (
    <div ref={ref} className="rounded-sm border border-edge bg-surface/50 p-4 md:p-6">
      <h2 className="mb-4 text-lg font-medium text-fg">Latency</h2>
      <div className="h-56 md:h-64">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 18, right: 14, left: 0, bottom: 0 }}>
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
              width={42}
              domain={[0, 150]}
            />
            <ReferenceArea y1={0} y2={100} fill="#22c55e" fillOpacity={0.06} />
            <ReferenceArea y1={100} y2={150} fill="#f59e0b" fillOpacity={0.08} />
            <Tooltip content={<LatencyTooltip />} />
            <Line
              type="monotone"
              dataKey="msDisplay"
              stroke={colors.accent}
              strokeWidth={2}
              dot={{ r: 1.5, strokeWidth: 0 }}
              connectNulls={false}
              isAnimationActive={false}
            >
              <LabelList
                dataKey="spikeLabel"
                position="top"
                fill={colors.warning}
                fontSize={10}
                fontFamily="var(--font-mono)"
              />
            </Line>
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function BandwidthChart({
  snapshot,
  scale,
}: {
  snapshot: MonitorSnapshot | null;
  scale: ChartScale;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const colors = getChartColors();

  const { data, avgRx, avgTx } = useMemo(() => {
    const raw: BandwidthPoint[] = snapshot?.bandwidth?.history ?? [];
    const chartData =
      scale === "live" ? liveBandwidth(raw) : bucketBandwidth(raw, SCALE_SECONDS[scale]);
    return {
      data: chartData,
      avgRx: snapshot?.bandwidth?.avg_rx_mbps ?? 0,
      avgTx: snapshot?.bandwidth?.avg_tx_mbps ?? 0,
    };
  }, [snapshot?.bandwidth, scale]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) return;

    const ctx = gsap.context(() => {
      gsap.fromTo(
        el,
        { opacity: 0, scale: 0.95 },
        {
          opacity: 1,
          scale: 1,
          duration: 0.8,
          ease: "power2.out",
          scrollTrigger: {
            trigger: el,
            start: "top 85%",
            toggleActions: "play none none reverse",
          },
        },
      );
    }, el);
    return () => ctx.revert();
  }, []);

  return (
    <div ref={ref} className="rounded-sm border border-edge bg-surface/50 p-4 md:p-6">
      <h2 className="mb-4 text-lg font-medium text-fg">Throughput</h2>
      <div className="h-56 md:h-[calc(100%-2.5rem)] min-h-56">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data}>
            <CartesianGrid stroke={colors.grid} strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="label"
              tick={{ fill: colors.tick, fontSize: 9 }}
              interval="preserveStartEnd"
              minTickGap={40}
            />
            <YAxis stroke={colors.tick} tick={{ fill: colors.tick, fontSize: 11 }} width={42} />
            <Tooltip
              contentStyle={{
                background: colors.surface,
                border: `1px solid ${colors.grid}`,
                borderRadius: 4,
                color: colors.fg,
              }}
            />
            <ReferenceLine
              y={avgRx}
              stroke={colors.accent}
              strokeDasharray="4 4"
              strokeOpacity={0.6}
              label={{
                value: "RX avg",
                position: "insideTopRight",
                fill: colors.accent,
                fontSize: 10,
              }}
            />
            <ReferenceLine
              y={avgTx}
              stroke={colors.warning}
              strokeDasharray="4 4"
              strokeOpacity={0.6}
              label={{
                value: "TX avg",
                position: "insideBottomRight",
                fill: colors.warning,
                fontSize: 10,
              }}
            />
            <Area
              type="monotone"
              dataKey="rx"
              stroke={colors.accent}
              fill={colors.accent}
              fillOpacity={0.15}
              isAnimationActive={false}
            />
            <Area
              type="monotone"
              dataKey="tx"
              stroke={colors.warning}
              fill={colors.warning}
              fillOpacity={0.12}
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      {snapshot?.bandwidth.error && (
        <p className="mt-2 text-xs text-warning">{snapshot.bandwidth.error}</p>
      )}
      <div className="mt-2 flex gap-4 text-xs text-fg-muted">
        <span>
          RX avg: <span className="font-mono text-accent">{avgRx.toFixed(2)} Mbps</span>
        </span>
        <span>
          TX avg: <span className="font-mono text-warning">{avgTx.toFixed(2)} Mbps</span>
        </span>
      </div>
    </div>
  );
}

export function BentoCharts({ snapshot }: BentoChartsProps) {
  const [scale, setScale] = useState<ChartScale>("live");

  return (
    <section className="px-4 py-24 md:px-8">
      <div className="mx-auto mb-4 flex max-w-7xl flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-fg-muted">Time scale</p>
        <ChartScaleToggle scale={scale} onChange={setScale} />
      </div>
      <div className="mx-auto grid max-w-7xl grid-flow-dense grid-cols-1 gap-4 md:grid-cols-3 md:grid-rows-2">
        <div className="md:col-span-2 md:row-span-1">
          <RTTChart snapshot={snapshot} scale={scale} />
        </div>
        <div className="md:col-span-1 md:row-span-2">
          <BandwidthChart snapshot={snapshot} scale={scale} />
        </div>
        <div className="md:col-span-1">
          <StatsPanel title="Window" stats={snapshot?.window_stats ?? null} />
        </div>
        <div className="md:col-span-1">
          <StatsPanel title="Session" stats={snapshot?.session_stats ?? null} />
        </div>
      </div>
    </section>
  );
}
