import { useCallback, useRef, useState } from "react";
import { describeError, isServerGone } from "../api";
import { withRecovery, type AuthSession } from "../recovery";

export type ActionResult<T> = { ok: true; value: T } | { ok: false };

// One-at-a-time API calls for a form or button: tracks progress and errors, ignores double
// submits, and reports a server that no longer exists (deleted, or the caller was removed).
export function useServerAction(session: AuthSession | null, onGone?: () => void) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const sessionRef = useRef(session);
  sessionRef.current = session;
  const onGoneRef = useRef(onGone);
  onGoneRef.current = onGone;
  const inFlight = useRef(false);

  const run = useCallback(async <T>(
    call: (token?: string) => Promise<T>,
    describe: (e: unknown) => string = describeError,
  ): Promise<ActionResult<T>> => {
    if (inFlight.current) return { ok: false };
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      const value = await withRecovery(call, sessionRef.current, {
        onWaking: () => setNotice("Waking up the database…"),
      });
      return { ok: true, value };
    } catch (e) {
      setError(describe(e));
      if (isServerGone(e)) onGoneRef.current?.();
      return { ok: false };
    } finally {
      inFlight.current = false;
      setBusy(false);
      setNotice(null);
    }
  }, []);

  const clearError = useCallback(() => setError(null), []);

  return { busy, error, notice, run, clearError };
}
