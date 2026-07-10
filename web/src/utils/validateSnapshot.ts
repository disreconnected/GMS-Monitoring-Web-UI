import type { MonitorSnapshot } from "../types/monitor";

export function isMonitorSnapshot(value: unknown): value is MonitorSnapshot {
  if (!value || typeof value !== "object") return false;
  const snapshot = value as MonitorSnapshot;
  return (
    typeof snapshot.host === "string" &&
    typeof snapshot.timestamp === "number" &&
    typeof snapshot.quality === "string" &&
    typeof snapshot.quality_code === "string" &&
    typeof snapshot.paused === "boolean" &&
    Array.isArray(snapshot.ping_history) &&
    snapshot.bandwidth !== undefined &&
    Array.isArray(snapshot.bandwidth.history) &&
    snapshot.traceroute !== undefined &&
    Array.isArray(snapshot.traceroute.hops) &&
    snapshot.session !== undefined
  );
}
