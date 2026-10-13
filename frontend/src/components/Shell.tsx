import type { ReactNode } from "react";
import type { Mode } from "../hooks/useHealth";
import HealthBadge from "./HealthBadge";

export default function Shell({ mode, account, children }: { mode: Mode; account?: ReactNode; children: ReactNode }) {
  return (
    <main>
      <header className="page-head">
        <h1>Minecraft Servers</h1>
        <div className="head-right">
          {account}
          <HealthBadge mode={mode} />
        </div>
      </header>
      {children}
    </main>
  );
}
