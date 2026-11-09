import { useState, type FormEvent } from "react";
import { ApiError, deleteServer, isServerGone } from "../api";
import { useServerAction } from "../hooks/useServerAction";
import type { AuthSession } from "../recovery";

// Deleting destroys the world and its backups for good, so the owner types the name.
export default function DeleteConfirm({ serverId, name, playersOnline, session, onDeleted, onCancel }: {
  serverId: string;
  name: string;
  playersOnline: number;
  session: AuthSession | null;
  onDeleted: () => void;
  onCancel: () => void;
}) {
  const [typed, setTyped] = useState("");
  // A gone server is what was asked for (perhaps deleted from another tab), so it isn't reported as a failure.
  const { busy, error, notice, run } = useServerAction(session);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (typed.trim() !== name) return;
    const result = await run(async (t) => {
      try {
        await deleteServer(serverId, t);
      } catch (err) {
        if (!(err instanceof ApiError && isServerGone(err))) throw err;
      }
    });
    if (result.ok) onDeleted();
  };

  return (
    <form className="panel" onSubmit={onSubmit}>
      <p className="error">This permanently deletes the server, its world, and all of its backups. It can't be undone.</p>
      {playersOnline > 0 && <p className="error">{playersOnline} player(s) are online right now.</p>}
      <label className="field">
        Type <strong>{name}</strong> to confirm
        <input value={typed} autoFocus autoComplete="off" disabled={busy} onChange={(e) => setTyped(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Escape" && !busy) onCancel(); }} />
      </label>
      <div className="actions">
        <button className="danger" disabled={busy || typed.trim() !== name}>{busy ? "Deleting…" : "Delete forever"}</button>
        <button type="button" className="secondary" disabled={busy} onClick={onCancel}>Cancel</button>
      </div>
      {notice && <p className="muted">{notice}</p>}
      {error && <p className="error">{error}</p>}
    </form>
  );
}
