import { useCallback, useEffect, useRef, useState } from "react";
import type { ConnectionStatus, MonitorSnapshot } from "../types/monitor";
import {
  clearAccessToken,
  getAccessToken,
  setAccessToken,
} from "../utils/accessToken";
import { isMonitorSnapshot } from "../utils/validateSnapshot";

const WS_BASE =
  import.meta.env.VITE_WS_URL ||
  `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/ws`;

const WS_APP_PROTOCOL = "gms-monitoring";
const WS_TOKEN_PREFIX = "gms-token.";
const TOKEN_HEADER = "X-GMS-Token";

type UseMonitorSocketResult = {
  snapshot: MonitorSnapshot | null;
  status: ConnectionStatus;
  stopped: boolean;
  isStale: boolean;
  lastUpdatedAt: number | null;
  shutdownError: string | null;
  needsToken: boolean;
  pause: () => void;
  resume: () => void;
  rerunTraceroute: () => void;
  setWindowSize: (size: number) => void;
  stopServer: () => Promise<void>;
  submitToken: (token: string) => void;
};

function buildWebSocketProtocols(token: string): string[] {
  return [WS_APP_PROTOCOL, `${WS_TOKEN_PREFIX}${token}`];
}

function mapCloseReason(code: number, reason: string): ConnectionStatus {
  if (code === 1008) {
    const normalized = reason.toLowerCase();
    if (normalized.includes("origin")) return "origin_error";
    if (normalized.includes("too many")) return "client_limit";
    return "auth_error";
  }
  return "disconnected";
}

export function useMonitorSocket(): UseMonitorSocketResult {
  const [snapshot, setSnapshot] = useState<MonitorSnapshot | null>(null);
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const [stopped, setStopped] = useState(false);
  const [isStale, setIsStale] = useState(false);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<number | null>(null);
  const [shutdownError, setShutdownError] = useState<string | null>(null);
  const [needsToken, setNeedsToken] = useState(() => !getAccessToken());
  const [connectNonce, setConnectNonce] = useState(0);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<number | null>(null);
  const stoppedRef = useRef(false);
  const policyFailedRef = useRef(false);
  const connectingRef = useRef(false);

  const controlsEnabled = status === "connected";

  const send = useCallback(
    (payload: object) => {
      if (!controlsEnabled) return;
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(payload));
      }
    },
    [controlsEnabled],
  );

  const pause = useCallback(() => send({ action: "pause" }), [send]);
  const resume = useCallback(() => send({ action: "resume" }), [send]);
  const rerunTraceroute = useCallback(() => send({ action: "traceroute" }), [send]);
  const setWindowSize = useCallback(
    (size: number) => send({ action: "set_window", size }),
    [send],
  );

  const submitToken = useCallback((token: string) => {
    setAccessToken(token);
    policyFailedRef.current = false;
    setNeedsToken(false);
    setShutdownError(null);
    setConnectNonce((value) => value + 1);
  }, []);

  const stopServer = useCallback(async () => {
    const token = getAccessToken();
    if (!token) {
      setShutdownError("Missing access token.");
      return;
    }

    setShutdownError(null);
    if (reconnectRef.current) {
      window.clearTimeout(reconnectRef.current);
      reconnectRef.current = null;
    }
    wsRef.current?.close();

    try {
      const response = await fetch("/api/shutdown", {
        method: "POST",
        headers: { [TOKEN_HEADER]: token },
      });
      if (!response.ok) {
        const detail = (await response.json().catch(() => null)) as
          | { detail?: string }
          | null;
        setShutdownError(detail?.detail ?? `Shutdown failed (${response.status}).`);
        setConnectNonce((value) => value + 1);
        return;
      }
      stoppedRef.current = true;
      setStopped(true);
      setStatus("disconnected");
    } catch {
      setShutdownError("Shutdown request failed.");
      setConnectNonce((value) => value + 1);
    }
  }, []);

  useEffect(() => {
    let active = true;

    const connect = () => {
      if (!active || stoppedRef.current || policyFailedRef.current || connectingRef.current) {
        return;
      }

      const token = getAccessToken();
      if (!token) {
        setNeedsToken(true);
        setStatus("auth_error");
        return;
      }

      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }

      connectingRef.current = true;
      setStatus("connecting");
      const ws = new WebSocket(WS_BASE, buildWebSocketProtocols(token));
      wsRef.current = ws;

      ws.onopen = () => {
        connectingRef.current = false;
        if (!active) return;
        setStatus("connected");
        setIsStale(false);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (!isMonitorSnapshot(data)) return;
          setSnapshot(data);
          setLastUpdatedAt(data.timestamp);
          setIsStale(false);
        } catch {
          // ignore malformed payloads
        }
      };

      ws.onclose = (event) => {
        connectingRef.current = false;
        if (!active) return;
        if (stoppedRef.current) {
          setStatus("disconnected");
          return;
        }

        const nextStatus = mapCloseReason(event.code, event.reason || "");
        if (nextStatus === "auth_error") {
          clearAccessToken();
          policyFailedRef.current = true;
          setNeedsToken(true);
        } else if (nextStatus !== "disconnected") {
          policyFailedRef.current = true;
        }

        setStatus(nextStatus);
        setIsStale(true);

        if (nextStatus === "disconnected") {
          reconnectRef.current = window.setTimeout(connect, 2000);
        }
      };

      ws.onerror = () => {
        ws.close();
      };
    };

    connect();

    return () => {
      active = false;
      connectingRef.current = false;
      if (reconnectRef.current) {
        window.clearTimeout(reconnectRef.current);
      }
      wsRef.current?.close();
    };
  }, [connectNonce]);

  return {
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
    setWindowSize,
    stopServer,
    submitToken,
  };
}
