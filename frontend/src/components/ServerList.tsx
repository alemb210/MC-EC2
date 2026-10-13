import { useEffect, useState } from "react";
import { listServers } from "../api";
import ServerCard from "./ServerCard";

export default function ServerList() {
  const [servers, setServers] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listServers()
      .then(setServers)
      .catch((e: Error) => setError(e.message));
  }, []);

  if (error) return <p className="error">Couldn't load servers: {error}</p>;
  if (!servers) return <p className="muted">Loading servers…</p>;
  if (servers.length === 0) {
    return (
      <p className="muted">
        No servers configured. Set <code>DEMO_SERVERS</code> in <code>.env</code>, or
        use <code>MOCK_MODE=true</code> for demo servers.
      </p>
    );
  }

  return (
    <div className="grid">
      {servers.map((id) => <ServerCard key={id} serverId={id} />)}
    </div>
  );
}
