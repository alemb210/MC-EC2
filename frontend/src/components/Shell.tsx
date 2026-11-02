import type { ReactNode } from "react";
import type { Mode } from "../hooks/useHealth";
import HealthBadge from "./HealthBadge";

export default function Shell({ mode, account, onBrandClick, children }: { mode: Mode; account?: ReactNode; onBrandClick?: () => void; children: ReactNode }) {
  return (
    <main>
      <header className="page-head">
        <a className="brand" href="/" aria-label="MCWorldControl home" onClick={onBrandClick ? (event) => { event.preventDefault(); onBrandClick(); } : undefined}><span className="brand-mark" aria-hidden="true">▰</span>MC<span>WorldControl</span></a>
        <div className="head-right">
          {account}
          <HealthBadge mode={mode} />
        </div>
      </header>
      {children}
      <footer className="site-footer">MCWorldControl <span>Your world. On your schedule.</span></footer>
    </main>
  );
}
