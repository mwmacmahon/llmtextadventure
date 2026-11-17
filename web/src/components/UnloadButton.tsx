import { useState } from "react";
import { unloadModel } from "../api";

/** Unload the model on the GPU box now (D327), instead of waiting out llama-server's 10-minute idle sleep; the next request
 *  loads it again by itself (about 10 seconds). Dev mode, a server playing on the box. Needs the game's llama.cpp patch
 *  (docs/LLAMA-SLEEP-PATCH.md): a build without it answers with what to do, shown here. */
export function UnloadButton({ onDone, sleeping }: { onDone?: () => void; sleeping?: boolean | null }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  async function go() {
    setBusy(true);
    setMsg(null);
    try {
      setMsg((await unloadModel()).message);
      onDone?.();
    } catch (e) {
      setMsg((e instanceof Error ? e.message : String(e)).replace(/^\d+ \{"detail":"(.*)"\}$/, "$1"));
    } finally {
      setBusy(false);
    }
  }
  return (
    <span className="unload">
      <button onClick={go} disabled={busy || sleeping === true}
        title="Free the GPU now instead of after 10 idle minutes; the next request loads the model again (about 10 s)">
        {busy ? "unloading…" : sleeping ? "unloaded" : "Unload model"}
      </button>
      {msg && <span className="muted small"> {msg}</span>}
    </span>
  );
}
