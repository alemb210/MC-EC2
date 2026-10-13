import HealthBadge from "./components/HealthBadge";
import ServerList from "./components/ServerList";

export default function App() {
  return (
    <main>
      <header className="page-head">
        <h1>Minecraft Servers</h1>
        <HealthBadge />
      </header>
      <ServerList />
    </main>
  );
}
