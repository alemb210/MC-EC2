import { useCallback, useEffect, useRef, useState } from "react";
import { describeError, listServers, type ServerSummary } from "../api";
import { withRecovery, type AuthSession } from "../recovery";

// Refresh from the database after creation; ignore replies from older requests.
export function useServers(session: AuthSession | null) {
  const [servers, setServers] = useState<ServerSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const sessionRef = useRef(session);
  sessionRef.current = session;
  const latest = useRef(0);

  const load = useCallback(async () => {
    const seq = ++latest.current;
    setError(null);
    try {
      const servers = await withRecovery(listServers, sessionRef.current, {
        onWaking: () => { if (seq === latest.current) setNotice("Waking up the database…"); },
      });
      if (seq === latest.current) setServers(servers);
    } catch (e) {
      if (seq === latest.current) setError(describeError(e));
    } finally {
      if (seq === latest.current) setNotice(null);
    }
  }, []);

  useEffect(() => {
    void load();
    return () => { latest.current++; };
  }, [load]);

  return { servers, error, notice, reload: load };
}
