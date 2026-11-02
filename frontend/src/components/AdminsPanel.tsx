import { useCallback, useEffect, useState, type FormEvent } from "react";
import { addAdmin, ApiError, describeError, isServerGone, listAdmins, removeAdmin, type ServerAdmin } from "../api";
import { useServerAction } from "../hooks/useServerAction";
import type { AuthSession } from "../recovery";

// Mirror backend/service.py and backend/models.py, so a mistake is explained before anything is sent.
export const MAX_ADMINS = 5;
const EMAIL = /^[^@\s"\\]+@[^@\s"\\]+$/;

// A 404 here means no account has that email, which the API's own message explains.
const describeAddError = (e: unknown) =>
  e instanceof ApiError && e.status === 404 && !isServerGone(e) ? e.detail : describeError(e);

// For the server's owner. Adding takes effect immediately, with no invite to accept.
export default function AdminsPanel({ serverId, session, onGone }: {
  serverId: string;
  session: AuthSession | null;
  onGone?: () => void;
}) {
  const [admins, setAdmins] = useState<ServerAdmin[] | null>(null);
  const [email, setEmail] = useState("");
  const [added, setAdded] = useState<string | null>(null);
  const load = useServerAction(session, onGone);
  const change = useServerAction(session, onGone);
  const runLoad = load.run;

  const refresh = useCallback(async () => {
    const result = await runLoad((t) => listAdmins(serverId, t));
    if (result.ok) setAdmins(result.value);
  }, [runLoad, serverId]);

  useEffect(() => { void refresh(); }, [refresh]);

  const address = email.trim();
  const validEmail = EMAIL.test(address) && address.length <= 254;
  const full = (admins?.length ?? 0) >= MAX_ADMINS;

  const onAdd = async (e: FormEvent) => {
    e.preventDefault();
    if (!validEmail || full) return;
    setAdded(null);
    const result = await change.run((t) => addAdmin(serverId, address, t), describeAddError);
    if (result.ok) {
      const admin = result.value;
      // Adding an existing admin changes nothing on the server, so it mustn't add a second row here.
      setAdmins((list) => [...(list ?? []).filter((a) => a.user_id !== admin.user_id), admin]);
      setEmail("");
      setAdded(`${admin.email} is now an admin. The server will appear on their dashboard.`);
    }
  };

  const onRemove = async (admin: ServerAdmin) => {
    setAdded(null);
    const result = await change.run(async (t) => {
      try {
        await removeAdmin(serverId, admin.user_id, t);
      } catch (e) {
        // Already removed, perhaps from another tab or because they left: the result is what was asked for.
        if (!(e instanceof ApiError && e.status === 404 && !isServerGone(e))) throw e;
      }
    });
    if (result.ok) setAdmins((list) => (list ?? []).filter((a) => a.user_id !== admin.user_id));
  };

  return (
    <section className="panel">
      <p className="muted">Admins can start, stop and rename this server, and manage who can join.</p>
      {admins === null && load.busy && <p className="muted">{load.notice ?? "Loading…"}</p>}
      {admins === null && !load.busy && load.error && (
        <>
          <p className="error">{load.error}</p>
          <button type="button" className="secondary" onClick={refresh}>Retry</button>
        </>
      )}
      {admins !== null && (
        <>
          {admins.length === 0 && <p className="muted">No admins yet.</p>}
          {admins.length > 0 && (
            <ul className="admins">
              {admins.map((a) => (
                <li key={a.user_id}>
                  <span>{a.email}</span>
                  <button type="button" className="link" disabled={change.busy} onClick={() => onRemove(a)}>Remove</button>
                </li>
              ))}
            </ul>
          )}
          {full ? (
            <p className="muted">This server has the maximum of {MAX_ADMINS} admins.</p>
          ) : (
            <form onSubmit={onAdd} noValidate>
              <label className="field">
                Add by email
                <input type="email" value={email} autoComplete="off" disabled={change.busy}
                       placeholder="friend@example.com"
                       onChange={(e) => { setEmail(e.target.value); setAdded(null); change.clearError(); }} />
              </label>
              <button disabled={change.busy || !validEmail}>{change.busy ? "Adding…" : "Add admin"}</button>
              <p className="muted">They need a confirmed account on this site.</p>
            </form>
          )}
        </>
      )}
      {change.notice && <p className="muted">{change.notice}</p>}
      {added && <p className="muted">{added}</p>}
      {change.error && <p className="error">{change.error}</p>}
    </section>
  );
}
