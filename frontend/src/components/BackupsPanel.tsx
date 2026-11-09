import { useCallback, useEffect, useState } from "react";
import { listBackups, restoreBackup, type Backup, type Role, type ServerStatus } from "../api";
import { useServerAction } from "../hooks/useServerAction";
import type { AuthSession } from "../recovery";

const when = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

// Backups are listed for owners and admins. Only the owner can restore one, and only while stopped.
export default function BackupsPanel({ serverId, role, status, session, onRestoring, onGone }: {
  serverId: string;
  role: Role;
  status: ServerStatus | null;
  session: AuthSession | null;
  onRestoring: () => void;
  onGone?: () => void;
}) {
  const [backups, setBackups] = useState<Backup[] | null>(null);
  const load = useServerAction(session, onGone);
  const restore = useServerAction(session, onGone);
  const runLoad = load.run;

  const refresh = useCallback(async () => {
    const result = await runLoad((t) => listBackups(serverId, t));
    if (result.ok) setBackups(result.value);
  }, [runLoad, serverId]);

  useEffect(() => { void refresh(); }, [refresh]);

  const restoring = status?.restoring ?? false;
  const canRestore = role === "owner" && status?.instance_state === "stopped" && !restoring;

  const onRestore = async (backup: Backup) => {
    if (!window.confirm(`Replace this world with the backup from ${when(backup.created_at)}? `
      + "Your current world will be saved as a backup first.")) return;
    const result = await restore.run((t) => restoreBackup(serverId, backup.backup_id, t));
    if (result.ok) {
      onRestoring();
      void refresh();
    }
  };

  return (
    <section className="panel">
      {restoring && <p className="muted">Restoring a backup. This can take 20 minutes or more, and the server may start and restart along the way.</p>}
      {!restoring && status?.restore_failed && <p className="error">The last restore didn't finish. Check that your world looks right before playing.</p>}
      {role === "owner" && !restoring && status?.instance_state !== "stopped" && <p className="muted">Stop the server to restore a backup.</p>}
      {role === "admin" && <p className="muted">Only the server's owner can restore a backup.</p>}
      {backups === null && load.busy && <p className="muted">{load.notice ?? "Loading…"}</p>}
      {backups === null && !load.busy && load.error && (
        <>
          <p className="error">{load.error}</p>
          <button type="button" className="secondary" onClick={refresh}>Retry</button>
        </>
      )}
      {backups !== null && backups.length === 0 && <p className="muted">No backups yet. One is saved after each session once the server stops.</p>}
      {backups !== null && backups.length > 0 && (
        <ul className="admins">
          {backups.map((b) => (
            <li key={b.backup_id}>
              <span>
                {when(b.created_at)}
                {b.kind === "pre-restore" && " · Before a restore"}
                {b.state === "pending" && " · Saving…"}
              </span>
              {role === "owner" && (
                <button type="button" className="link" disabled={!canRestore || restore.busy || b.state !== "completed"}
                        aria-label={`Restore backup from ${when(b.created_at)}`} onClick={() => onRestore(b)}>Restore</button>
              )}
            </li>
          ))}
        </ul>
      )}
      {restore.notice && <p className="muted">{restore.notice}</p>}
      {restore.error && <p className="error">{restore.error}</p>}
    </section>
  );
}
