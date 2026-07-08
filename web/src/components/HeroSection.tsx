import { AnimatedNumber } from "./AnimatedNumber";
import type { MonitorSnapshot } from "../types/monitor";

type HeroSectionProps = {
  snapshot: MonitorSnapshot | null;
};

export function HeroSection({ snapshot }: HeroSectionProps) {
  const ping = snapshot?.current_ping ?? null;
  const quality = snapshot?.quality ?? "Unknown";
  const host = snapshot?.host ?? "waiting for target";
  const paused = snapshot?.paused ?? false;

  return (
    <section className="relative flex min-h-[100dvh] items-center justify-center overflow-hidden px-4 pb-24 pt-20">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_50%_0%,color-mix(in_srgb,var(--color-surface)_95%,transparent),var(--color-bg)_60%)]" />
      <div className="pointer-events-none absolute inset-0 grid-texture opacity-40" />

      <div className="relative z-10 mx-auto flex w-full max-w-5xl flex-col items-center text-center">
        <p className="mb-4 font-mono text-xs uppercase tracking-[0.18em] text-fg-muted">
          Live latency to
        </p>
        <p className="mb-8 font-mono text-sm text-fg-muted">{host}</p>

        <div className="flex items-end justify-center gap-3">
          <AnimatedNumber
            value={ping}
            decimals={ping !== null && ping < 10 ? 1 : 0}
            className="font-mono text-[clamp(5rem,10vw,9rem)] font-medium leading-none tracking-tighter text-fg"
          />
          <span className="mb-4 font-mono text-2xl text-fg-muted md:text-3xl">ms</span>
        </div>

        <p className="mt-6 text-lg text-fg md:text-xl">{quality}</p>
        <p className="mt-2 text-sm text-fg-muted">
          {paused ? "Monitoring paused" : "Updating every second"}
        </p>
      </div>
    </section>
  );
}
