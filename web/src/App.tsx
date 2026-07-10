import { useState } from "react";
import { TopBar } from "./components/TopBar";
import { DisconnectedBanner } from "./components/DisconnectedBanner";
import { HeroSection } from "./components/HeroSection";
import { AlertTicker } from "./components/AlertTicker";
import { BentoCharts } from "./components/BentoCharts";
import { TracerouteStack } from "./components/TracerouteStack";
import { RecentPingsTable } from "./components/RecentPingsTable";
import { SessionDetailPanel } from "./components/SessionDetailPanel";
import { AlertHistoryPanel } from "./components/AlertHistoryPanel";
import { ReportView } from "./components/ReportView";
import { TokenEntryPanel } from "./components/TokenEntryPanel";
import { useMonitorSocket } from "./hooks/useMonitorSocket";
import { useTheme } from "./hooks/useTheme";
import type { AppView } from "./types/monitor";

function StatusFooter({ snapshot }: { snapshot: ReturnType<typeof useMonitorSocket>["snapshot"] }) {
  if (!snapshot) return null;

  const uptime = snapshot.session.total_sent;
  const recv = snapshot.session.total_recv;
  const loss =
    uptime > 0 ? (((uptime - recv) / uptime) * 100).toFixed(1) : "0.0";

  return (
    <footer className="border-t border-edge px-4 py-16 md:px-8">
      <div className="mx-auto flex max-w-7xl flex-col gap-6 md:flex-row md:items-end md:justify-between">
        <div>
          <h2 className="text-2xl font-medium text-fg">Session status</h2>
          <p className="mt-2 text-fg-muted">
            {recv} of {uptime} pings received. Session loss {loss}%.
          </p>
        </div>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
          <div>
            <p className="font-mono text-xl text-fg">{uptime}</p>
            <p className="text-sm text-fg-muted">Packets sent</p>
          </div>
          <div>
            <p className="font-mono text-xl text-fg">{recv}</p>
            <p className="text-sm text-fg-muted">Packets received</p>
          </div>
          <div>
            <p className="font-mono text-xl text-fg">
              {snapshot.session.max_consecutive_rto}
            </p>
            <p className="text-sm text-fg-muted">Max consecutive timeouts</p>
          </div>
        </div>
      </div>
    </footer>
  );
}

function StoppedOverlay() {
  return (
    <div className="flex min-h-[100dvh] flex-col items-center justify-center bg-bg px-4 text-center">
      <h1 className="text-2xl font-medium text-fg">Server stopped</h1>
      <p className="mt-3 max-w-md text-fg-muted">
        The GMS monitoring web server has been shut down. Run{" "}
        <code className="rounded bg-surface px-2 py-0.5 font-mono text-sm text-accent">
          run_gms_web.bat
        </code>{" "}
        to start it again.
      </p>
    </div>
  );
}

export default function App() {
  const {
    snapshot,
    status,
    stopped,
    isStale,
    lastUpdatedAt,
    shutdownError,
    needsToken,
    pause,
    resume,
    rerunTraceroute,
    stopServer,
    submitToken,
  } = useMonitorSocket();
  const { theme, toggleTheme } = useTheme();
  const [view, setView] = useState<AppView>("live");
  const controlsEnabled = status === "connected";

  if (needsToken) {
    return <TokenEntryPanel onSubmit={submitToken} />;
  }

  if (stopped) {
    return <StoppedOverlay />;
  }

  const topBar = (
    <TopBar
      snapshot={snapshot}
      status={status}
      view={view}
      theme={theme}
      controlsEnabled={controlsEnabled}
      onViewChange={setView}
      onThemeToggle={toggleTheme}
      onPause={pause}
      onResume={resume}
      onStop={stopServer}
    />
  );

  if (view === "report") {
    return (
      <main className="flex h-[100dvh] w-full max-w-full flex-col overflow-hidden bg-bg text-fg">
        {topBar}
        <DisconnectedBanner
          status={status}
          isStale={isStale}
          lastUpdatedAt={lastUpdatedAt}
          shutdownError={shutdownError}
        />
        <ReportView snapshot={snapshot} isStale={isStale} />
      </main>
    );
  }

  return (
    <main className="overflow-x-hidden w-full max-w-full bg-bg text-fg">
      {topBar}
      <DisconnectedBanner
        status={status}
        isStale={isStale}
        lastUpdatedAt={lastUpdatedAt}
        shutdownError={shutdownError}
      />
      <HeroSection snapshot={snapshot} status={status} isStale={isStale} />
      <AlertTicker alerts={snapshot?.alerts ?? []} />
      <BentoCharts snapshot={snapshot} isStale={isStale} />
      <section className="px-4 py-12 md:px-8">
        <div className="mx-auto grid max-w-7xl grid-cols-1 gap-4 md:grid-cols-2">
          <RecentPingsTable pingHistory={snapshot?.ping_history ?? []} />
          <SessionDetailPanel session={snapshot?.session ?? null} />
        </div>
      </section>
      <section className="px-4 pb-12 md:px-8">
        <div className="mx-auto max-w-7xl">
          <AlertHistoryPanel alertLog={snapshot?.alert_log ?? []} />
        </div>
      </section>
      <TracerouteStack
        snapshot={snapshot}
        controlsEnabled={controlsEnabled}
        onRerun={rerunTraceroute}
      />
      <StatusFooter snapshot={snapshot} />
    </main>
  );
}
