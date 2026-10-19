import { useEffect, useState } from "react";
import { useServerStatus } from "../hooks/useServerStatus";
import type { ServerStatus } from "../api";
import type { AuthSession } from "../recovery";

function minecraftLabel(s: ServerStatus): string {
  if (s.minecraft_ready) return "Ready";
  return s.instance_state === "running" ? "Minecraft starting…" : "—";
}

export default function ServerCard({ serverId, session }: { serverId: string; session: AuthSession | null }) {
  const { status, error, notice, busy, refresh, start, stop } = useServerStatus(serverId, session);
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState<string | null>(null);

  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(timer);
  }, [copied]);

  const state = status?.instance_state;
  const awaitingInstance = status?.provisioning_state === "awaiting_instance";
  const address = status?.connection_address ?? null;

  const onStop = () => {
    const online = status?.players_online ?? 0;
    if (online > 0 && !window.confirm(`${online} player(s) online. Stop the server anyway?`)) return;
    stop();
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
        <h2><code>{serverId}</code></h2>
        <span className={`state ${state ?? ""}`}>{awaitingInstance ? "Awaiting instance" : state ?? "loading…"}</span>
      </header>

      {status && (
        <dl>
          <dt>Minecraft</dt> <dd>{minecraftLabel(status)}</dd>
          <dt>Address</dt>
          <dd className="address">
            {address ? <code>{address}</code> : "—"}
            <button className="link" onClick={onCopy} disabled={!address}>
              {copied ? "Copied" : "Copy"}
            </button>
          </dd>
          <dt>Players</dt>
          <dd>{status.players_online !== null ? `${status.players_online} / ${status.players_max}` : "—"}</dd>
          <dt>Version</dt> <dd>{status.minecraft_version ?? "—"}</dd>
        </dl>
      )}

      <div className="actions">
        <button onClick={start} disabled={busy || state !== "stopped"}>Start</button>
        <button onClick={onStop} disabled={busy || state !== "running"}>Stop</button>
        <button className="secondary" onClick={refresh} disabled={busy}>Refresh</button>
      </div>

      {awaitingInstance && <p className="muted">Creation has not finished. Use Resume creation to retry the existing server.</p>}
      {notice && <p className="muted">{notice}</p>}
      {(error || copyError) && <p className="error">{error ?? copyError}</p>}
    </article>
  );
}
