import { useServers } from "../hooks/useServers";
import type { AuthSession } from "../recovery";
import CreateServer from "./CreateServer";
import ServerCard from "./ServerCard";

// Lists the caller's servers from GET /servers. Creating needs a session, so mock mode has no button.
export default function Dashboard({ session }: { session: AuthSession | null }) {
  const { ids, error, notice, reload, add } = useServers(session);

  return (
    <>
      {session && <CreateServer session={session} onCreated={(server) => add(server.server_id)} />}
      {notice && <p className="muted">{notice}</p>}
      {error && (
        <>
          <p className="error">{error}</p>
          <button className="secondary" onClick={reload}>Retry</button>
        </>
      )}
      {ids === null && !error && !notice && <p className="muted">Loading servers…</p>}
      {ids?.length === 0 && <p className="muted">No servers yet.</p>}
      {ids && ids.length > 0 && (
        <div className="grid">
          {ids.map((id) => <ServerCard key={id} serverId={id} session={session} />)}
        </div>
      )}
    </>
  );
}
