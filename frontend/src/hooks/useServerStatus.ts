import { useCallback, useEffect, useRef, useState } from "react";
import {
  describeError, getStatus, startServer, statusFromAction, stopServer, type ServerStatus,
} from "../api";
import { withRecovery, type AuthSession } from "../recovery";

const POLL_MS = 5000;

// Keep polling while AWS or Minecraft is still transitioning.
export function isSettling(s: ServerStatus): boolean {
  return s.instance_state === "pending" || s.instance_state === "stopping" ||
    (s.instance_state === "running" && !s.minecraft_ready);
}

export function useServerStatus(serverId: string, session: AuthSession | null) {
  const [status, setStatus] = useState<ServerStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // A slow poll must not overwrite the newer state returned by start/stop.
  const latest = useRef(0);
  // The session object is rebuilt every render; keep the newest one without re-running effects.
  const sessionRef = useRef(session);
  sessionRef.current = session;

  const run = useCallback(async (call: (token?: string) => Promise<ServerStatus>) => {
    const seq = ++latest.current;
    try {
      const next = await withRecovery(call, sessionRef.current, {
        onWaking: () => seq === latest.current && setNotice("Waking up the database…"),
      });
      if (seq === latest.current) {
        setStatus(next);
        setError(null);
      }
    } catch (e) {
      if (seq === latest.current) setError(describeError(e));
    } finally {
      if (seq === latest.current) setNotice(null);
    }
  }, []);

  const refresh = useCallback(() => run((t) => getStatus(serverId, t)), [run, serverId]);

  const act = useCallback(async (action: "start" | "stop") => {
    setBusy(true);
    const fn = action === "start" ? startServer : stopServer;
    await run(async (t) => statusFromAction(await fn(serverId, t)));
    setBusy(false);
  }, [run, serverId]);

  useEffect(() => { refresh(); }, [refresh]);

  useEffect(() => {
    if (!status || !isSettling(status)) return;
    const timer = setTimeout(refresh, POLL_MS);
    return () => clearTimeout(timer);
  }, [status, refresh]);

  return { status, error, notice, busy, refresh, start: () => act("start"), stop: () => act("stop") };
}
