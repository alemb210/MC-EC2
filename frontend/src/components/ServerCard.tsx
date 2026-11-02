import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { useServerAction } from "../hooks/useServerAction";
import { useServerStatus } from "../hooks/useServerStatus";
import { ApiError, removeAdmin, type Role, type ServerStatus } from "../api";
import type { AuthSession } from "../recovery";
import AccessEditor from "./AccessEditor";
import AdminsPanel from "./AdminsPanel";
import DeleteConfirm from "./DeleteConfirm";
import RenameForm from "./RenameForm";

type Panel = "general" | "access" | "admins" | "delete";

function minecraftLabel(s: ServerStatus): string {
  if (s.minecraft_ready) return "Ready";
  return s.instance_state === "running" ? "Minecraft starting…" : "—";
}

function serverStateLabel(s: ServerStatus | null): string {
  if (!s) return "Loading…";
  if (s.provisioning_state === "awaiting_instance") return "Awaiting instance";
  switch (s.instance_state) {
    case "running": return s.minecraft_ready ? "Ready to join" : "Starting Minecraft";
    case "pending": return "Starting server";
    case "stopping": return "Stopping";
    case "stopped": return "Stopped";
    case "shutting-down": return "Shutting down";
    case "terminated": return "Terminated";
    default: return "Status unavailable";
  }
}

export function autoStopLabel(s: ServerStatus, now = Date.now()): string | null {
  if (!s.auto_stop_at || s.instance_state !== "running") return null;
  const stopsAt = Date.parse(s.auto_stop_at);
  if (Number.isNaN(stopsAt)) return null;
  const minutes = Math.ceil((stopsAt - now) / 60000);
  return minutes > 0 ? `Stops in ${minutes} min if nobody joins` : "Stopping soon because nobody is playing";
}

export default function ServerCard({ serverId, name, role, version, showId = false, session, onChanged }: {
  serverId: string;
  name?: string;
  role?: Role;
  version?: string | null;
  // Names don't have to be unique, so servers sharing one also show part of their ID.
  showId?: boolean;
  session: AuthSession | null;
  // Called when the server list needs reloading: renamed, removed, or gone from under this card.
  onChanged?: () => void;
}) {
  const { status, error, notice, busy, refresh, start, stop } = useServerStatus(serverId, session, onChanged);
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState<string | null>(null);
  const [panel, setPanel] = useState<Panel>("general");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const hasOpened = useRef(false);
  // Mounted on first open, then kept so closing the panel doesn't lose unsaved edits.
  const [accessOpened, setAccessOpened] = useState(false);
  const [renaming, setRenaming] = useState(false);
  // What the user just saved, shown until the reloaded list catches up.
  const [renamed, setRenamed] = useState<string | null>(null);
  const [removed, setRemoved] = useState(false);
  const leave = useServerAction(session);

  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(timer);
  }, [copied]);

  // A new name from the list wins, including one another admin chose.
  useEffect(() => setRenamed(null), [name]);

  useEffect(() => {
    if (settingsOpen) {
      hasOpened.current = true;
      dialogRef.current?.querySelector<HTMLElement>("[data-close-settings]")?.focus();
    } else if (hasOpened.current) triggerRef.current?.focus();
  }, [settingsOpen]);

  const state = status?.instance_state;
  const awaitingInstance = status?.provisioning_state === "awaiting_instance";
  const address = status?.connection_address ?? null;
  const displayName = renamed ?? name;
  // The API sends a server's ID as its name until it's given a custom one.
  const unnamed = displayName === undefined || displayName === serverId;
  const online = status?.players_online ?? 0;
  const autoStop = status && autoStopLabel(status);

  // The list reload removes this card, but it can fail or take a moment, so don't leave a dead card behind.
  const onRemoved = () => {
    setRemoved(true);
    onChanged?.();
  };

  if (removed) return null;

  const onStop = () => {
    if (online > 0 && !window.confirm(`${online} player(s) online. Stop the server anyway?`)) return;
    stop();
  };

  const onLeave = async () => {
    if (!window.confirm(`Stop being an admin of "${displayName}"? You'll lose access to it.`)) return;
    const result = await leave.run(async (t) => {
      try {
        await removeAdmin(serverId, "me", t);
      } catch (e) {
        // Already removed, or the server was deleted: either way there's nothing left to leave.
        if (!(e instanceof ApiError && e.status === 404)) throw e;
      }
    });
    if (result.ok) onRemoved();
  };

  const togglePanel = (next: Panel) => {
    if (next === "access") setAccessOpened(true);
    setPanel(next);
  };

  const onDialogKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") { event.stopPropagation(); setSettingsOpen(false); return; }
    if (event.key !== "Tab") return;
    const focusable = [...(dialogRef.current?.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), a[href]') ?? [])];
    if (!focusable.length) return;
    const first = focusable[0], last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  };

  const onCopy = async () => {
    if (!address) return;
    try {
      await navigator.clipboard.writeText(address);
      setCopyError(null);
      setCopied(true);
    } catch {
      setCopyError("Couldn't copy. Select the address manually.");
    }
  };

  return (
    <article className="card">
      <header className="card-head">
        <h2>
          {unnamed ? <code>{serverId}</code> : displayName}
          {showId && <code className="server-id"> {serverId.slice(0, 8)}</code>}
          {role === "admin" && <span className="shared">Admin</span>}
        </h2>
        <span className={`state ${state ?? ""}`}>{serverStateLabel(status)}</span>
      </header>

      {status && (
        <dl>
          <dt>Minecraft</dt> <dd>{minecraftLabel(status)}</dd>
          <dt>Address</dt>
          <dd className="address">
            {address ? <code>{address}</code> : "Available when running"}
            <button className="link" onClick={onCopy} disabled={!address}>
              {copied ? "Copied" : "Copy"}
            </button>
          </dd>
          <dt>Players</dt>
          <dd>{status.players_online !== null ? `${status.players_online} / ${status.players_max}` : "—"}</dd>
          <dt>Version</dt> <dd>{status.minecraft_version ?? version ?? "—"}</dd>
        </dl>
      )}

      <div className="actions card-actions">
        {state === "running" ? <button onClick={onStop} disabled={busy || !status?.minecraft_ready}>Stop</button> : <button onClick={start} disabled={busy || state !== "stopped"}>Start</button>}
        {role && <button className="secondary" ref={triggerRef} aria-haspopup="dialog" aria-expanded={settingsOpen} onClick={() => { setPanel("general"); setSettingsOpen(true); }}>Manage</button>}
        <button className="secondary" onClick={refresh} disabled={busy}>Refresh</button>
      </div>
      {role && (
        <div className="settings-overlay" hidden={!settingsOpen}
             onMouseDown={(event) => { if (event.target === event.currentTarget) setSettingsOpen(false); }}>
          <div className="settings-drawer" ref={dialogRef} role="dialog" aria-modal="true"
               aria-label={`${displayName} settings`} onKeyDown={onDialogKeyDown}>
            <header className="drawer-top">
              <div>
                <p className="eyebrow">SERVER SETTINGS</p>
                <h2>{displayName}</h2>
                <p className="muted">{role === "owner" ? "You own this server." : "You're an admin on this server."}</p>
              </div>
              <button data-close-settings className="secondary" aria-label="Close settings"
                      onClick={() => setSettingsOpen(false)}>✕</button>
            </header>
            <nav className="settings-tabs" aria-label="Server settings">
              <button aria-current={panel === "general" ? "page" : undefined} onClick={() => togglePanel("general")}>General</button>
              <button aria-current={panel === "access" ? "page" : undefined} onClick={() => togglePanel("access")}>Player access</button>
              {role === "owner" && <button aria-current={panel === "admins" ? "page" : undefined} onClick={() => togglePanel("admins")}>Admins</button>}
            </nav>
            <div className="settings-content">
              {panel === "general" && (
                <>
                  <h3>A familiar name.</h3>
                  <p>Make it easy for your group to find its world.</p>
                  {renaming && displayName !== undefined ? (
                    <RenameForm serverId={serverId} name={unnamed ? "" : displayName} session={session}
                                onGone={onChanged} onCancel={() => setRenaming(false)}
                                onRenamed={(next) => { setRenamed(next); setRenaming(false); onChanged?.(); }} />
                  ) : <button className="secondary" onClick={() => setRenaming(true)}>Rename</button>}
                  <dl><dt>Your role</dt><dd>{role === "owner" ? "Owner" : "Admin"}</dd>
                    <dt>Minecraft</dt><dd>{status?.minecraft_version ?? version ?? "—"}</dd></dl>
                  <div className="danger-zone">
                    <h3>{role === "owner" ? "Delete server" : "Leave this server"}</h3>
                    <p>{role === "owner" ? "Permanently delete this server and its world. This cannot be undone." : "Remove yourself as an admin and lose access to its controls."}</p>
                    {role === "owner" ? <button className="danger" onClick={() => togglePanel("delete")}>Delete</button>
                      : <button className="danger" disabled={leave.busy} onClick={onLeave}>{leave.busy ? "Leaving…" : "Leave"}</button>}
                  </div>
                </>
              )}
              {accessOpened && <div hidden={panel !== "access"}>
                <h3>Choose your company.</h3>
                <p>Player access controls who joins in Minecraft. It does not grant server control.</p>
                <AccessEditor serverId={serverId} session={session} visible={settingsOpen && panel === "access"} onGone={onChanged} />
              </div>}
              {panel === "admins" && role === "owner" && <>
                <h3>Share the controls.</h3>
                <p>Admins can start, stop, rename, and manage player access. Only the owner can manage admins or delete.</p>
                <AdminsPanel serverId={serverId} session={session} onGone={onChanged} />
              </>}
              {panel === "delete" && role === "owner" && displayName !== undefined &&
                <DeleteConfirm serverId={serverId} name={unnamed ? serverId.slice(0, 8) : displayName}
                               playersOnline={online} session={session} onDeleted={onRemoved}
                               onCancel={() => togglePanel("general")} />}
              {leave.error && <p className="error">{leave.error}</p>}
            </div>
            <div className="drawer-bottom">Settings apply to this server only.</div>
          </div>
        </div>
      )}

      {autoStop && <p className="muted">{autoStop}</p>}
      {awaitingInstance && (
        <p className="muted">
          {role === "admin"
            ? "Creation has not finished. The server's owner can resume it."
            : "Creation has not finished. Use Resume creation to retry the existing server."}
        </p>
      )}
      {(notice || leave.notice) && <p className="muted">{notice ?? leave.notice}</p>}
      {(error || copyError) && <p className="error">{error ?? copyError}</p>}
    </article>
  );
}
