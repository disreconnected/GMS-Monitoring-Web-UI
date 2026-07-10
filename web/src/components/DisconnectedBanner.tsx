import type { ConnectionStatus } from "../types/monitor";

type DisconnectedBannerProps = {
  status: ConnectionStatus;
  isStale: boolean;
  lastUpdatedAt: number | null;
  shutdownError: string | null;
};

function formatUpdatedAt(timestamp: number | null): string {
  if (!timestamp) return "unknown";
  return new Date(timestamp * 1000).toLocaleTimeString();
}

export function DisconnectedBanner({
  status,
  isStale,
  lastUpdatedAt,
  shutdownError,
}: DisconnectedBannerProps) {
  if (shutdownError) {
    return (
      <div className="sticky top-[88px] z-30 border-b border-danger/30 bg-danger/15 px-4 py-3 text-center text-sm text-fg">
        {shutdownError}
      </div>
    );
  }

  if (status === "connected" && !isStale) return null;

  let message: string;
  if (status === "auth_error") {
    message =
      "Unauthorized. Open the secure URL printed at server startup or enter the access token.";
  } else if (status === "origin_error") {
    message = "Connection blocked by origin policy. Use the dashboard URL from this server.";
  } else if (status === "client_limit") {
    message = "Too many dashboard connections are open. Close another tab and retry.";
  } else if (status === "connecting") {
    message = "Connecting to monitor backend...";
  } else if (isStale) {
    message = `Showing stale data from ${formatUpdatedAt(lastUpdatedAt)}. Reconnecting...`;
  } else {
    message = "Connection lost. Reconnecting to live data...";
  }

  return (
    <div className="sticky top-[88px] z-30 border-b border-warning/30 bg-warning/15 px-4 py-3 text-center text-sm text-fg">
      {message}
    </div>
  );
}
