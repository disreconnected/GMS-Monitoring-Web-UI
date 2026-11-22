import { describe, expect, it } from "vitest";
import { isMonitorSnapshot } from "./validateSnapshot";

function baseSnapshot(): Record<string, unknown> {
  return {
    host: "8.8.8.8",
    timestamp: 1_700_000_000,
    quality: "Excellent",
    quality_code: "excellent",
    paused: false,
    ping_history: [],
    bandwidth: { history: [] },
    traceroute: { hops: [] },
    session: {},
  };
}

function validStormshield(): Record<string, unknown> {
  return {
    connected: true,
    error: null,
    model: "SN510",
    version: "4.8.0",
    host: "192.168.1.254",
    last_poll: 1_700_000_000,
    interfaces: [{ name: "out", history: [] }],
    hosts: [],
    host_interfaces: ["in"],
  };
}

function validSns(): Record<string, unknown> {
  return {
    active_host: "10.5.1.1",
    password_set: true,
    saved_hosts: [{ host: "10.5.1.1", label: "Church A", last_seen: 1_700_000_000 }],
    candidates: [
      { host: "10.5.1.1", reachable: true, stormshield: true, latency_ms: 12.5 },
      { host: "10.5.2.1", reachable: false, stormshield: false, latency_ms: null },
    ],
    probed_at: 1_700_000_000,
    busy: false,
    message: null,
  };
}

describe("isMonitorSnapshot", () => {
  it("accepts a valid base snapshot", () => {
    expect(isMonitorSnapshot(baseSnapshot())).toBe(true);
  });

  it("accepts a snapshot with a valid stormshield block", () => {
    const snapshot = { ...baseSnapshot(), stormshield: validStormshield() };
    expect(isMonitorSnapshot(snapshot)).toBe(true);
    expect(snapshot.stormshield).toBeDefined();
  });

  it("accepts a snapshot with a malformed stormshield block and drops it", () => {
    const snapshot = {
      ...baseSnapshot(),
      stormshield: { ...validStormshield(), interfaces: [{ name: "out" }] },
    };
    expect(isMonitorSnapshot(snapshot)).toBe(true);
    expect("stormshield" in snapshot).toBe(false);
  });

  it("accepts a snapshot with a valid sns block", () => {
    const snapshot = { ...baseSnapshot(), sns: validSns() };
    expect(isMonitorSnapshot(snapshot)).toBe(true);
    expect(snapshot.sns).toBeDefined();
  });

  it("accepts an empty sns block (nothing saved, nothing probed)", () => {
    const snapshot = {
      ...baseSnapshot(),
      sns: {
        ...validSns(),
        active_host: null,
        saved_hosts: [],
        candidates: [],
        probed_at: null,
        message: "no Stormshield found among 4 candidates",
      },
    };
    expect(isMonitorSnapshot(snapshot)).toBe(true);
    expect(snapshot.sns).toBeDefined();
  });

  it("accepts a snapshot with a malformed sns block and drops it", () => {
    const malformed = [
      { ...validSns(), busy: "no" },
      { ...validSns(), saved_hosts: [{ host: 5, label: "", last_seen: null }] },
      { ...validSns(), candidates: [{ host: "10.5.1.1" }] },
      { ...validSns(), active_host: undefined },
      "not-an-object",
    ];
    for (const sns of malformed) {
      const snapshot = { ...baseSnapshot(), stormshield: validStormshield(), sns };
      expect(isMonitorSnapshot(snapshot)).toBe(true);
      expect("sns" in snapshot).toBe(false);
      expect(snapshot.stormshield).toBeDefined();
    }
  });

  it("rejects a snapshot missing host", () => {
    const snapshot = baseSnapshot();
    delete snapshot.host;
    expect(isMonitorSnapshot(snapshot)).toBe(false);
  });
});
