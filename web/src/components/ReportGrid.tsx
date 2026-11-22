import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";
import { Responsive, type Layout, type Layouts } from "react-grid-layout";
import type { MonitorSnapshot } from "../types/monitor";
import {
  BREAKPOINTS,
  COLS,
  DEFAULT_VISIBLE_INTERFACES,
  MARGIN,
  MAX_INTERFACE_PANELS,
  activeInterfaces,
  breakpointForWidth,
  clearStoredLayout,
  computeRowHeight,
  ifaceNameFromPanelId,
  ifacePanelId,
  isIfacePanelId,
  loadStoredLayout,
  mergeLayouts,
  presentPanelIds,
  resolveLayouts,
  saveStoredLayout,
  type PanelLayouts,
  type SavedLayouts,
} from "../utils/reportLayout";
import { ReportInterfaceChart, ReportInterfaceHeading } from "./ReportInterfaceChart";
import { ReportLatencyCaption, ReportLatencyChart } from "./ReportLatencyChart";
import {
  AlertsBody,
  FirewallBody,
  HostsBody,
  MetricsBody,
  PingsBody,
  ReportPanel,
  SmallLabel,
  SummaryBody,
  TracerouteBody,
} from "./ReportPanels";

// ---------------------------------------------------------------------------
// Layout state
// ---------------------------------------------------------------------------

type SaveStatus = "idle" | "saved" | "failed";

export type ReportGridController = {
  /** Locked layouts cannot be dragged or resized. Locked by default. */
  locked: boolean;
  toggleLocked: () => void;
  layouts: PanelLayouts;
  /** Ids of the panels to render, in reading order. */
  panelIds: string[];
  /** Interface names that are plugged in but currently hidden (can be added back). */
  hiddenInterfaces: string[];
  status: SaveStatus;
  save: () => void;
  reset: () => void;
  showInterface: (name: string) => void;
  hideInterface: (name: string) => void;
  onLayoutChange: (current: Layout[], all: Layouts) => void;
  onUserChange: () => void;
};

/**
 * Owns the layout state for the report: which panels exist, where they sit, the
 * lock flag and the save/reset actions. Lives outside <ReportGrid> so the header
 * can render the controls.
 */
export function useReportGrid(snapshot: MonitorSnapshot | null): ReportGridController {
  const [initial] = useState(loadStoredLayout);
  // null = nothing customised: the defaults are recomputed as panels come and go.
  const [layouts, setLayouts] = useState<SavedLayouts | null>(initial?.layouts ?? null);
  const [hidden, setHidden] = useState<string[] | null>(initial?.hiddenInterfaces ?? null);
  const [locked, setLocked] = useState(true);
  const [status, setStatus] = useState<SaveStatus>("idle");

  // Latest layouts reported by the grid, including panels that are not on screen.
  const knownRef = useRef<SavedLayouts | null>(initial?.layouts ?? null);
  // False until the user changes something (or a saved layout was loaded).
  const editedRef = useRef(initial !== null);
  // Set by a drag or resize stop, which the grid reports just before onLayoutChange.
  const userChangeRef = useRef(false);
  // Interface names in the order they were first seen, busiest first at that
  // moment. Interface rates change every poll; ranking live would swap panels.
  const orderRef = useRef<string[]>([]);
  const timerRef = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timerRef.current), []);

  const firewall = snapshot?.stormshield ?? null;
  const plugged = firewall ? activeInterfaces(firewall.interfaces) : [];
  for (const iface of plugged) {
    if (!orderRef.current.includes(iface.name)) orderRef.current.push(iface.name);
  }
  const pluggedNames = new Set(plugged.map((iface) => iface.name));
  const shown = orderRef.current
    .filter((name) => pluggedNames.has(name))
    .slice(0, MAX_INTERFACE_PANELS);
  const hiddenNames = hidden ?? shown.slice(DEFAULT_VISIBLE_INTERFACES);
  const visible = shown.filter((name) => !hiddenNames.includes(name));
  const hiddenInterfaces = shown.filter((name) => hiddenNames.includes(name));

  const hasFirewall = firewall !== null;
  const visibleKey = JSON.stringify(visible);
  // Keyed on visibleKey (the value of `visible`) so ctx keeps its identity between polls.
  const ctx = useMemo(
    () => ({ firewall: hasFirewall, ifaceIds: visible.map(ifacePanelId) }),
    [hasFirewall, visibleKey],
  );
  const resolved = useMemo(() => resolveLayouts(layouts, ctx), [layouts, ctx]);
  const panelIds = useMemo(() => presentPanelIds(ctx), [ctx]);

  // Pin the layout as it is now, so that it stops following the defaults.
  const freeze = () => {
    const base = mergeLayouts(editedRef.current ? knownRef.current : null, resolved);
    knownRef.current = base;
    editedRef.current = true;
    setLayouts(base);
  };

  // Only a drag or resize is stored. The grid also reports layouts it compacted
  // because panels came or went (an interface unplugged, the firewall reconnecting);
  // storing those would move panels up into the gaps, and they would collide when
  // the missing panels return.
  const onLayoutChange = (_current: Layout[], all: Layouts) => {
    const merged = mergeLayouts(knownRef.current, all);
    knownRef.current = merged;
    if (userChangeRef.current) {
      userChangeRef.current = false;
      setLayouts(merged);
    }
  };

  const save = () => {
    const ok = saveStoredLayout({
      layouts: mergeLayouts(editedRef.current ? knownRef.current : null, resolved),
      // null keeps the default rule (only the first four shown) for interfaces seen later.
      hiddenInterfaces: hidden,
    });
    setStatus(ok ? "saved" : "failed");
    window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => setStatus("idle"), 2000);
  };

  const reset = () => {
    clearStoredLayout();
    editedRef.current = false;
    knownRef.current = null;
    orderRef.current = [];
    window.clearTimeout(timerRef.current);
    setStatus("idle");
    setLayouts(null);
    setHidden(null);
  };

  return {
    locked,
    toggleLocked: () => setLocked((value) => !value),
    layouts: resolved,
    panelIds,
    hiddenInterfaces,
    status,
    save,
    reset,
    showInterface: (name) => {
      freeze();
      setHidden(hiddenNames.filter((hiddenName) => hiddenName !== name));
    },
    hideInterface: (name) => {
      freeze();
      setHidden([...hiddenNames, name]);
    },
    onLayoutChange,
    onUserChange: () => {
      freeze();
      userChangeRef.current = true;
      // A drop that changed nothing gets no onLayoutChange: don't leave the flag set.
      queueMicrotask(() => {
        userChangeRef.current = false;
      });
    },
  };
}

// ---------------------------------------------------------------------------
// Header controls
// ---------------------------------------------------------------------------

const CONTROL_BUTTON =
  "rounded-full border border-edge bg-surface px-2 py-0.5 text-xs text-fg-muted transition-colors hover:border-accent/40 hover:text-fg";

export function ReportLayoutControls({ grid }: { grid: ReportGridController }) {
  return (
    <div className="flex flex-wrap items-center justify-end gap-1.5">
      {grid.hiddenInterfaces.length > 0 && (
        <div className="flex flex-wrap items-center gap-1">
          <span className="text-xs text-fg-muted">Show:</span>
          {grid.hiddenInterfaces.map((name) => (
            <button
              key={name}
              type="button"
              className={CONTROL_BUTTON}
              onClick={() => grid.showInterface(name)}
              title={`Add the ${name} graph to the report`}
            >
              {name}
            </button>
          ))}
        </div>
      )}
      {grid.status !== "idle" && (
        <span
          role="status"
          className={`text-xs ${grid.status === "saved" ? "text-accent" : "text-warning"}`}
        >
          {grid.status === "saved" ? "Saved" : "Could not save"}
        </span>
      )}
      <button type="button" className={CONTROL_BUTTON} onClick={grid.save}>
        Save layout
      </button>
      <button type="button" className={CONTROL_BUTTON} onClick={grid.reset}>
        Reset layout
      </button>
      <button
        type="button"
        aria-pressed={!grid.locked}
        className={
          grid.locked
            ? CONTROL_BUTTON
            : "rounded-full border border-accent/30 bg-accent/20 px-2 py-0.5 text-xs font-medium text-accent"
        }
        onClick={grid.toggleLocked}
      >
        {grid.locked ? "Edit layout" : "Lock layout"}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Grid
// ---------------------------------------------------------------------------

/** Content-box size of an element, kept current with a ResizeObserver. */
function useContentSize(ref: RefObject<HTMLElement | null>) {
  const [size, setSize] = useState({ width: 0, height: 0 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => {
      const style = getComputedStyle(el);
      const width =
        el.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
      const height =
        el.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom);
      setSize((prev) => (prev.width === width && prev.height === height ? prev : { width, height }));
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref]);
  return size;
}

type ReportGridProps = {
  snapshot: MonitorSnapshot;
  grid: ReportGridController;
};

export function ReportGrid({ snapshot, grid }: ReportGridProps) {
  const bodyRef = useRef<HTMLDivElement>(null);
  const size = useContentSize(bodyRef);
  const editing = !grid.locked;

  // The grid is given the measured width directly (rather than wrapped in
  // WidthProvider) so there is a single source of truth for the breakpoint and
  // no first frame at WidthProvider's 1280 px default.
  // From md up the default layout fills the body exactly; below it the body
  // scrolls and rows have a fixed height.
  const rowHeight = computeRowHeight(size.height, breakpointForWidth(size.width));

  const firewall = snapshot.stormshield ?? null;
  const plugged = firewall ? activeInterfaces(firewall.interfaces) : [];

  const renderPanel = (id: string): ReactNode => {
    switch (id) {
      case "metrics":
        return (
          <ReportPanel title="Latency stats" editing={editing}>
            <MetricsBody snapshot={snapshot} />
          </ReportPanel>
        );
      case "summary":
        return (
          <ReportPanel title="Summary" editing={editing}>
            <SummaryBody snapshot={snapshot} />
          </ReportPanel>
        );
      case "firewall":
        return firewall ? (
          <ReportPanel title={<SmallLabel>Firewall</SmallLabel>} editing={editing}>
            <FirewallBody
              firewall={firewall}
              // By name: ranking by live rate would reshuffle the chips every poll.
              interfaces={[...plugged].sort((a, b) => a.name.localeCompare(b.name))}
            />
          </ReportPanel>
        ) : null;
      case "latency":
        return (
          <ReportPanel
            title="Latency (1h)"
            extra={<ReportLatencyCaption />}
            editing={editing}
            scroll={false}
          >
            <ReportLatencyChart pingHistory={snapshot.ping_history} />
          </ReportPanel>
        );
      case "traceroute":
        return (
          <ReportPanel title="Traceroute" editing={editing}>
            <TracerouteBody snapshot={snapshot} />
          </ReportPanel>
        );
      case "pings":
        return (
          <ReportPanel title="Recent pings" editing={editing}>
            <PingsBody snapshot={snapshot} />
          </ReportPanel>
        );
      case "hosts":
        return firewall ? (
          <ReportPanel
            title="Top hosts"
            editing={editing}
            extra={
              firewall.host_interfaces.length > 0 ? (
                <span className="font-mono text-[10px] text-fg-muted">
                  on {firewall.host_interfaces.join(", ")}
                </span>
              ) : undefined
            }
          >
            <HostsBody firewall={firewall} />
          </ReportPanel>
        ) : null;
      case "alerts":
        return (
          <ReportPanel title={<SmallLabel>Recent alerts</SmallLabel>} editing={editing}>
            <AlertsBody snapshot={snapshot} />
          </ReportPanel>
        );
      default: {
        if (!isIfacePanelId(id)) return null;
        const name = ifaceNameFromPanelId(id);
        const iface = plugged.find((candidate) => candidate.name === name);
        if (!iface) return null;
        return (
          <ReportPanel
            title={<ReportInterfaceHeading iface={iface} />}
            editing={editing}
            onHide={() => grid.hideInterface(name)}
            scroll={false}
          >
            <ReportInterfaceChart iface={iface} />
          </ReportPanel>
        );
      }
    }
  };

  return (
    <div ref={bodyRef} className="min-h-0 flex-1 overflow-y-auto p-2 md:p-3">
      {size.width > 0 && (
        <Responsive
          className={`report-grid${editing ? " report-grid--editing" : ""}`}
          width={size.width}
          breakpoints={BREAKPOINTS}
          cols={COLS}
          layouts={grid.layouts}
          rowHeight={rowHeight}
          margin={[MARGIN, MARGIN]}
          containerPadding={[0, 0]}
          compactType="vertical"
          draggableHandle=".panel-drag"
          resizeHandles={["se"]}
          isBounded
          isDraggable={editing}
          isResizable={editing}
          onLayoutChange={grid.onLayoutChange}
          onDragStop={grid.onUserChange}
          onResizeStop={grid.onUserChange}
        >
          {grid.panelIds.map((id) => (
            <div key={id}>{renderPanel(id)}</div>
          ))}
        </Responsive>
      )}
    </div>
  );
}
