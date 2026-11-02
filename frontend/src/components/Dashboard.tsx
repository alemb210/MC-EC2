import { useState } from "react";
import { useServers } from "../hooks/useServers";
import type { AuthSession } from "../recovery";
import CreateServer from "./CreateServer";
import ServerCard from "./ServerCard";

// Lists the caller's servers from GET /servers. Creating needs a session, so mock mode has no button.
export default function Dashboard({ session }: { session: AuthSession | null }) {
  const [filter, setFilter] = useState<"all" | "owned" | "shared">("all");
  const { servers, error, notice, reload } = useServers(session);
  const refreshList = () => { void reload(); };
  // Only the caller's own unfinished server can be resumed; POST /servers never touches one they administer.
  const resume = servers?.some((s) => s.role === "owner" && !s.has_instance) ?? false;
  const isDuplicate = (name: string) => (servers ?? []).filter((s) => s.name === name).length > 1;
  const shown = servers?.filter((s) => filter === "all" || s.role === (filter === "owned" ? "owner" : "admin"));

  return (
    <>
      <div className="dashboard-heading"><div><p className="eyebrow">WORKSPACE / YOUR SERVERS</p><h1>Your servers</h1><p className="muted">Good worlds are worth coming back to.</p></div></div>
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
      {servers && servers.length > 0 && <nav className="server-filters" aria-label="Filter servers">
        <button aria-current={filter === "all" ? "page" : undefined} onClick={() => setFilter("all")}>All servers <span>{servers.length}</span></button>
        <button aria-current={filter === "owned" ? "page" : undefined} onClick={() => setFilter("owned")}>Owned <span>{servers.filter((s) => s.role === "owner").length}</span></button>
        <button aria-current={filter === "shared" ? "page" : undefined} onClick={() => setFilter("shared")}>Shared <span>{servers.filter((s) => s.role === "admin").length}</span></button>
      </nav>}
      {shown && shown.length > 0 && (
        <div className="grid">
          {shown.map((s) => (
            <ServerCard key={s.server_id} serverId={s.server_id} name={s.name} role={s.role} version={s.minecraft_version}
                        showId={isDuplicate(s.name)} session={session} onChanged={refreshList} />
          ))}
        </div>
      )}
      {servers && servers.length > 0 && shown?.length === 0 && <p className="empty">No {filter} servers.</p>}
      <p className="dashboard-tip">Your world stays while your server rests. Start a few minutes before you play.</p>
    </>
  );
}
