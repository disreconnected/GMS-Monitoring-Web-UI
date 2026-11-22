import type { MonitorSnapshot, SnsState, StormshieldInfo } from "../types/monitor";

function isStormshieldInfo(value: unknown): value is StormshieldInfo {
  if (!value || typeof value !== "object") return false;
  const info = value as StormshieldInfo;
  return (
    typeof info.connected === "boolean" &&
    Array.isArray(info.interfaces) &&
    info.interfaces.every(
      (iface) => !!iface && typeof iface === "object" && Array.isArray(iface.history),
    ) &&
    Array.isArray(info.hosts) &&
    Array.isArray(info.host_interfaces)
  );
}

function isSnsState(value: unknown): value is SnsState {
  if (!value || typeof value !== "object") return false;
  const sns = value as SnsState;
  const isRecord = (item: unknown): item is Record<string, unknown> =>
    !!item && typeof item === "object";
  return (
    (sns.active_host === null || typeof sns.active_host === "string") &&
    typeof sns.password_set === "boolean" &&
    typeof sns.busy === "boolean" &&
    (sns.message === null || typeof sns.message === "string") &&
    (sns.probed_at === null || typeof sns.probed_at === "number") &&
    Array.isArray(sns.saved_hosts) &&
    sns.saved_hosts.every(
      (item) =>
        isRecord(item) &&
        typeof item.host === "string" &&
        typeof item.label === "string" &&
        (item.last_seen === null || typeof item.last_seen === "number"),
    ) &&
    Array.isArray(sns.candidates) &&
    sns.candidates.every(
      (item) =>
        isRecord(item) &&
        typeof item.host === "string" &&
        typeof item.reachable === "boolean" &&
        typeof item.stormshield === "boolean",
    )
  );
}

export function isMonitorSnapshot(value: unknown): value is MonitorSnapshot {
  if (!value || typeof value !== "object") return false;
  const snapshot = value as MonitorSnapshot;
  const baseOk =
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
    snapshot.session !== undefined;
  if (!baseOk) return false;
  // The firewall block is optional: drop it when malformed rather than reject
  // the whole snapshot and freeze ping/traceroute monitoring.
  if (snapshot.stormshield !== undefined && !isStormshieldInfo(snapshot.stormshield)) {
    delete snapshot.stormshield;
  }
  // Same for the firewall picker state: the Live view just hides the section.
  if (snapshot.sns !== undefined && !isSnsState(snapshot.sns)) {
    delete snapshot.sns;
  }
  return true;
}
