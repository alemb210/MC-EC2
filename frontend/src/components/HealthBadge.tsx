import { useEffect, useState } from "react";
import { getHealth } from "../api";

type Mode = "loading" | "mock" | "live" | "offline";

const LABELS: Record<Mode, string> = {
  loading: "Checking API…",
  mock: "Mock mode",
  live: "Live AWS",
  offline: "API offline",
};

export default function HealthBadge() {
  const [mode, setMode] = useState<Mode>("loading");

  useEffect(() => {
    getHealth()
      .then((h) => setMode(h.mock_mode ? "mock" : "live"))
      .catch(() => setMode("offline"));
  }, []);

  return <span className={`badge ${mode}`}>{LABELS[mode]}</span>;
}
