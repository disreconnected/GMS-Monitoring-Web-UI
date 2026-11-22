import type { StormshieldInterface } from "../types/monitor";

// ---------------------------------------------------------------------------
// Grid geometry
// ---------------------------------------------------------------------------

export const BREAKPOINT_NAMES = ["lg", "md", "sm"] as const;
export type BreakpointName = (typeof BREAKPOINT_NAMES)[number];

export const BREAKPOINTS: Record<BreakpointName, number> = { lg: 1200, md: 900, sm: 0 };
export const COLS: Record<BreakpointName, number> = { lg: 12, md: 12, sm: 2 };

/** Grid rows the default lg/md layout spans; row height is derived from this. */
export const ROWS = 26;
export const MARGIN = 8;
/** Below this the page scrolls instead of squeezing panels further. */
export const MIN_ROW_HEIGHT = 14;
/** On the single-column `sm` layout the page scrolls, so rows have a fixed height. */
export const SM_ROW_HEIGHT = 24;

export const STORAGE_KEY = "gms.report.layout.v1";

export const MAX_INTERFACE_PANELS = 6;
export const DEFAULT_VISIBLE_INTERFACES = 4;

// ---------------------------------------------------------------------------
// Panel ids
// ---------------------------------------------------------------------------

export const FIXED_PANEL_IDS = [
  "metrics",
  "summary",
  "firewall",
  "latency",
  "traceroute",
  "pings",
  "hosts",
  "alerts",
] as const;

const IFACE_PREFIX = "iface:";

export function ifacePanelId(name: string): string {
  return `${IFACE_PREFIX}${name}`;
}

export function isIfacePanelId(id: string): boolean {
  return id.startsWith(IFACE_PREFIX) && id.length > IFACE_PREFIX.length;
}

export function ifaceNameFromPanelId(id: string): string {
  return id.slice(IFACE_PREFIX.length);
}

function isKnownPanelId(id: string): boolean {
  return (FIXED_PANEL_IDS as readonly string[]).includes(id) || isIfacePanelId(id);
}

/** Plugged interfaces, busiest (rx + tx) first. */
export function activeInterfaces(interfaces: StormshieldInterface[]): StormshieldInterface[] {
  return interfaces
    .filter((iface) => iface.plugged === 1)
    .sort((a, b) => b.rx_mbps + b.tx_mbps - (a.rx_mbps + a.tx_mbps));
}

// ---------------------------------------------------------------------------
// Layout types
// ---------------------------------------------------------------------------

export type LayoutItem = {
  i: string;
  x: number;
  y: number;
  w: number;
  h: number;
  minW?: number;
  minH?: number;
};

export type PanelLayouts = Record<BreakpointName, LayoutItem[]>;
/** Layouts as stored: any breakpoint may be missing and falls back to the default. */
export type SavedLayouts = Partial<PanelLayouts>;

export type StoredLayout = {
  layouts: SavedLayouts;
  /** Interface names the user hid, or null to apply the default (top 4 visible). */
  hiddenInterfaces: string[] | null;
};

export type DefaultContext = {
  firewall: boolean;
  /** Panel ids (`iface:<name>`) of the interface panels to show, in slot order. */
  ifaceIds: string[];
};

export function panelMinSize(id: string): { minW: number; minH: number } {
  const chart = id === "latency" || isIfacePanelId(id);
  return { minW: 2, minH: chart ? 4 : 2 };
}

function withMin(item: LayoutItem): LayoutItem {
  return { ...item, ...panelMinSize(item.i) };
}

export function breakpointForWidth(width: number): BreakpointName {
  // Mirrors react-grid-layout's getBreakpointFromWidth (strictly greater-than).
  let matching: BreakpointName = "sm";
  if (width > BREAKPOINTS.md) matching = "md";
  if (width > BREAKPOINTS.lg) matching = "lg";
  return matching;
}

/** Row height that makes ROWS rows fill `height`; fixed on the scrolling `sm` layout. */
export function computeRowHeight(height: number, breakpoint: BreakpointName): number {
  if (breakpoint === "sm") return SM_ROW_HEIGHT;
  const fitted = Math.floor(((height - MARGIN * (ROWS - 1)) / ROWS) * 100) / 100;
  return Math.max(MIN_ROW_HEIGHT, fitted);
}

// ---------------------------------------------------------------------------
// Default layouts
// ---------------------------------------------------------------------------

/** Ordered list of the panels that exist for this context (also the `sm` stacking order). */
export function presentPanelIds(ctx: DefaultContext): string[] {
  return [
    "metrics",
    "summary",
    ...(ctx.firewall ? ["firewall"] : []),
    "latency",
    ...ctx.ifaceIds,
    "traceroute",
    "pings",
    ...(ctx.firewall ? ["hosts"] : []),
    "alerts",
  ];
}

// Row counts for the single-column layout, where every panel is full width.
const SM_HEIGHTS: Record<string, number> = {
  metrics: 5,
  summary: 6,
  firewall: 8,
  latency: 8,
  traceroute: 10,
  pings: 10,
  hosts: 10,
  alerts: 5,
};
const SM_IFACE_HEIGHT = 8;

function stackedLayout(ctx: DefaultContext): LayoutItem[] {
  let y = 0;
  return presentPanelIds(ctx).map((id) => {
    const h = SM_HEIGHTS[id] ?? SM_IFACE_HEIGHT;
    const item = withMin({ i: id, x: 0, y, w: COLS.sm, h });
    y += h;
    return item;
  });
}

type Slot = [x: number, y: number, w: number, h: number];

// Interface panels share the right column below the latency chart: x 4..12, y 6..18.
function ifaceSlots(count: number): Slot[] {
  const slots: Slot[] = [];
  if (count === 1) slots.push([4, 6, 8, 12]);
  else if (count === 2) slots.push([4, 6, 4, 12], [8, 6, 4, 12]);
  else if (count === 3) slots.push([4, 6, 4, 6], [8, 6, 4, 6], [4, 12, 8, 6]);
  else slots.push([4, 6, 4, 6], [8, 6, 4, 6], [4, 12, 4, 6], [8, 12, 4, 6]);
  // Anything past the fourth goes below the alerts row.
  for (let k = slots.length; k < count; k += 1) {
    slots.push([6 * ((k - 4) % 2), ROWS + 7 * Math.floor((k - 4) / 2), 6, 7]);
  }
  return slots;
}

function wideLayout(ctx: DefaultContext): LayoutItem[] {
  const items: LayoutItem[] = [];
  const add = (i: string, x: number, y: number, w: number, h: number) =>
    items.push(withMin({ i, x, y, w, h }));

  // The small text panels get 4 rows (3 for alerts) so their content fits at a
  // 1080p row height; on shorter screens their bodies scroll.
  add("metrics", 0, 0, 4, 4);
  add("summary", 0, 4, 4, 4);

  if (!ctx.firewall) {
    add("traceroute", 0, 8, 4, 15);
    add("latency", 4, 0, 8, 14);
    add("pings", 4, 14, 8, 12);
  } else {
    add("firewall", 0, 8, 4, 4);
    add("traceroute", 0, 12, 4, 11);
    add("hosts", 4, 18, 5, 8);
    add("pings", 9, 18, 3, 8);
    if (ctx.ifaceIds.length === 0) {
      add("latency", 4, 0, 8, 18);
    } else {
      add("latency", 4, 0, 8, 6);
      const slots = ifaceSlots(ctx.ifaceIds.length);
      ctx.ifaceIds.forEach((id, k) => add(id, ...slots[k]));
    }
  }

  add("alerts", 0, 23, 4, 3);
  return items;
}

export function buildDefaultLayouts(ctx: DefaultContext): PanelLayouts {
  const wide = wideLayout(ctx);
  return {
    lg: wide,
    md: wide.map((item) => ({ ...item })),
    sm: stackedLayout(ctx),
  };
}

function bottomOf(items: LayoutItem[]): number {
  return items.reduce((max, item) => Math.max(max, item.y + item.h), 0);
}

/**
 * Layouts to hand to the grid. With nothing saved this is the default set.
 * With a saved set it is used as-is for the panels it knows about; ids that are
 * not shown right now are ignored, and shown panels it lacks are appended at the
 * bottom with their default size.
 */
export function resolveLayouts(saved: SavedLayouts | null, ctx: DefaultContext): PanelLayouts {
  const defaults = buildDefaultLayouts(ctx);
  if (!saved) return defaults;

  const present = presentPanelIds(ctx);
  const out = {} as PanelLayouts;
  for (const bp of BREAKPOINT_NAMES) {
    const savedItems = saved[bp];
    if (!savedItems) {
      out[bp] = defaults[bp];
      continue;
    }
    const items = savedItems.filter((item) => present.includes(item.i)).map(withMin);
    let bottom = bottomOf(items);
    for (const id of present) {
      if (items.some((item) => item.i === id)) continue;
      const fallback = defaults[bp].find((item) => item.i === id);
      if (!fallback) continue;
      items.push(withMin({ ...fallback, x: 0, y: bottom, w: Math.min(fallback.w, COLS[bp]) }));
      bottom += fallback.h;
    }
    out[bp] = items;
  }
  return out;
}

function strip(item: LayoutItem): LayoutItem {
  return { i: item.i, x: item.x, y: item.y, w: item.w, h: item.h };
}

/**
 * Fold the grid's report (which only lists panels that are on screen) into what
 * we already know, keeping entries of panels that are not shown right now - for
 * example an interface that is briefly missing from a snapshot.
 */
export function mergeLayouts(
  previous: SavedLayouts | null,
  next: Record<string, LayoutItem[] | undefined>,
): PanelLayouts {
  const out = {} as PanelLayouts;
  for (const bp of BREAKPOINT_NAMES) {
    const reported = (next[bp] ?? []).map(strip);
    const seen = new Set(reported.map((item) => item.i));
    const kept = (previous?.[bp] ?? []).filter((item) => !seen.has(item.i)).map(strip);
    out[bp] = [...reported, ...kept];
  }
  return out;
}

// ---------------------------------------------------------------------------
// Persistence
// ---------------------------------------------------------------------------

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseItems(value: unknown): LayoutItem[] | null {
  if (!Array.isArray(value)) return null;
  const items: LayoutItem[] = [];
  const seen = new Set<string>();
  for (const raw of value) {
    if (!isRecord(raw) || typeof raw.i !== "string") return null;
    const { x, y, w, h } = raw;
    if (
      typeof x !== "number" ||
      typeof y !== "number" ||
      typeof w !== "number" ||
      typeof h !== "number" ||
      !Number.isFinite(x) ||
      !Number.isFinite(y) ||
      !Number.isFinite(w) ||
      !Number.isFinite(h)
    ) {
      return null;
    }
    // Ids this version does not know are dropped rather than failing the whole load.
    if (!isKnownPanelId(raw.i) || seen.has(raw.i)) continue;
    seen.add(raw.i);
    items.push({
      i: raw.i,
      x: Math.max(0, Math.round(x)),
      y: Math.max(0, Math.round(y)),
      w: Math.max(1, Math.round(w)),
      h: Math.max(1, Math.round(h)),
    });
  }
  return items;
}

/** Returns null for anything that is not a well-formed saved layout. */
export function parseStoredLayout(raw: string | null | undefined): StoredLayout | null {
  if (!raw) return null;
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!isRecord(data) || !isRecord(data.layouts)) return null;

  const layouts: SavedLayouts = {};
  for (const bp of BREAKPOINT_NAMES) {
    const value = data.layouts[bp];
    if (value === undefined) continue;
    const items = parseItems(value);
    if (!items) return null;
    layouts[bp] = items;
  }
  if (Object.keys(layouts).length === 0) return null;

  const hidden = data.hiddenInterfaces;
  const hiddenInterfaces =
    Array.isArray(hidden) && hidden.every((name) => typeof name === "string")
      ? Array.from(new Set(hidden as string[]))
      : null;
  return { layouts, hiddenInterfaces };
}

export function serializeStoredLayout(stored: StoredLayout): string {
  const layouts: Record<string, LayoutItem[]> = {};
  for (const bp of BREAKPOINT_NAMES) {
    const items = stored.layouts[bp];
    if (items) layouts[bp] = items.map(strip);
  }
  return JSON.stringify({ layouts, hiddenInterfaces: stored.hiddenInterfaces });
}

export function loadStoredLayout(): StoredLayout | null {
  try {
    return parseStoredLayout(localStorage.getItem(STORAGE_KEY));
  } catch {
    return null;
  }
}

export function saveStoredLayout(stored: StoredLayout): boolean {
  try {
    localStorage.setItem(STORAGE_KEY, serializeStoredLayout(stored));
    return true;
  } catch {
    return false;
  }
}

export function clearStoredLayout(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Storage unavailable: nothing to clear.
  }
}
