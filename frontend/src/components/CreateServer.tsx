import { useRef, useState } from "react";
import { createServer, describeError, type ServerCreated } from "../api";
import { withRecovery, type AuthSession } from "../recovery";

export default function CreateServer({ session, onCreated }: {
  session: AuthSession;
  onCreated: (server: ServerCreated) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const sessionRef = useRef(session);
  sessionRef.current = session;

  const onCreate = async () => {
    setBusy(true);
    setError(null);
    setNotice("Launching…");
    try {
      const server = await withRecovery(createServer, sessionRef.current, {
        onWaking: () => setNotice("Waking up the database…"),
      });
      onCreated(server);
      setNotice("Server launched. First boot installs Minecraft and takes a few minutes.");
    } catch (e) {
      setNotice(null);
      setError(describeError(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="create">
      <button onClick={onCreate} disabled={busy}>{busy ? "Creating…" : "Create server"}</button>
      {notice && <p className="muted">{notice}</p>}
      {error && <p className="error">{error}</p>}
    </section>
  );
}
