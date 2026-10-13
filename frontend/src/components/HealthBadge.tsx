import type { Mode } from "../hooks/useHealth";

const LABELS: Record<Mode, string> = {
  loading: "Checking API…",
  mock: "Mock mode",
  live: "Live AWS",
  offline: "API offline",
};

export default function HealthBadge({ mode }: { mode: Mode }) {
  return <span className={`badge ${mode}`}>{LABELS[mode]}</span>;
}
