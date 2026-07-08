export function getChartColors() {
  const root = getComputedStyle(document.documentElement);
  return {
    grid: root.getPropertyValue("--color-edge").trim() || "#3f3f46",
    tick: root.getPropertyValue("--color-fg-muted").trim() || "#a1a1aa",
    accent: root.getPropertyValue("--color-accent").trim() || "#38bdf8",
    warning: root.getPropertyValue("--color-warning").trim() || "#fbbf24",
    surface: root.getPropertyValue("--color-surface").trim() || "#18181b",
    fg: root.getPropertyValue("--color-fg").trim() || "#fafafa",
  };
}
