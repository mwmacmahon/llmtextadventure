// Dev-only page (/plan-demo.html): the planner panels (docs/PLANNER-CONTRACT.md) on web/fixtures/plan_sample.json, with
// every command a panel would send listed below instead of sent. Not part of the build's pages.
import React, { useState } from "react";
import ReactDOM from "react-dom/client";
import sample from "../fixtures/plan_sample.json";
import type { CardsWidget, ChartWidget, ProfileWidget, RosterWidget } from "./api";
import { ChartPanel } from "./components/ChartPanel";
import { CardsPanel } from "./components/CardsPanel";
import { ProfilePanel, RosterPanel } from "./components/DetailView";
import "./styles.css";

function Demo() {
  const [sent, setSent] = useState<string[]>([]);
  const log = (c: string, a: Record<string, unknown>) => setSent((s) => [`${c} ${JSON.stringify(a)}`, ...s].slice(0, 12));
  return (
    <div style={{ padding: 16, display: "grid", gap: 16, gridTemplateColumns: "minmax(0, 1fr) 320px", alignItems: "start" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
        <h2 style={{ margin: 0 }}>Planner demo</h2>
        <ChartPanel widget={sample.chart as unknown as ChartWidget} onCommand={log} />
        <CardsPanel widget={sample.cards as unknown as CardsWidget} onCommand={log} />
        <ProfilePanel widget={sample.profile as unknown as ProfileWidget} onCommand={log} />
        <div>
          <h3>Sent</h3>
          <pre id="sent" className="small" style={{ whiteSpace: "pre-wrap" }}>{sent.join("\n") || "(nothing yet)"}</pre>
        </div>
      </div>
      <div className="side" style={{ border: "1px solid var(--border)" }}>
        <RosterPanel widget={sample.roster as unknown as RosterWidget} onCommand={log} />
      </div>
    </div>
  );
}
ReactDOM.createRoot(document.getElementById("root")!).render(<React.StrictMode><Demo /></React.StrictMode>);
