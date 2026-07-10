import { Pause, Play, Pulse, Stop, WifiHigh, WifiSlash } from "@phosphor-icons/react";
import type { ConnectionStatus, MonitorSnapshot, AppView } from "../types/monitor";
import type { Theme } from "../hooks/useTheme";
import { ThemeToggle } from "./ThemeToggle";

type TopBarProps = {
  snapshot: MonitorSnapshot | null;
  status: ConnectionStatus;
  view: AppView;
  theme: Theme;
  controlsEnabled: boolean;
  onViewChange: (view: AppView) => void;
  onThemeToggle: () => void;
  onPause: () => void;
  onResume: () => void;
  onStop: () => void;
};

function qualityClass(code: MonitorSnapshot["quality_code"] | undefined): string {
  switch (code) {
    case "excellent":
      return "bg-accent/20 text-accent border-accent/30";
    case "good":
      return "bg-emerald-500/20 text-emerald-400 border-emerald-500/30";
    case "fair":
      return "bg-warning/20 text-warning border-warning/30";
    case "poor":
      return "bg-danger/20 text-danger border-danger/30";
    default:
      return "bg-surface text-fg-muted border-edge";
  }
}

function statusLabel(status: ConnectionStatus): string {
  switch (status) {
    case "connected":
      return "Live";
    case "connecting":
      return "Connecting";
    case "auth_error":
      return "Unauthorized";
    case "origin_error":
      return "Origin blocked";
    case "client_limit":
      return "Client limit";
    default:
      return "Offline";
  }
}

export function TopBar({
  snapshot,
  status,
  view,
  theme,
  controlsEnabled,
  onViewChange,
  onThemeToggle,
  onPause,
  onResume,
  onStop,
}: TopBarProps) {
  const paused = snapshot?.paused ?? false;
  const host = snapshot?.host ?? "connecting...";
  const quality = snapshot?.quality ?? "Unknown";
  const qualityCode = snapshot?.quality_code;

  const handleStop = () => {
    if (window.confirm("Stop the GMS monitoring web server?")) {
      onStop();
    }
  };

  return (
    <header className="sticky top-0 z-20 px-4 py-4 md:px-8">
      <div className="mx-auto flex max-w-7xl items-center justify-between gap-2 rounded-full border border-edge/60 bg-surface/70 px-3 py-2.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.06)] backdrop-blur-xl md:gap-4 md:px-6">
        <div className="flex min-w-0 items-center gap-2 md:gap-3">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent/15 text-accent md:h-9 md:w-9">
            <Pulse size={16} weight="bold" className="md:hidden" />
            <Pulse size={18} weight="bold" className="hidden md:block" />
          </div>
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-fg">GMS Monitoring</p>
            <p className="truncate font-mono text-xs text-fg-muted">{host}</p>
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-1.5 md:gap-2">
          <div className="inline-flex rounded-full border border-edge bg-bg/60 p-0.5">
            <button
              type="button"
              onClick={() => onViewChange("live")}
              className={`rounded-full px-2.5 py-1 text-xs font-medium transition md:px-3 ${
                view === "live"
                  ? "bg-accent text-white"
                  : "text-fg-muted hover:text-fg"
              }`}
            >
              Live
            </button>
            <button
              type="button"
              onClick={() => onViewChange("report")}
              className={`rounded-full px-2.5 py-1 text-xs font-medium transition md:px-3 ${
                view === "report"
                  ? "bg-accent text-white"
                  : "text-fg-muted hover:text-fg"
              }`}
            >
              Report
            </button>
          </div>

          <span
            className={`hidden rounded-full border px-2.5 py-1 text-xs font-medium lg:inline ${qualityClass(qualityCode)}`}
          >
            {quality}
          </span>

          <span className="hidden items-center gap-1 rounded-full border border-edge bg-surface/80 px-2 py-1 text-xs text-fg-muted sm:inline-flex">
            {status === "connected" ? (
              <WifiHigh size={12} className="text-accent" />
            ) : (
              <WifiSlash size={12} className="text-warning" />
            )}
            <span className="hidden md:inline">{statusLabel(status)}</span>
          </span>

          <ThemeToggle theme={theme} onToggle={onThemeToggle} />

          {view === "live" &&
            controlsEnabled &&
            (paused ? (
              <button
                type="button"
                onClick={onResume}
                className="inline-flex items-center gap-1 rounded-full bg-accent px-2.5 py-1.5 text-xs font-medium text-white transition active:scale-[0.98] md:gap-2 md:px-4 md:py-2 md:text-sm"
              >
                <Play size={14} weight="fill" className="md:hidden" />
                <Play size={16} weight="fill" className="hidden md:block" />
                <span className="hidden sm:inline">Resume</span>
              </button>
            ) : (
              <button
                type="button"
                onClick={onPause}
                className="inline-flex items-center gap-1 rounded-full border border-edge bg-surface px-2.5 py-1.5 text-xs font-medium text-fg transition active:scale-[0.98] md:gap-2 md:px-4 md:py-2 md:text-sm"
              >
                <Pause size={14} weight="fill" className="md:hidden" />
                <Pause size={16} weight="fill" className="hidden md:block" />
                <span className="hidden sm:inline">Pause</span>
              </button>
            ))}

          <button
            type="button"
            onClick={handleStop}
            disabled={!controlsEnabled}
            className="inline-flex items-center gap-1 rounded-full border border-danger/30 bg-danger/10 px-2.5 py-1.5 text-xs font-medium text-danger transition active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50 md:gap-2 md:px-3 md:py-2 md:text-sm"
          >
            <Stop size={14} weight="fill" className="md:hidden" />
            <Stop size={16} weight="fill" className="hidden md:block" />
            <span className="hidden sm:inline">Stop</span>
          </button>
        </div>
      </div>
    </header>
  );
}
