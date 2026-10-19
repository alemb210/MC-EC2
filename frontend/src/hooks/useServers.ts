import { useCallback, useEffect, useRef, useState } from "react";
import { describeError, listServers } from "../api";
import { withRecovery, type AuthSession } from "../recovery";

// The caller's server IDs from GET /servers; add() shows a newly created one without a reload.
export function useServers(session: AuthSession | null) {
  const [ids, setIds] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const sessionRef = useRef(session);
  sessionRef.current = session;

  const load = useCallback(async () => {
    setError(null);
    try {
      const servers = await withRecovery(listServers, sessionRef.current, {
        onWaking: () => setNotice("Waking up the database…"),
      });
      setIds(servers.map((s) => s.server_id));
    } catch (e) {
      setError(describeError(e));
    } finally {
      setNotice(null);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const add = useCallback((id: string) => setIds((prev) => [...new Set([...(prev ?? []), id])]), []);

  return { ids, error, notice, reload: load, add };
}
