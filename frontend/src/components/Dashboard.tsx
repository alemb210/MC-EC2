import type { AuthSession } from "../recovery";
import ServerCard from "./ServerCard";

// Server IDs come from config until the API has a GET /servers.
export default function Dashboard({ serverIds, session }: { serverIds: string[]; session: AuthSession | null }) {
  if (serverIds.length === 0) {
    return <p className="muted">No servers configured. Set <code>VITE_SERVER_IDS</code> in <code>frontend/.env.local</code>.</p>;
  }
  return (
    <div className="grid">
      {serverIds.map((id) => <ServerCard key={id} serverId={id} session={session} />)}
    </div>
  );
}
