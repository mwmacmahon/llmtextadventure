import { useCallback, useEffect, useRef, useState } from "react";
import { api, streamTurn, type InstanceView, type Mechanics, type TranscriptRow } from "./api";
import { DebugDrawer } from "./components/DebugDrawer";
import { Lobby } from "./components/Lobby";
import { Panels } from "./components/Panels";

function useHashRoute(): [string | null, (id: string | null) => void] {
  const read = () => (location.hash.startsWith("#/g/") ? location.hash.slice(4) : null);
  const [id, setId] = useState<string | null>(read);
  useEffect(() => {
    const h = () => setId(read());
    addEventListener("hashchange", h);
    return () => removeEventListener("hashchange", h);
  }, []);
  return [id, (v) => (location.hash = v ? `#/g/${v}` : "")];
}

export default function App() {
  const [id, setId] = useHashRoute();
  if (!id) return <Lobby onOpen={setId} />;
  return <Game id={id} onExit={() => setId(null)} />;
}

function Game({ id, onExit }: { id: string; onExit: () => void }) {
  const [view, setView] = useState<InstanceView | null>(null);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState<string | null>(null);
  const [stage, setStage] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [debug, setDebug] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const load = useCallback(() => api.instance(id).then(setView).catch((e) => setErr(String(e))), [id]);
  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [view, streaming]);

  async function send(text: string) {
    if (!view || streaming !== null || !text.trim()) return;
    setErr(null);
    setPending(text);
    setInput("");
    setStreaming("");
    setStage("adjudicating…");
    let acc = "";
    try {
      for await (const ev of streamTurn(id, text)) {
        if (ev.event === "adjudication") {
          setStage(ev.data.kind === "clarify" || ev.data.kind === "impossible" ? "asking for clarification…" : "resolving…");
        } else if (ev.event === "resolution") {
          setStage("resolving…");
        } else if (ev.event === "text") {
          acc += ev.data.t;
          setStreaming(acc);
          setStage(null);
        } else if (ev.event === "bulletin") {
          setStage("narrating…");
        } else if (ev.event === "referee") {
          setStage(null);
        } else if (ev.event === "done") {
          setStage(null);
          if (ev.data.note) setErr(ev.data.note);
        } else if (ev.event === "error") {
          setErr(ev.data.message);
        }
      }
    } catch (e) {
      setErr(String(e));
    } finally {
      setStreaming(null);
      setStage(null);
      setPending(null);
      await load();
    }
  }

  async function undo(toTurn?: number) {
    if (streaming !== null) return;
    setErr(null);
    try {
      setView(await api.undo(id, toTurn));
    } catch (e) {
      setErr(String(e));
    }
  }

  async function branch(atTurn?: number) {
    if (streaming !== null) return;
    setErr(null);
    try {
      const v = await api.fork(id, atTurn);
      location.hash = `#/g/${v.id}`;
    } catch (e) {
      setErr(String(e));
    }
  }

  if (!view) return <div className="lobby">{err ?? "loading…"}</div>;

  const rows: TranscriptRow[] = view.transcript.filter((r) => r.role === "player" || r.role === "narrator" || r.role === "mechanics");

  return (
    <div className="layout">
      <header>
        <button className="link" onClick={onExit}>
          ← games
        </button>
        <strong>{view.title}</strong>
        <span className="muted">turn {view.turn}</span>
        <span className="spacer" />
        <button onClick={() => undo()} disabled={view.turn === 0 || streaming !== null} title="Rewind one turn">
          undo
        </button>
        <button onClick={() => branch()} disabled={streaming !== null} title="Copy this game as a new branch from here">
          branch
        </button>
        <a className="link small" href={api.exportUrl(id)} download title="Download this game as JSON">
          export
        </a>
        <button onClick={() => setDebug(!debug)}>GM debug</button>
      </header>
      <main>
        <section className="narrative" ref={scrollRef}>
          {rows.map((r) => (r.role === "mechanics" ? <MechanicsRow key={r.seq} text={r.text} /> : (
            <div key={r.seq} className={`msg ${r.role}`}>
              {r.text}
            </div>
          )))}
          {pending && <div className="msg player">{pending}</div>}
          {streaming !== null && streaming && <div className="msg narrator streaming">{streaming}</div>}
          {streaming !== null && stage && <div className="muted small stage">{stage}</div>}
          {view.ending && <div className="ending">The End. {view.ending}</div>}
          {err && <div className="error">{err}</div>}
        </section>
        <aside className="side">
          <Panels panels={view.ui.panels} onChoice={(cmd) => send(cmd)} />
        </aside>
      </main>
      <footer>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
        >
          <textarea
            value={input}
            placeholder={view.ui.placeholder}
            disabled={!view.ui.free_text || streaming !== null}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send(input);
              }
            }}
            rows={2}
          />
          <button type="submit" disabled={streaming !== null || !input.trim()}>
            Send
          </button>
        </form>
      </footer>
      <DebugDrawer
        instanceId={id}
        turn={view.turn}
        transcript={view.transcript}
        open={debug}
        onClose={() => setDebug(false)}
        onRewind={(t) => undo(t)}
        onBranch={(t) => branch(t)}
      />
    </div>
  );
}


function MechanicsRow({ text }: { text: string }) {
  let m: Mechanics;
  try {
    m = JSON.parse(text);
  } catch {
    return null;
  }
  const bits: string[] = [];
  if (m.kind === "clarify" || m.kind === "impossible") bits.push(m.kind);
  if (m.elapsed) bits.push(`+${m.elapsed} min`);
  for (const c of m.checks) bits.push(`${c.label}: ${c.outcome.replace(/_/g, " ")}${c.roll != null ? ` (d20 ${c.roll}, ${c.total} vs ${c.target})` : ""}`);
  for (const e of m.events) bits.push(`event ${e}`);
  for (const e of m.expired) bits.push(`expired ${e}`);
  if (m.applied.length) bits.push(`${m.applied.length} change${m.applied.length === 1 ? "" : "s"}`);
  if (m.rejected.length) bits.push(`${m.rejected.length} rejected`);
  if (m.issues.length) bits.push(`${m.issues.length} issue${m.issues.length === 1 ? "" : "s"}`);
  if (!bits.length) return null;
  const title = [...m.applied, ...m.rejected.map((r) => `rejected ${r.path}: ${r.reason}`), ...m.issues.map((i) => `issue: ${i}`)].join("\n");
  return (
    <div className="mechanics" title={title}>
      {bits.join(" · ")}
    </div>
  );
}
