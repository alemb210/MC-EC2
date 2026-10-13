import { useCallback, useEffect, useRef, useState } from "react";
import { getStatus, startServer, stopServer, type ServerStatus } from "../api";

const POLL_MS = 5000;

// Keep polling while AWS or Minecraft is still transitioning.
export function isSettling(s: ServerStatus): boolean {
  return s.instance_state === "pending" || s.instance_state === "stopping" ||
    (s.instance_state === "running" && !s.minecraft_ready);
}

export function useServerStatus(serverId: string) {
  const [status, setStatus] = useState<ServerStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // A slow poll must not overwrite the newer state returned by start/stop.
  const latest = useRef(0);

  const run = useCallback(async (call: () => Promise<ServerStatus>) => {
    const seq = ++latest.current;
    try {
      const next = await call();
      if (seq === latest.current) {
        setStatus(next);
        setError(null);
      }
    } catch (e) {
      if (seq === latest.current) setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const refresh = useCallback(() => run(() => getStatus(serverId)), [run, serverId]);

  const act = useCallback(async (action: "start" | "stop") => {
    setBusy(true);
    await run(() => (action === "start" ? startServer : stopServer)(serverId));
    setBusy(false);
  }, [run, serverId]);

  useEffect(() => { refresh(); }, [refresh]);

  useEffect(() => {
    if (!status || !isSettling(status)) return;
    const timer = setTimeout(refresh, POLL_MS);
    return () => clearTimeout(timer);
  }, [status, refresh]);

  return { status, error, busy, refresh, start: () => act("start"), stop: () => act("stop") };
}
