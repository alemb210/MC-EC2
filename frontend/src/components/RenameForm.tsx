import { useState, type FormEvent } from "react";
import { renameServer } from "../api";
import { useServerAction } from "../hooks/useServerAction";
import type { AuthSession } from "../recovery";

export const MAX_NAME_LENGTH = 32;

export default function RenameForm({ serverId, name, session, onRenamed, onCancel, onGone }: {
  serverId: string;
  name: string;
  session: AuthSession | null;
  onRenamed: (name: string) => void;
  onCancel: () => void;
  onGone?: () => void;
}) {
  const [draft, setDraft] = useState(name);
  const { busy, error, notice, run, clearError } = useServerAction(session, onGone);
  const next = draft.trim();
  const valid = next.length > 0 && next.length <= MAX_NAME_LENGTH;

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!valid) return;
    if (next === name) return onCancel();
    const result = await run((t) => renameServer(serverId, next, t));
    if (result.ok) onRenamed(result.value.name);
  };

  return (
    <form className="rename" onSubmit={onSubmit}>
      <label className="field">
        Server name
        <input value={draft} maxLength={MAX_NAME_LENGTH} autoFocus disabled={busy}
               onChange={(e) => { setDraft(e.target.value); clearError(); }}
               onKeyDown={(e) => { if (e.key === "Escape") onCancel(); }} />
      </label>
      <div className="actions">
        <button disabled={busy || !valid}>{busy ? "Saving…" : "Save"}</button>
        <button type="button" className="secondary" disabled={busy} onClick={onCancel}>Cancel</button>
      </div>
      {!valid && <p className="error">Enter a name.</p>}
      {notice && <p className="muted">{notice}</p>}
      {error && <p className="error">{error}</p>}
    </form>
  );
}
