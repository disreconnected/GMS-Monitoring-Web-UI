import type { ConnectionStatus } from "../types/monitor";

type DisconnectedBannerProps = {
  status: ConnectionStatus;
};

export function DisconnectedBanner({ status }: DisconnectedBannerProps) {
  if (status === "connected") return null;

  return (
    <div className="sticky top-[88px] z-30 border-b border-warning/30 bg-warning/15 px-4 py-3 text-center text-sm text-fg">
      {status === "connecting"
        ? "Connecting to monitor backend..."
        : "Connection lost. Reconnecting to live data..."}
    </div>
  );
}
