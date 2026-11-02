import { useServers } from "../hooks/useServers";
import type { AuthSession } from "../recovery";
import CreateServer from "./CreateServer";
import ServerCard from "./ServerCard";

// Lists the caller's servers from GET /servers. Creating needs a session, so mock mode has no button.
export default function Dashboard({ session }: { session: AuthSession | null }) {
  const { servers, error, notice, reload } = useServers(session);
  const refreshList = () => { void reload(); };
  // Only the caller's own unfinished server can be resumed; POST /servers never touches one they administer.
  const resume = servers?.some((s) => s.role === "owner" && !s.has_instance) ?? false;
  const isDuplicate = (name: string) => (servers ?? []).filter((s) => s.name === name).length > 1;

  return (
    <>
      {session && <CreateServer session={session} resume={resume} onCreated={refreshList} />}
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
          {servers.map((s) => (
            <ServerCard key={s.server_id} serverId={s.server_id} name={s.name} role={s.role}
                        showId={isDuplicate(s.name)} session={session} onChanged={refreshList} />
          ))}
        </div>
      )}
    </>
  );
}
