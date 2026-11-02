import { useRef, useState, type FormEvent } from "react";
import { accessPayload, parsePlayers, playersProblem } from "../access";
import { createServer, describeError, type AccessMode, type ServerCreated } from "../api";
import { withRecovery, type AuthSession } from "../recovery";
import AccessFields from "./AccessFields";
import { MAX_NAME_LENGTH } from "./RenameForm";

export default function CreateServer({ session, onCreated, resume = false }: {
  session: AuthSession;
  onCreated: (server: ServerCreated) => void;
  resume?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [mode, setMode] = useState<AccessMode | null>(null);
  const [players, setPlayers] = useState("");
  const sessionRef = useRef(session);
  sessionRef.current = session;

  const problem = mode === "whitelist" ? playersProblem(parsePlayers(players)) : null;
  // Resuming keeps the name and access saved by the first attempt, so it doesn't ask again.
  const ready = resume || (mode !== null && !problem);

  const onCreate = async (e: FormEvent) => {
    e.preventDefault();
    if (busy || !ready) return;
    setBusy(true);
    setError(null);
    setNotice("Launching…");
    try {
      // If the first attempt failed before saving, values still on this form are saved now.
      const access = mode ? accessPayload(mode, players) : undefined;
      const server = await withRecovery((t) => createServer(t, { name: name.trim() || undefined, access }), sessionRef.current, {
        onWaking: () => setNotice("Waking up the database…"),
      });
      onCreated(server);
      setName("");
      setMode(null);
      setPlayers("");
      setNotice("Server launched. First boot installs Minecraft and takes a few minutes.");
    } catch (err) {
      setNotice(null);
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="create" onSubmit={onCreate}>
      {!resume && (
        <>
          <label className="field">
            Server name
            <input value={name} maxLength={MAX_NAME_LENGTH} placeholder="Minecraft server" disabled={busy}
                   onChange={(e) => setName(e.target.value)} />
          </label>
          <AccessFields mode={mode} players={players} disabled={busy} onMode={setMode} onPlayers={setPlayers} />
        </>
      )}
      <button disabled={busy || !ready}>{busy ? "Creating…" : resume ? "Resume creation" : "Create server"}</button>
      {!resume && mode === null && <p className="muted">Choose who can join to continue.</p>}
      {notice && <p className="muted">{notice}</p>}
      {error && <p className="error">{error}</p>}
    </form>
  );
}
