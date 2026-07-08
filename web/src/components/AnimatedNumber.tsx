import { useEffect, useRef } from "react";
import { animate, useMotionValue, useReducedMotion } from "motion/react";

type AnimatedNumberProps = {
  value: number | null;
  decimals?: number;
  suffix?: string;
  className?: string;
};

export function AnimatedNumber({
  value,
  decimals = 1,
  suffix = "",
  className = "",
}: AnimatedNumberProps) {
  const reduce = useReducedMotion();
  const motionValue = useMotionValue(0);
  const displayRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (value === null) {
      if (displayRef.current) displayRef.current.textContent = "-";
      return;
    }
    if (reduce) {
      motionValue.set(value);
      if (displayRef.current) {
        displayRef.current.textContent = `${value.toFixed(decimals)}${suffix}`;
      }
      return;
    }
    const controls = animate(motionValue, value, {
      type: "spring",
      stiffness: 100,
      damping: 20,
      onUpdate: (v) => {
        if (displayRef.current) {
          displayRef.current.textContent = `${v.toFixed(decimals)}${suffix}`;
        }
      },
    });
    return () => controls.stop();
  }, [value, decimals, suffix, reduce, motionValue]);

  return <span ref={displayRef} className={className}>-</span>;
}
