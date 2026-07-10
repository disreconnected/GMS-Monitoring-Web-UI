import type { ConnectionStatus } from "../types/monitor";

type DisconnectedBannerProps = {
  status: ConnectionStatus;
};

export function DisconnectedBanner({ status }: DisconnectedBannerProps) {
  if (status === "connected") return null;

  let message: string;
  if (status === "auth_error") {
    message =
      "Unauthorized. Open the dashboard using the secure URL printed by the server at startup.";
  } else if (status === "connecting") {
    message = "Connecting to monitor backend...";
  } else {
    message = "Connection lost. Reconnecting to live data...";
  }

  return (
    <div className="sticky top-[88px] z-30 border-b border-warning/30 bg-warning/15 px-4 py-3 text-center text-sm text-fg">
      {message}
    </div>
  );
}
