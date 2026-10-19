import { useServers } from "../hooks/useServers";
import type { AuthSession } from "../recovery";
import CreateServer from "./CreateServer";
import ServerCard from "./ServerCard";

// Lists the caller's servers from GET /servers. Creating needs a session, so mock mode has no button.
export default function Dashboard({ session }: { session: AuthSession | null }) {
  const { servers, error, notice, reload } = useServers(session);

  return (
    <>
      {session && <CreateServer session={session} resume={servers?.some((s) => !s.has_instance) ?? false}
                               onCreated={() => { void reload(); }} />}
      {notice && <p className="muted">{notice}</p>}
      {error && (
        <>
          <p className="error">{error}</p>
          <button className="secondary" onClick={reload}>Retry</button>
        </>
      )}
      {servers === null && !error && !notice && <p className="muted">Loading servers…</p>}
      {servers?.length === 0 && <p className="muted">No servers yet.</p>}
      {servers && servers.length > 0 && (
        <div className="grid">
          {servers.map((s) => <ServerCard key={s.server_id} serverId={s.server_id} session={session} />)}
        </div>
      )}
    </>
  );
}
