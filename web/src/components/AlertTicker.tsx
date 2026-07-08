import { useEffect, useRef } from "react";
import gsap from "gsap";
import type { Alert } from "../types/monitor";

type AlertTickerProps = {
  alerts: Alert[];
};

export function AlertTicker({ alerts }: AlertTickerProps) {
  const trackRef = useRef<HTMLDivElement>(null);
  const tweenRef = useRef<gsap.core.Tween | null>(null);

  const items =
    alerts.length > 0
      ? alerts.map((a) => a.msg)
      : ["No active alerts. Network looks stable."];

  const text = items.join("   |   ");

  useEffect(() => {
    const track = trackRef.current;
    if (!track) return;

    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) return;

    tweenRef.current?.kill();
    gsap.set(track, { x: 0 });
    const distance = track.scrollWidth / 2;
    tweenRef.current = gsap.to(track, {
      x: -distance,
      duration: Math.max(18, distance / 40),
      ease: "none",
      repeat: -1,
    });

    return () => {
      tweenRef.current?.kill();
    };
  }, [text]);

  return (
    <section className="border-y border-edge bg-surface/80 py-3">
      <div className="overflow-hidden">
        <div ref={trackRef} className="flex w-max whitespace-nowrap px-4">
          <span className="pr-16 font-mono text-sm text-warning">{text}</span>
          <span className="pr-16 font-mono text-sm text-warning" aria-hidden="true">
            {text}
          </span>
        </div>
      </div>
    </section>
  );
}
