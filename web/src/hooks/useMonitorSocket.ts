import { useCallback, useEffect, useRef, useState } from "react";
import type { ConnectionStatus, MonitorSnapshot } from "../types/monitor";

const WS_URL =
  import.meta.env.VITE_WS_URL ||
  `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/ws`;

type UseMonitorSocketResult = {
  snapshot: MonitorSnapshot | null;
  status: ConnectionStatus;
  stopped: boolean;
  pause: () => void;
  resume: () => void;
  rerunTraceroute: () => void;
  setWindowSize: (size: number) => void;
  stopServer: () => Promise<void>;
};

export function useMonitorSocket(): UseMonitorSocketResult {
  const [snapshot, setSnapshot] = useState<MonitorSnapshot | null>(null);
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const [stopped, setStopped] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<number | null>(null);
  const stoppedRef = useRef(false);

  const send = useCallback((payload: object) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(payload));
    }
  }, []);

  const pause = useCallback(() => send({ action: "pause" }), [send]);
  const resume = useCallback(() => send({ action: "resume" }), [send]);
  const rerunTraceroute = useCallback(() => send({ action: "traceroute" }), [send]);
  const setWindowSize = useCallback(
    (size: number) => send({ action: "set_window", size }),
    [send],
  );

  const stopServer = useCallback(async () => {
    stoppedRef.current = true;
    setStopped(true);
    if (reconnectRef.current) {
      window.clearTimeout(reconnectRef.current);
      reconnectRef.current = null;
    }
    wsRef.current?.close();
    try {
      await fetch("/api/shutdown", { method: "POST" });
    } catch {
      // server may already be stopping
    }
  }, []);

  useEffect(() => {
    let active = true;

    const connect = () => {
      if (!active || stoppedRef.current) return;
      setStatus("connecting");
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!active) return;
        setStatus("connected");
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as MonitorSnapshot;
          setSnapshot(data);
        } catch {
          // ignore malformed payloads
        }
      };

      ws.onclose = () => {
        if (!active) return;
        if (stoppedRef.current) {
          setStatus("disconnected");
          return;
        }
        setStatus("disconnected");
        reconnectRef.current = window.setTimeout(connect, 2000);
      };

      ws.onerror = () => {
        ws.close();
      };
    };

    connect();

    return () => {
      active = false;
      if (reconnectRef.current) {
        window.clearTimeout(reconnectRef.current);
      }
      wsRef.current?.close();
    };
  }, []);

  return {
    snapshot,
    status,
    stopped,
    pause,
    resume,
    rerunTraceroute,
    setWindowSize,
    stopServer,
  };
}
