import { describe, expect, it } from "vitest";
import type { StormshieldInterface } from "../types/monitor";
import {
  BREAKPOINT_NAMES,
  COLS,
  FIXED_PANEL_IDS,
  MIN_ROW_HEIGHT,
  ROWS,
  SM_ROW_HEIGHT,
  activeInterfaces,
  breakpointForWidth,
  buildDefaultLayouts,
  computeRowHeight,
  ifacePanelId,
  mergeLayouts,
  parseStoredLayout,
  presentPanelIds,
  resolveLayouts,
  serializeStoredLayout,
  type DefaultContext,
  type LayoutItem,
  type StoredLayout,
} from "./reportLayout";

const FOUR_IFACES: DefaultContext = {
  firewall: true,
  ifaceIds: ["CBN", "Fibernet", "LAN", "DMZ"].map(ifacePanelId),
};

function ids(items: LayoutItem[]): string[] {
  return items.map((item) => item.i).sort();
}

function overlaps(a: LayoutItem, b: LayoutItem): boolean {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

describe("buildDefaultLayouts", () => {
  it("covers every fixed panel plus the interface panels at every breakpoint", () => {
    const layouts = buildDefaultLayouts(FOUR_IFACES);
    const expected = [...FIXED_PANEL_IDS, ...FOUR_IFACES.ifaceIds].sort();
    for (const bp of BREAKPOINT_NAMES) {
      expect(ids(layouts[bp])).toEqual(expected);
    }
  });

  it("fills exactly ROWS rows of 12 columns without overlaps at lg/md", () => {
    const { lg, md } = buildDefaultLayouts(FOUR_IFACES);
    expect(md).toEqual(lg);
    expect(Math.max(...lg.map((item) => item.y + item.h))).toBe(ROWS);
    for (const item of lg) {
      expect(item.x + item.w).toBeLessThanOrEqual(COLS.lg);
    }
    for (let a = 0; a < lg.length; a += 1) {
      for (let b = a + 1; b < lg.length; b += 1) {
        expect(overlaps(lg[a], lg[b]), `${lg[a].i} vs ${lg[b].i}`).toBe(false);
      }
    }
  });

  it("stacks every panel full width on sm", () => {
    const { sm } = buildDefaultLayouts(FOUR_IFACES);
    expect(sm.every((item) => item.x === 0 && item.w === COLS.sm)).toBe(true);
    for (let a = 0; a < sm.length; a += 1) {
      for (let b = a + 1; b < sm.length; b += 1) {
        expect(overlaps(sm[a], sm[b])).toBe(false);
      }
    }
  });

  it("gives every panel a minimum size, charts at least 4 rows", () => {
    for (const bp of BREAKPOINT_NAMES) {
      for (const item of buildDefaultLayouts(FOUR_IFACES)[bp]) {
        expect(item.minW).toBe(2);
        const chart = item.i === "latency" || item.i.startsWith("iface:");
        expect(item.minH).toBe(chart ? 4 : 2);
      }
    }
  });

  it("omits the firewall, interface and hosts panels without a firewall", () => {
    const ctx: DefaultContext = { firewall: false, ifaceIds: [] };
    const layouts = buildDefaultLayouts(ctx);
    for (const bp of BREAKPOINT_NAMES) {
      expect(ids(layouts[bp])).toEqual(
        ["alerts", "latency", "metrics", "pings", "summary", "traceroute"],
      );
    }
    expect(Math.max(...layouts.lg.map((item) => item.y + item.h))).toBe(ROWS);
  });

  it("re-flows the right column for fewer than four interfaces", () => {
    for (const count of [0, 1, 2, 3]) {
      const ctx: DefaultContext = {
        firewall: true,
        ifaceIds: FOUR_IFACES.ifaceIds.slice(0, count),
      };
      const { lg } = buildDefaultLayouts(ctx);
      expect(ids(lg)).toEqual([...presentPanelIds(ctx)].sort());
      for (let a = 0; a < lg.length; a += 1) {
        for (let b = a + 1; b < lg.length; b += 1) {
          expect(overlaps(lg[a], lg[b]), `${count}: ${lg[a].i} vs ${lg[b].i}`).toBe(false);
        }
      }
    }
  });
});

describe("resolveLayouts", () => {
  it("returns the defaults when nothing is saved", () => {
    expect(resolveLayouts(null, FOUR_IFACES)).toEqual(buildDefaultLayouts(FOUR_IFACES));
  });

  it("uses a saved layout as-is and appends missing panels at the bottom", () => {
    const saved = {
      lg: [
        { i: "metrics", x: 6, y: 0, w: 6, h: 3 },
        { i: "latency", x: 0, y: 3, w: 12, h: 5 },
      ],
    };
    const resolved = resolveLayouts(saved, { firewall: false, ifaceIds: [] });
    const metrics = resolved.lg.find((item) => item.i === "metrics");
    expect(metrics).toMatchObject({ x: 6, y: 0, w: 6, h: 3 });
    const summary = resolved.lg.find((item) => item.i === "summary");
    // Appended below the lowest saved panel (latency ends at row 8) at its default size.
    expect(summary).toMatchObject({ x: 0, y: 8, w: 4, h: 4 });
    const traceroute = resolved.lg.find((item) => item.i === "traceroute");
    expect(traceroute?.y).toBe(12);
    expect(ids(resolved.lg)).toEqual(
      ["alerts", "latency", "metrics", "pings", "summary", "traceroute"],
    );
    // Breakpoints missing from storage fall back to their defaults.
    expect(resolved.sm).toEqual(buildDefaultLayouts({ firewall: false, ifaceIds: [] }).sm);
  });

  it("ignores saved entries for panels that are not shown", () => {
    const saved = {
      lg: [
        { i: "metrics", x: 0, y: 0, w: 4, h: 3 },
        { i: "iface:Gone", x: 4, y: 0, w: 4, h: 7 },
        { i: "firewall", x: 0, y: 3, w: 4, h: 5 },
      ],
    };
    const resolved = resolveLayouts(saved, { firewall: false, ifaceIds: [] });
    expect(resolved.lg.some((item) => item.i === "iface:Gone")).toBe(false);
    expect(resolved.lg.some((item) => item.i === "firewall")).toBe(false);
  });

  it("re-applies current minimum sizes to saved items", () => {
    const resolved = resolveLayouts(
      { lg: [{ i: "latency", x: 0, y: 0, w: 4, h: 4 }] },
      { firewall: false, ifaceIds: [] },
    );
    expect(resolved.lg.find((item) => item.i === "latency")).toMatchObject({ minW: 2, minH: 4 });
  });
});

describe("mergeLayouts", () => {
  it("keeps entries of panels the grid did not report", () => {
    const previous = {
      lg: [
        { i: "metrics", x: 0, y: 0, w: 4, h: 3 },
        { i: "iface:Gone", x: 4, y: 0, w: 4, h: 7 },
      ],
    };
    const merged = mergeLayouts(previous, {
      lg: [{ i: "metrics", x: 2, y: 1, w: 4, h: 3, minW: 2, minH: 2 }],
    });
    expect(merged.lg).toEqual([
      { i: "metrics", x: 2, y: 1, w: 4, h: 3 },
      { i: "iface:Gone", x: 4, y: 0, w: 4, h: 7 },
    ]);
    expect(merged.md).toEqual([]);
    expect(merged.sm).toEqual([]);
  });
});

describe("parseStoredLayout", () => {
  const valid = {
    layouts: { lg: [{ i: "metrics", x: 0, y: 0, w: 4, h: 3 }] },
    hiddenInterfaces: ["CBN"],
  };

  it("accepts a well-formed layout", () => {
    expect(parseStoredLayout(JSON.stringify(valid))).toEqual({
      layouts: { lg: [{ i: "metrics", x: 0, y: 0, w: 4, h: 3 }] },
      hiddenInterfaces: ["CBN"],
    });
  });

  it("rejects empty input and malformed JSON", () => {
    expect(parseStoredLayout(null)).toBeNull();
    expect(parseStoredLayout("")).toBeNull();
    expect(parseStoredLayout("{not json")).toBeNull();
  });

  it("rejects the wrong overall shape", () => {
    expect(parseStoredLayout("[]")).toBeNull();
    expect(parseStoredLayout("42")).toBeNull();
    expect(parseStoredLayout(JSON.stringify({}))).toBeNull();
    expect(parseStoredLayout(JSON.stringify({ layouts: [] }))).toBeNull();
    expect(parseStoredLayout(JSON.stringify({ layouts: {} }))).toBeNull();
    expect(parseStoredLayout(JSON.stringify({ layouts: { xl: [] } }))).toBeNull();
  });

  it("rejects items with missing, non-numeric or non-finite fields", () => {
    const bad = (item: unknown) =>
      parseStoredLayout(JSON.stringify({ layouts: { lg: [item] } }));
    expect(bad({ i: "metrics", x: 0, y: 0, w: 4 })).toBeNull();
    expect(bad({ i: "metrics", x: "0", y: 0, w: 4, h: 3 })).toBeNull();
    expect(bad({ i: "metrics", x: null, y: 0, w: 4, h: 3 })).toBeNull();
    expect(bad({ i: 7, x: 0, y: 0, w: 4, h: 3 })).toBeNull();
    expect(bad("metrics")).toBeNull();
    // 1e999 parses to Infinity.
    expect(parseStoredLayout('{"layouts":{"lg":[{"i":"metrics","x":0,"y":0,"w":1e999,"h":3}]}}')).toBeNull();
    expect(parseStoredLayout(JSON.stringify({ layouts: { lg: "nope" } }))).toBeNull();
  });

  it("drops unknown ids and duplicates instead of failing", () => {
    const parsed = parseStoredLayout(
      JSON.stringify({
        layouts: {
          lg: [
            { i: "metrics", x: 0, y: 0, w: 4, h: 3 },
            { i: "metrics", x: 9, y: 9, w: 1, h: 1 },
            { i: "mystery", x: 0, y: 3, w: 4, h: 3 },
            { i: "iface:", x: 0, y: 3, w: 4, h: 3 },
            { i: "iface:CBN", x: 4, y: 0, w: 4, h: 7 },
          ],
        },
      }),
    );
    expect(parsed?.layouts.lg?.map((item) => item.i)).toEqual(["metrics", "iface:CBN"]);
    expect(parsed?.hiddenInterfaces).toBeNull();
  });

  it("ignores a malformed hiddenInterfaces field", () => {
    const parsed = parseStoredLayout(
      JSON.stringify({ ...valid, hiddenInterfaces: ["CBN", 3] }),
    );
    expect(parsed?.hiddenInterfaces).toBeNull();
  });
});

describe("serializeStoredLayout", () => {
  it("round-trips through parseStoredLayout", () => {
    const defaults = buildDefaultLayouts(FOUR_IFACES);
    const stored: StoredLayout = {
      layouts: {
        lg: defaults.lg.map(({ i, x, y, w, h }) => ({ i, x, y, w, h })),
        md: defaults.md.map(({ i, x, y, w, h }) => ({ i, x, y, w, h })),
        sm: defaults.sm.map(({ i, x, y, w, h }) => ({ i, x, y, w, h })),
      },
      hiddenInterfaces: ["Spare"],
    };
    expect(parseStoredLayout(serializeStoredLayout(stored))).toEqual(stored);
  });

  it("drops grid-only fields such as minW/minH", () => {
    const stored: StoredLayout = {
      layouts: { lg: [{ i: "metrics", x: 0, y: 0, w: 4, h: 3, minW: 2, minH: 2 }] },
      hiddenInterfaces: null,
    };
    expect(JSON.parse(serializeStoredLayout(stored)).layouts.lg[0]).toEqual({
      i: "metrics",
      x: 0,
      y: 0,
      w: 4,
      h: 3,
    });
  });
});

describe("geometry helpers", () => {
  it("picks the breakpoint like react-grid-layout", () => {
    expect(breakpointForWidth(1920)).toBe("lg");
    expect(breakpointForWidth(1201)).toBe("lg");
    expect(breakpointForWidth(1200)).toBe("md");
    expect(breakpointForWidth(901)).toBe("md");
    expect(breakpointForWidth(900)).toBe("sm");
    expect(breakpointForWidth(375)).toBe("sm");
  });

  it("derives a row height that fills the body without overflowing", () => {
    const rh = computeRowHeight(820, "lg");
    expect(rh * ROWS + 8 * (ROWS - 1)).toBeLessThanOrEqual(820);
    expect(rh * ROWS + 8 * (ROWS - 1)).toBeGreaterThan(820 - ROWS);
  });

  it("floors the row height on short screens and fixes it on sm", () => {
    expect(computeRowHeight(100, "lg")).toBe(MIN_ROW_HEIGHT);
    expect(computeRowHeight(900, "sm")).toBe(SM_ROW_HEIGHT);
  });
});

describe("activeInterfaces", () => {
  const iface = (name: string, plugged: number, rx: number, tx: number): StormshieldInterface => ({
    name,
    real_name: name,
    type: "ethernet",
    addr: "",
    state: 1,
    plugged,
    protected: 0,
    link_mbps: 1000,
    rx_mbps: rx,
    tx_mbps: tx,
    avg_rx_mbps: 0,
    avg_tx_mbps: 0,
    tcp_conn: 0,
    udp_conn: 0,
    history: [],
  });

  it("keeps plugged interfaces, busiest first", () => {
    const ranked = activeInterfaces([
      iface("quiet", 1, 1, 1),
      iface("unplugged", 0, 99, 99),
      iface("busy", 1, 10, 5),
    ]);
    expect(ranked.map((i) => i.name)).toEqual(["busy", "quiet"]);
  });
});
