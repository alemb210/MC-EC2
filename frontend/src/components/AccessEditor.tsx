import { useCallback, useEffect, useRef, useState } from "react";
import { accessPayload, parsePlayers, playersProblem } from "../access";
import { getAccess, updateAccess, type AccessMode, type AccessSettings } from "../api";
import { useServerAction } from "../hooks/useServerAction";
import type { AuthSession } from "../recovery";
import AccessFields from "./AccessFields";

const APPLIED_MESSAGE = {
  applying: "Saved. The server is updating now.",
  on_next_start: "Saved. It will apply the next time the server starts.",
};

const sameSettings = (a: AccessSettings, b: AccessSettings) =>
  a.mode === b.mode && a.players.join("\n") === b.players.join("\n");

// Stays mounted while hidden, so closing the panel doesn't lose unsaved edits. Works while the
// server is stopped: settings are saved separately and the server applies them when it boots.
export default function AccessEditor({ serverId, session, visible, onGone }: {
  serverId: string;
  session: AuthSession | null;
  visible: boolean;
  onGone?: () => void;
}) {
  const [saved, setSaved] = useState<AccessSettings | null>(null);
  const [mode, setMode] = useState<AccessMode | null>(null);
  const [players, setPlayers] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const load = useServerAction(session, onGone);
  const save = useServerAction(session, onGone);
  const runLoad = load.run;
  // Saved settings arriving late mustn't overwrite what the user has typed since asking for them.
  const edited = useRef(false);

  const apply = useCallback((settings: AccessSettings) => {
    edited.current = false;
    setSaved(settings);
    setMode(settings.mode);
    setPlayers(settings.players.join("\n"));
  }, []);

  const refresh = useCallback(async () => {
    const result = await runLoad((t) => getAccess(serverId, t));
    if (result.ok && !edited.current) apply(result.value);
  }, [apply, runLoad, serverId]);

  // Reopening shows what another admin may have changed, unless there are edits to keep.
  useEffect(() => {
    if (visible && !edited.current) void refresh();
  }, [visible, refresh]);

  const edit = <T,>(setter: (value: T) => void) => (value: T) => {
    edited.current = true;
    setMessage(null);
    save.clearError();
    setter(value);
  };

  const current = mode && accessPayload(mode, players);
  const problem = mode === "whitelist" ? playersProblem(parsePlayers(players)) : null;
  const changed = Boolean(saved && current && !sameSettings(saved, current));

  const onSave = async () => {
    if (!current || problem) return;
    setMessage(null);
    const result = await save.run((t) => updateAccess(serverId, current, t));
    if (result.ok) {
      apply({ mode: result.value.mode, players: result.value.players });
      setMessage(APPLIED_MESSAGE[result.value.applied]);
    }
  };

  if (!visible) return null;

  return (
    <section className="panel">
      {/* Never show a form built on settings that didn't load: saving it would overwrite the real list. */}
      {saved === null && load.busy && <p className="muted">{load.notice ?? "Loading…"}</p>}
      {saved === null && !load.busy && load.error && (
        <>
          <p className="error">{load.error}</p>
          <button type="button" className="secondary" onClick={refresh}>Retry</button>
        </>
      )}
      {saved !== null && (
        <>
          <AccessFields mode={mode} players={players} disabled={save.busy}
                        onMode={edit(setMode)} onPlayers={edit(setPlayers)} />
          <div className="actions">
            <button type="button" onClick={onSave} disabled={save.busy || !changed || Boolean(problem)}>
              {save.busy ? "Saving…" : "Save"}
            </button>
            {changed && (
              <button type="button" className="secondary" disabled={save.busy} onClick={() => { setMessage(null); save.clearError(); apply(saved); }}>
                Discard
              </button>
            )}
          </div>
          {save.notice && <p className="muted">{save.notice}</p>}
          {message && <p className="muted">{message}</p>}
          {save.error && <p className="error">{save.error}</p>}
          {load.error && <p className="error">Couldn't refresh: {load.error}</p>}
        </>
      )}
    </section>
  );
}
