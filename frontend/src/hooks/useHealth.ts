import { useEffect, useState } from "react";
import { getHealth } from "../api";

export type Mode = "loading" | "mock" | "live" | "offline";

export function useHealth(): Mode {
  const [mode, setMode] = useState<Mode>("loading");

  useEffect(() => {
    getHealth()
      .then((h) => setMode(h.mock_mode ? "mock" : "live"))
      .catch(() => setMode("offline"));
  }, []);

  return mode;
}
