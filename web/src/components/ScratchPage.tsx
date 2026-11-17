import { useEffect, useRef, useState } from "react";
import { scratchInfo, scratchTemplate, streamScratch, type ScratchDone, type ScratchInfo } from "../api";

const ROLE_ORDER = ["narrator", "assistant", "referee", "summarizer"];

/** The scratch pad (D326): the GPU box's model with no game around it, in dev mode on a local server. Raw: the model continues
 *  the box's own text. Chat: a system text and the box as one user message, the reply under it. Everything lives in this
 *  page's memory only: Clear or a reload and it is gone; the server keeps nothing but a count of tokens. */
export function ScratchPage() {
  const [info, setInfo] = useState<ScratchInfo | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [mode, setMode] = useState<"raw" | "chat">("raw");
  const [text, setText] = useState("");
  const [system, setSystem] = useState("");
  const [reply, setReply] = useState("");
  const [reasoning, setReasoning] = useState("");
  const [preset, setPreset] = useState("custom");
  const [params, setParams] = useState<Record<string, string>>({});
  const [maxTokens, setMaxTokens] = useState(512);
  const [thinking, setThinking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<ScratchDone | null>(null);
  const [before, setBefore] = useState<string | null>(null);     // the box before the last generation, for Undo
  const abort = useRef<AbortController | null>(null);
  const boxRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    scratchInfo()
      .then((i) => {
        setInfo(i);
        const first = ROLE_ORDER.find((r) => i.presets[r]) ?? Object.keys(i.presets)[0];
        if (first) pick(first, i);
      })
      .catch(() => setErr("The scratch pad is only on a server whose model runs on the GPU box, in dev mode."));
    return () => abort.current?.abort();
  }, []);

  function pick(name: string, i: ScratchInfo | null = info) {
    setPreset(name);
    const p = i?.presets[name];
    if (!p) return;
    setParams(Object.fromEntries(Object.entries(p.params).map(([k, v]) => [k, String(v)])));
    setMaxTokens(p.max_tokens);
    setThinking(p.thinking);
  }

  function edit(k: string, v: string) {
    setParams((p) => ({ ...p, [k]: v }));
    setPreset("custom");
  }

  async function generate() {
    if (busy || !text.trim()) return;
    setErr(null);
    setDone(null);
    setReasoning("");
    setBusy(true);
    const ctl = new AbortController();
    abort.current = ctl;
    const sent: Record<string, number | null> = {};
    for (const [k, v] of Object.entries(params)) if (v.trim() !== "" && !isNaN(Number(v))) sent[k] = Number(v);
    const start = text;
    if (mode === "raw") setBefore(start);
    else setReply("");
    let acc = "";
    try {
      for await (const ev of streamScratch({ mode, text, system, preset, params: sent, max_tokens: maxTokens, thinking: mode === "chat" && thinking }, ctl.signal)) {
        if (ev.event === "text") {
          acc += ev.data.t;
          if (mode === "raw") {
            setText(start + acc);
            requestAnimationFrame(() => boxRef.current && (boxRef.current.scrollTop = boxRef.current.scrollHeight));
          } else setReply(acc);
        } else if (ev.event === "reasoning") setReasoning((r) => r + ev.data.t);
        else if (ev.event === "done") setDone(ev.data);
        else if (ev.event === "error") setErr(ev.data.message);
      }
    } catch (e) {
      if (!ctl.signal.aborted) setErr(String(e));
    } finally {
      setBusy(false);
      abort.current = null;
    }
  }

  /** Raw mode: the box (and the system text) put in the loaded model's own chat template, ending where its reply begins, so
   *  Generate continues it as the model's answer. An instruction-tuned model loops in raw text outside it (D326). */
  async function wrap() {
    if (busy || !text.trim()) return;
    setErr(null);
    try {
      const { prompt } = await scratchTemplate(text, system, thinking);
      setBefore(text);
      setText(prompt);
    } catch (e) {
      setErr(String(e));
    }
  }

  function clear() {
    abort.current?.abort();
    setText("");
    setReply("");
    setReasoning("");
    setDone(null);
    setBefore(null);
    setErr(null);
  }

  if (!info) return <div className="lobby">{err ?? "loading…"}</div>;
  const presetNames = [...Object.keys(info.presets)].sort((a, b) => rank(a) - rank(b));
  return (
    <div className="lobby scratch-page">
      <h1>Scratch pad</h1>
      <p className="muted small">
        The model on the GPU box ({info.profile}), with no game around it, on the side slot (slot {info.slot}; the narrator, assistant and referee are on slots 0 to 2 and keep their caches).
        Nothing is kept: Clear or a reload and it is gone. {info.busy && <strong>The box is busy with a turn just now; a call will share it.</strong>}
      </p>
      {err && <div className="error">{err}</div>}

      <section className="settings">
        <div className="settings-row">
          <label>
            <input type="radio" checked={mode === "raw"} onChange={() => setMode("raw")} disabled={busy} /> Raw: the model continues the text, no chat template
          </label>
          <label>
            <input type="radio" checked={mode === "chat"} onChange={() => setMode("chat")} disabled={busy} /> Chat: a system text and one user message, as the roles call it
          </label>
        </div>
        <div className="settings-row">
          <label>
            Preset{" "}
            <select value={preset} onChange={(e) => pick(e.target.value)} disabled={busy}>
              {presetNames.map((n) => <option key={n} value={n}>{n}</option>)}
              <option value="custom">custom</option>
            </select>
          </label>
          <label>
            max tokens <input type="number" className="scratch-num" min={1} max={info.max_new} value={maxTokens} onChange={(e) => { setMaxTokens(Number(e.target.value)); setPreset("custom"); }} />
          </label>
          <label title={mode === "raw" ? "raw mode: whether Wrap opens the model's thinking" : ""}>
            <input type="checkbox" checked={thinking} onChange={(e) => { setThinking(e.target.checked); setPreset("custom"); }} /> thinking
          </label>
        </div>
        <div className="scratch-params">
          {info.samplers.map((k) => (
            <label key={k} title={params[k] ? "" : "empty: the server's own default"}>
              <span className="muted small">{k}</span>
              <input type="text" className="scratch-num" value={params[k] ?? ""} placeholder="default" onChange={(e) => edit(k, e.target.value)} />
            </label>
          ))}
        </div>
      </section>

      <textarea className="scratch-system" rows={3} placeholder={mode === "raw" ? "System text (optional; used only by Wrap in template)" : "System text (optional)"} value={system} onChange={(e) => setSystem(e.target.value)} disabled={busy} />
      <textarea ref={boxRef} className="scratch-box" value={text} onChange={(e) => setText(e.target.value)} readOnly={busy}
        placeholder={mode === "raw" ? "Text for the model to continue. Ctrl+Enter generates." : "The user message. Ctrl+Enter generates."}
        onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); generate(); } }} />
      <div className="settings-row scratch-actions">
        {busy ? <button onClick={() => abort.current?.abort()}>Stop</button> : <button className="primary" onClick={generate} disabled={!text.trim()}>Generate</button>}
        {mode === "raw" && <button onClick={wrap} disabled={busy || !text.trim()} title="Put the text (and the system text) in the model's own chat template, ending where its reply begins; then Generate">Wrap in template</button>}
        {mode === "raw" && <button onClick={() => { if (before !== null) { setText(before); setBefore(null); } }} disabled={busy || before === null} title="The text as it was before the last generation or wrap">Undo</button>}
        <button onClick={clear}>Clear</button>
        <span className="spacer" />
        {done && (
          <span className="muted small">
            prompt {done.prompt_tokens ?? "?"}{done.cached ? ` (${done.cached} cached)` : ""} · wrote {done.new_tokens ?? 0}
            {done.per_second ? ` · ${done.per_second.toFixed(1)} tok/s` : ""} · {(done.ms / 1000).toFixed(1)} s · {done.stop}
          </span>
        )}
      </div>
      {reasoning && (
        <details className="scratch-reasoning">
          <summary className="muted small">thinking ({reasoning.length} characters)</summary>
          <pre>{reasoning}</pre>
        </details>
      )}
      {mode === "chat" && (reply || busy) && <pre className="scratch-reply">{reply || "…"}</pre>}
    </div>
  );
}

function rank(n: string) {
  return ROLE_ORDER.includes(n) ? ROLE_ORDER.indexOf(n) : ROLE_ORDER.length;
}
