import { useCallback, useEffect, useRef, useState } from "react";
import { api, streamCommand, streamTurn, type InstanceView, type Mechanics, type TranscriptRow, type TurnEvent } from "./api";
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

const SHOWN: TranscriptRow["role"][] = ["player", "narrator", "mechanics", "command", "result", "system_note"];

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

  /** Drive one SSE stream (typed turn or clicked command) through the stage indicator. */
  async function run(gen: AsyncGenerator<TurnEvent>, pendingText: string) {
    setErr(null);
    setPending(pendingText);
    setStreaming("");
    setStage("adjudicating…");
    let acc = "";
    try {
      for await (const ev of gen) {
        if (ev.event === "command") {
          if (!ev.data.ok) {
            setErr(ev.data.text);
            break;
          }
          setPending(ev.data.label ?? pendingText);
          setStage(ev.data.mode === "engine" ? null : "resolving…");
        } else if (ev.event === "adjudication") {
          setStage(ev.data.kind === "clarify" || ev.data.kind === "impossible" ? "asking for clarification…" : "resolving…");
        } else if (ev.event === "resolution") {
          setStage("resolving…");
        } else if (ev.event === "summary") {
          setStage(ev.data.status === "running" ? `folding turns ${ev.data.turns[0]}–${ev.data.turns[ev.data.turns.length - 1]} into the story so far…` : "narrating…");
        } else if (ev.event === "bulletin") {
          setStage("narrating…");
        } else if (ev.event === "text") {
          acc += ev.data.t;
          setStreaming(acc);
          setStage(null);
        } else if (ev.event === "mechanic") {
          // the engine answered a narrator call: the mechanics line goes inline, where it happened
          acc = (acc.trim() ? acc.replace(/\s+$/, "") + "\n\n" : "") + "§ " + ev.data.text + "\n\n";
          setStreaming(acc);
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

  function send(text: string) {
    if (!view || streaming !== null || !text.trim()) return;
    setInput("");
    return run(streamTurn(id, text), text);
  }

  function sendCommand(command: string, args: Record<string, unknown>) {
    if (!view || streaming !== null) return;
    return run(streamCommand(id, command, args), command);
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

  const rows = view.transcript.filter((r) => SHOWN.includes(r.role));

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
          {rows.map((r) => (
            <Row key={r.seq} r={r} />
          ))}
          {pending && <div className="msg player">{pending}</div>}
          {streaming !== null && streaming && <div className="msg narrator streaming"><Prose text={streaming} /></div>}
          {streaming !== null && stage && <div className="muted small stage">{stage}</div>}
          {view.ending && <div className="ending">The End. {view.ending}</div>}
          {err && <div className="error">{err}</div>}
        </section>
        <aside className="side">
          <Panels panels={view.ui.panels} onChoice={(cmd) => send(cmd)} onCommand={sendCommand} busy={streaming !== null || !!view.ending} />
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

function Row({ r }: { r: TranscriptRow }) {
  switch (r.role) {
    case "mechanics":
      return <MechanicsRow text={r.text} />;
    case "system_note":
      return (
        <details className="story-note">
          <summary>Story so far, as folded into the narrator's memory after turn {r.turn}</summary>
          <div className="note-body">{r.text}</div>
        </details>
      );
    case "narrator":
      return <div className="msg narrator"><Prose text={r.text} /></div>;
    default:
      return <div className={`msg ${r.role}`}>{r.text}</div>;
  }
}

/** Narrator prose with the engine's mechanics lines (lines starting with "§ ") set apart. */
function Prose({ text }: { text: string }) {
  const blocks = text.split(/\n{2,}/);
  return (
    <>
      {blocks.map((b, i) =>
        b.startsWith("§ ") ? (
          <div key={i} className="mechanic-line">{b.slice(2)}</div>
        ) : (
          <p key={i}>{b}</p>
        ),
      )}
    </>
  );
}

function MechanicsRow({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  let m: Mechanics;
  try {
    m = JSON.parse(text);
  } catch {
    return null;
  }
  if (m.kind === "command") return null;
  const bits: string[] = [];
  if (m.kind === "clarify") bits.push("the engine could not tell what you meant and asked; no time passed");
  if (m.kind === "impossible") bits.push("not possible with what you have; no time passed");
  if (m.elapsed) bits.push(`+${m.elapsed} min`);
  for (const c of m.checks) bits.push(`${c.label}: ${c.outcome.replace(/_/g, " ")}${c.roll != null ? ` (d20 ${c.roll}, ${c.total} vs ${c.target})` : ""}`);
  for (const e of m.events) bits.push(`event ${e}`);
  for (const e of m.expired) bits.push(`expired ${e}`);
  for (const h of m.happenings ?? []) bits.push(`unscripted: ${h.id.replace(/_/g, " ")}${h.reason ? ` (${h.reason})` : ""}`);
  if (m.applied.length) bits.push(`${m.applied.length} change${m.applied.length === 1 ? "" : "s"}`);
  if (m.rejected.length) bits.push(`${m.rejected.length} rejected`);
  if (m.lever && m.lever.status !== "applied") bits.push(`${m.lever.id}: ${m.lever.status.replace("_", " ")}`);
  if (m.drift?.length) bits.push(`${m.drift.length} drifted`);
  if (!bits.length) return null;
  const lines = [
    ...m.applied,
    ...m.rejected.map((r) => `rejected ${r.path}: ${r.reason}`),
    ...(m.drift ?? []).map((d) => `drift ${d}`),
    ...(m.issues ?? []).map((i) => `issue: ${i}`),
  ];
  // The detail used to live in a hover tooltip, which a phone cannot show: tap to open it.
  return (
    <div className={"mechanics" + (open ? " open" : "")} onClick={() => lines.length && setOpen(!open)} role={lines.length ? "button" : undefined}>
      {bits.join(" · ")}
      {lines.length > 0 && <span className="mechanics-toggle">{open ? " ▾" : " ▸"}</span>}
      {open && (
        <ul className="mechanics-detail">
          {lines.map((l, i) => (
            <li key={i}>{l}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
