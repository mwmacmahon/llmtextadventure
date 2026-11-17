import { useEffect, useRef, useState } from "react";
import { scratchInfo, scratchTemplate, streamScratch, type ScratchDone, type ScratchInfo, type ScratchRequest } from "../api";
import { formatExchange, parseExchange, type Role } from "../scratchText";

const ROLE_ORDER = ["narrator", "assistant", "referee", "summarizer"];
type Mode = "conversation" | "chat" | "raw";
type Msg = { id: number; role: Role; content: string };
let nextId = 1;
const msg = (role: Role, content: string): Msg => ({ id: nextId++, role, content });

/** The scratch pad (D326): the GPU box's model with no game around it, in dev mode on a local server.
 *  Conversation (the default): a system text and messages, every one an editable box, the model's replies too.
 *  Chat: a system text and one user message, the reply under it. Raw: the model continues the box's own text.
 *  Everything lives in this page's memory only: Clear or a reload and it is gone; the server keeps nothing but a count. */
export function ScratchPage() {
  const [info, setInfo] = useState<ScratchInfo | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>("conversation");
  const [system, setSystem] = useState("");
  const [messages, setMessages] = useState<Msg[]>([]);
  const [draft, setDraft] = useState("");                         // conversation: the next user message
  const [text, setText] = useState("");                           // chat: the user message; raw: the whole text
  const [reply, setReply] = useState("");                         // chat: the reply, editable
  const [reasoning, setReasoning] = useState("");
  const [preset, setPreset] = useState("custom");
  const [params, setParams] = useState<Record<string, string>>({});
  const [maxTokens, setMaxTokens] = useState(512);
  const [thinking, setThinking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<ScratchDone | null>(null);
  const [before, setBefore] = useState<string | null>(null);      // raw: the text before the last generation or wrap, for Undo
  const [paste, setPaste] = useState<string | null>(null);        // the paste box, when the browser will not read the clipboard
  const [copyBox, setCopyBox] = useState<string | null>(null);    // the export shown to copy by hand, when it will not write it
  const abort = useRef<AbortController | null>(null);
  const boxRef = useRef<HTMLTextAreaElement>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const [swapped, setSwapped] = useState<string | null>(null);    // the box's model changed under the page
  const presetRef = useRef(preset);
  presetRef.current = preset;
  const seen = useRef<string | null>(null);                        // the model (and profile) last read from the box

  /** What the box has loaded now: asked on opening, on coming back to the tab and before each call, because the model can be
   *  swapped (another profile) while the page is open. A preset not edited by hand follows the new model's settings. */
  async function refresh(): Promise<ScratchInfo | null> {
    try {
      const i = await scratchInfo();
      setInfo(i);
      const key = `${i.model ?? "?"} / ${i.profile}`;
      if (seen.current === null) {
        const first = ROLE_ORDER.find((r) => i.presets[r]) ?? Object.keys(i.presets)[0];
        if (first) pick(first, i);
      } else if (seen.current !== key) {
        setSwapped(`The box changed from ${seen.current} to ${key}.` + (presetRef.current === "custom" ? " Your custom settings are kept; pick a preset for the new model's." : " The preset now has the new settings."));
        if (presetRef.current !== "custom") pick(presetRef.current, i);
      }
      seen.current = key;
      return i;
    } catch {
      setErr("The scratch pad is only on a server whose model runs on the GPU box, in dev mode.");
      return null;
    }
  }

  useEffect(() => {
    refresh();
    const onFocus = () => { if (!abort.current) refresh(); };
    addEventListener("focus", onFocus);
    return () => {
      removeEventListener("focus", onFocus);
      abort.current?.abort();
    };
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

  /** One call, streamed into `into` piece by piece. Says whether anything came back. */
  async function call(body: Omit<ScratchRequest, "preset" | "params" | "max_tokens" | "thinking">, into: (acc: string) => void): Promise<boolean> {
    const before0 = seen.current;
    if (!(await refresh())) return false;
    if (seen.current !== before0) return false;      // the model changed: say so and let the person look before sending
    setErr(null);
    setDone(null);
    setReasoning("");
    setBusy(true);
    const ctl = new AbortController();
    abort.current = ctl;
    const sent: Record<string, number | null> = {};
    for (const [k, v] of Object.entries(params)) if (v.trim() !== "" && !isNaN(Number(v))) sent[k] = Number(v);
    let acc = "";
    try {
      for await (const ev of streamScratch({ ...body, preset, params: sent, max_tokens: maxTokens, thinking: body.mode !== "raw" && thinking }, ctl.signal)) {
        if (ev.event === "text") {
          acc += ev.data.t;
          into(acc);
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
    return acc.length > 0;
  }

  /** Conversation: the draft (if any) joins as a user message, then the model's reply streams into a new assistant box. */
  async function converse(base: Msg[] = messages) {
    const turns = draft.trim() ? [...base, msg("user", draft)] : base;
    if (!turns.length || turns[turns.length - 1].role !== "user") {
      setErr("The last message is the model's. Write a user message below, or use Regenerate.");
      return;
    }
    const answer = msg("assistant", "");
    setMessages([...turns, answer]);
    setDraft("");
    const set = (acc: string) => {
      setMessages((ms) => ms.map((m) => (m.id === answer.id ? { ...m, content: acc } : m)));
      requestAnimationFrame(() => endRef.current?.scrollIntoView({ block: "end" }));
    };
    const got = await call({ mode: "conversation", text: "", system, messages: turns.map(({ role, content }) => ({ role, content })) }, set);
    if (!got) setMessages((ms) => ms.filter((m) => m.id !== answer.id));   // nothing came: no empty box left behind
  }

  function regenerate() {
    const last = messages[messages.length - 1];
    if (!last || last.role !== "assistant") return;
    converse(messages.slice(0, -1));
  }

  async function generate() {
    if (busy) return;
    if (mode === "conversation") return converse();
    if (!text.trim()) return;
    if (mode === "chat") {
      setReply("");
      await call({ mode: "chat", text, system, messages: [] }, setReply);
      return;
    }
    const start = text;
    setBefore(start);
    await call({ mode: "raw", text, system: "", messages: [] }, (acc) => {
      setText(start + acc);
      requestAnimationFrame(() => boxRef.current && (boxRef.current.scrollTop = boxRef.current.scrollHeight));
    });
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

  /** Chat: the message and its reply carried on as a conversation. */
  function toConversation() {
    const ms = [msg("user", text), ...(reply ? [msg("assistant", reply)] : [])];
    setMessages(ms);
    setText("");
    setReply("");
    setMode("conversation");
  }

  // ---- export and import: one text blob <-> the boxes (src/scratchText.ts has the format) -----------------------------
  function exported(): string {
    if (mode === "raw") return text;
    const ms = mode === "conversation"
      ? [...messages, ...(draft.trim() ? [msg("user", draft)] : [])]
      : [...(text ? [msg("user", text)] : []), ...(reply ? [msg("assistant", reply)] : [])];
    return formatExchange({ system, messages: ms.map(({ role, content }) => ({ role, content })) });
  }

  async function exportClip() {
    const blob = exported();
    try {
      await navigator.clipboard.writeText(blob);
      setNote("Copied to the clipboard.");
    } catch {
      setCopyBox(blob);            // the browser refused (a page not on https): shown to copy by hand
    }
  }

  async function importClip() {
    try {
      take(await navigator.clipboard.readText());
    } catch {
      setPaste("");                // the browser refused: a box to paste into
    }
  }

  function take(blob: string) {
    setPaste(null);
    const x = parseExchange(blob);
    if (x) {
      setSystem(x.system);
      setMessages(x.messages.map((m) => msg(m.role, m.content)));
      setDraft("");
      setMode("conversation");
      setNote(`Imported ${x.messages.length} message${x.messages.length === 1 ? "" : "s"}${x.system ? " and a system text" : ""}.`);
    } else if (mode === "conversation") {
      setDraft(blob);
      setNote("No ### headers in it: put in the next user message.");
    } else {
      setText(blob);
      setNote("Imported as the text.");
    }
  }

  function clear() {
    abort.current?.abort();
    setMessages([]);
    setDraft("");
    setText("");
    setReply("");
    setReasoning("");
    setDone(null);
    setBefore(null);
    setErr(null);
    setNote(null);
  }

  const keyGo = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      generate();
    }
  };

  if (!info) return <div className="lobby">{err ?? "loading…"}</div>;
  const presetNames = [...Object.keys(info.presets)].sort((a, b) => rank(a) - rank(b));
  const last = messages[messages.length - 1];
  const canGo = mode === "conversation" ? !!draft.trim() || last?.role === "user" : !!text.trim();
  return (
    <div className="lobby scratch-page">
      <h1>Scratch pad</h1>
      <p className="muted small">
        The model loaded on the GPU box now, <strong>{info.model ?? "(the box did not say)"}</strong> (profile {info.profile}
        {info.slot_ctx ? `, ${info.slot_ctx.toLocaleString()} tokens a slot` : ""}; prompts up to {info.max_prompt.toLocaleString()} tokens), with no game around it, on the side slot (slot {info.slot}; the narrator, assistant and referee are on slots 0 to 2 and keep their caches).
        Nothing is kept: Clear or a reload and it is gone. {info.busy && <strong>The box is busy with a turn just now; a call will share it.</strong>}
      </p>
      {err && <div className="error">{err}</div>}
      {swapped && (
        <div className="error">
          {swapped} <button className="link small" onClick={() => setSwapped(null)}>dismiss</button>
        </div>
      )}

      <section className="settings">
        <div className="settings-row">
          <label>
            <input type="radio" checked={mode === "conversation"} onChange={() => setMode("conversation")} disabled={busy} /> Conversation: messages back and forth, every one editable
          </label>
          <label>
            <input type="radio" checked={mode === "chat"} onChange={() => setMode("chat")} disabled={busy} /> Chat: a system text and one user message, as the roles call it
          </label>
          <label>
            <input type="radio" checked={mode === "raw"} onChange={() => setMode("raw")} disabled={busy} /> Raw: the model continues the text, no chat template
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

      <textarea className="scratch-system scratch-grow" rows={2} value={system} onChange={(e) => setSystem(e.target.value)} disabled={busy}
        placeholder={mode === "raw" ? "System text (optional; used only by Wrap in template)" : "System text (optional)"} />

      {mode === "conversation" && (
        <div className="scratch-thread">
          {messages.map((m, i) => (
            <div key={m.id} className={`scratch-msg scratch-${m.role}`}>
              <div className="scratch-msg-head small">
                <button className="link small" disabled={busy} title="Switch this message between user and model"
                  onClick={() => setMessages((ms) => ms.map((x) => (x.id === m.id ? { ...x, role: x.role === "user" ? "assistant" : "user" } : x)))}>
                  {m.role === "user" ? "user" : "model"}
                </button>
                <span className="spacer" />
                <button className="link small" disabled={busy} title="Delete this message" onClick={() => setMessages((ms) => ms.filter((x) => x.id !== m.id))}>delete</button>
              </div>
              <textarea className="scratch-grow" value={m.content} readOnly={busy && i === messages.length - 1}
                onChange={(e) => setMessages((ms) => ms.map((x) => (x.id === m.id ? { ...x, content: e.target.value } : x)))} />
            </div>
          ))}
          <div className="scratch-msg scratch-user scratch-draft">
            <div className="scratch-msg-head small muted">next user message</div>
            <textarea className="scratch-grow" rows={3} value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={keyGo}
              placeholder={messages.length ? "Your next message. Ctrl+Enter sends; empty sends the conversation as it stands." : "Your first message. Ctrl+Enter sends."} />
          </div>
          <div ref={endRef} />
        </div>
      )}

      {mode !== "conversation" && (
        <textarea ref={boxRef} className="scratch-box" value={text} onChange={(e) => setText(e.target.value)} readOnly={busy}
          placeholder={mode === "raw" ? "Text for the model to continue. Ctrl+Enter generates." : "The user message. Ctrl+Enter generates."}
          onKeyDown={keyGo} />
      )}

      <div className="settings-row scratch-actions">
        {busy ? <button onClick={() => abort.current?.abort()}>Stop</button> : <button className="primary" onClick={generate} disabled={!canGo}>{mode === "conversation" ? "Send" : "Generate"}</button>}
        {mode === "conversation" && <button onClick={regenerate} disabled={busy || last?.role !== "assistant"} title="Ask again for the last reply">Regenerate</button>}
        {mode === "raw" && <button onClick={wrap} disabled={busy || !text.trim()} title="Put the text (and the system text) in the model's own chat template, ending where its reply begins; then Generate">Wrap in template</button>}
        {mode === "raw" && <button onClick={() => { if (before !== null) { setText(before); setBefore(null); } }} disabled={busy || before === null} title="The text as it was before the last generation or wrap">Undo</button>}
        {mode === "chat" && reply && !busy && <button onClick={toConversation} title="Carry this message and its reply on as a conversation">Continue as conversation</button>}
        <button onClick={exportClip} disabled={busy} title="The system text and messages as one text (### headers), to the clipboard">Export</button>
        <button onClick={importClip} disabled={busy} title="Text with ### system / ### user / ### assistant headers (or a JSON message list) from the clipboard, into the boxes">Import</button>
        <button onClick={clear}>Clear</button>
        <span className="spacer" />
        {done && (
          <span className="muted small">
            prompt {done.prompt_tokens ?? "?"}{done.cached ? ` (${done.cached} cached)` : ""} · wrote {done.new_tokens ?? 0}
            {done.per_second ? ` · ${done.per_second.toFixed(1)} tok/s` : ""} · {(done.ms / 1000).toFixed(1)} s · {done.stop}
          </span>
        )}
      </div>
      {note && <div className="muted small">{note} <button className="link small" onClick={() => setNote(null)}>dismiss</button></div>}

      {paste !== null && (
        <div className="settings">
          <div className="small">This browser will not read the clipboard here. Paste below, then Import.</div>
          <textarea className="scratch-grow" rows={6} autoFocus value={paste} onChange={(e) => setPaste(e.target.value)} />
          <div className="settings-row">
            <button className="primary" onClick={() => take(paste)} disabled={!paste.trim()}>Import</button>
            <button onClick={() => setPaste(null)}>Cancel</button>
          </div>
        </div>
      )}
      {copyBox !== null && (
        <div className="settings">
          <div className="small">This browser will not write to the clipboard here. The text is selected: copy it (Cmd+C).</div>
          <textarea className="scratch-grow" rows={6} readOnly autoFocus value={copyBox} onFocus={(e) => e.currentTarget.select()} />
          <div className="settings-row"><button onClick={() => setCopyBox(null)}>Close</button></div>
        </div>
      )}

      {reasoning && (
        <details className="scratch-reasoning">
          <summary className="muted small">thinking ({reasoning.length} characters)</summary>
          <pre>{reasoning}</pre>
        </details>
      )}
      {mode === "chat" && (reply || busy) && (
        <div className="scratch-msg scratch-assistant">
          <div className="scratch-msg-head small muted">model</div>
          <textarea className="scratch-grow" value={reply || (busy ? "…" : "")} readOnly={busy} onChange={(e) => setReply(e.target.value)} />
        </div>
      )}
    </div>
  );
}

function rank(n: string) {
  return ROLE_ORDER.includes(n) ? ROLE_ORDER.indexOf(n) : ROLE_ORDER.length;
}
