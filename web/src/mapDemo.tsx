// Dev-only page (/map-demo.html): the map panel on web/fixtures/map_sample.json, at the side panel's width and at a phone's,
// with what a click would put in the input box shown below. Not part of the build's pages.
import React, { useState } from "react";
import ReactDOM from "react-dom/client";
import sample from "../fixtures/map_sample.json";
import type { MapWidget } from "./api";
import { MapPanel } from "./components/MapPanel";
import { checkArt } from "./components/mapArt";
import "./styles.css";

const problems = checkArt();

function Demo() {
  const [picked, setPicked] = useState<string>("(nothing yet)");
  const [w, setW] = useState<MapWidget>(sample as unknown as MapWidget);
  return (
    <div style={{ padding: 16, maxWidth: 900 }}>
      <h2>Map demo</h2>
      {problems.length > 0 && <pre style={{ color: "var(--bad)" }}>{problems.join("\n")}</pre>}
      <p className="small">
        Input box would hold: <code id="picked">{picked}</code>{" "}
        <button className="link small" onClick={() => setW({ ...w, player: { x: w.player.x + 1, y: w.player.y - 1 } })}>move player (new turn)</button>
      </p>
      <div style={{ display: "flex", gap: 24, flexWrap: "wrap", alignItems: "flex-start" }}>
        <div className="side" style={{ width: 340, border: "1px solid var(--border)" }}><MapPanel widget={w} onPick={setPicked} /></div>
        <div className="side" style={{ width: 375, border: "1px solid var(--border)" }}><MapPanel widget={w} onPick={setPicked} /></div>
      </div>
    </div>
  );
}
ReactDOM.createRoot(document.getElementById("root")!).render(<React.StrictMode><Demo /></React.StrictMode>);
