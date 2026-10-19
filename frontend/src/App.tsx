import Dashboard from "./components/Dashboard";
import LiveApp from "./components/LiveApp";
import Shell from "./components/Shell";
import { cognitoConfigured } from "./config";
import { useHealth } from "./hooks/useHealth";

// /health decides the mode, so the UI always matches the backend it is talking to.
export default function App() {
  const mode = useHealth();

  if (mode === "loading") {
    return <Shell mode={mode}><p className="muted">Checking API…</p></Shell>;
  }
  if (mode === "offline") {
    return <Shell mode={mode}><p className="error">API offline</p></Shell>;
  }
  if (mode === "mock") {
    return <Shell mode={mode}><Dashboard session={null} /></Shell>;
  }
  if (!cognitoConfigured) {
    return (
      <Shell mode={mode}>
        <p className="error">
          Cognito isn't configured. Copy <code>frontend/.env.example</code> to <code>frontend/.env.local</code> and fill it in.
        </p>
      </Shell>
    );
  }
  return <LiveApp mode={mode} />;
}
