import { useCallback, useEffect, useRef, useState } from "react";
import { api, streamCommand, streamRewrite, streamTurn, type InstanceView, type Mechanics, type Settings, type TranscriptRow, type TurnEvent } from "./api";
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
  const [settingsOpen, setSettingsOpen] = useState(false);
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
    setStage("the assistant reads the move…");
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
        } else if (ev.event === "rewrite") {
          acc = "";
          setStreaming("");
          setStage(ev.data.by === "referee" ? `retelling turn ${ev.data.turn} after a ruling…` : `retelling turn ${ev.data.turn}…`);
        } else if (ev.event === "retell") {
          // the referee ruled the telling out of line; under the guard the engine tells it again before (gate) or after (rewrite) showing it
          acc = "";
          setStreaming("");
          setStage(`rewriting… (${ev.data.rulings.map((r) => r.rule.replace(/_/g, " ")).join(", ")})`);
        } else if (ev.event === "progress") {
          // the prose may be held back (gate): a share of the usual length, then "checking…"
          if (ev.data.stage === "checking") setStage("checking…");
          else if (ev.data.slow) setStage("writing… taking longer than usual");
          else if (!acc) setStage(`writing… (est ~${ev.data.pct}%)`);
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

  /** "You're out of line": the last turn is told again, same facts, same dice. Whatever is in the text box is the
   * ruling or the instructions; an empty box just asks for it told again. The referee's writes are undone with the turn. */
  function rewrite() {
    if (!view || streaming !== null || view.turn === 0) return;
    const hint = input.trim();
    setInput("");
    const last = [...view.transcript].reverse().find((r) => r.role === "player");
    return run(streamRewrite(id, hint), `${last ? last.text : ""}  ↺ ${hint || "tell it again"}`.trim());
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
        <button onClick={() => rewrite()} disabled={view.turn === 0 || streaming !== null} title="Request a rewrite of the last turn: same facts, same dice, the referee's changes undone. Whatever is in the text box is your explanation or instructions; empty just tells it again.">
          rewrite
        </button>
        <button onClick={() => setSettingsOpen(!settingsOpen)} title="The narrator guard and the models in use">settings</button>
        <button onClick={() => branch()} disabled={streaming !== null} title="Copy this game as a new branch from here">
          branch
        </button>
        <a className="link small" href={api.exportUrl(id)} download title="Download this game as JSON">
          export
        </a>
        <button onClick={() => setDebug(!debug)}>GM debug</button>
      </header>
      {settingsOpen && <SettingsMenu onClose={() => setSettingsOpen(false)} />}
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
          <div key={i} className="mechanic-line">
            {b.slice(2).split(/([\u2680-\u2685])/).map((part, k) => (/^[\u2680-\u2685]$/.test(part) ? <span key={k} className="die">{part}</span> : part))}
          </div>
        ) : (
          <p key={i}>{b}</p>
        ),
      )}
    </>
  );
}

const ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
  "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"];
const TENS = ["", "", "twenty", "thirty", "forty", "fifty"];

function numberWord(n: number): string {
  if (n < 20) return ONES[n];
  if (n < 60) return TENS[Math.floor(n / 10)] + (n % 10 ? `-${ONES[n % 10]}` : "");
  return String(n);
}

/** Time in words for the player's row (B18): "One minute elapsed.", "An hour and ten minutes elapsed." */
export function timeWords(minutes: number): string {
  if (!minutes || minutes <= 0) return "";
  const h = Math.floor(minutes / 60), m = minutes % 60;
  const parts: string[] = [];
  if (h) parts.push(h === 1 ? "an hour" : `${numberWord(h)} hours`);
  if (m) parts.push(m === 1 ? "one minute" : `${numberWord(m)} minutes`);
  const s = parts.join(" and ");
  return s.charAt(0).toUpperCase() + s.slice(1) + " elapsed.";
}

/** The player's row under the prose (ISSUES B18, D143): the time in words and what the player should see change
 *  (pockets, health and nerves, a thing lost, a way closed). The checks are already in the § lines above; the
 *  engine's internals (events due, counts, drift, rulings) open with a tap on the row's ▸. */
function MechanicsRow({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  let m: Mechanics;
  try {
    m = JSON.parse(text);
  } catch {
    return null;
  }
  if (m.kind === "command") return null;
  const shown: string[] = [];
  if (m.kind === "clarify") shown.push("The engine could not tell what you meant and asked; no time passed.");
  if (m.kind === "impossible") shown.push("Not possible with what you have; no time passed.");
  const time = timeWords(m.elapsed);
  if (time) shown.push(time);
  const seen = m.seen ?? [];
  const lines = [
    ...(m.calls ?? []).map((c) => (c.outcome ? `${c.call}: ${c.outcome.replace(/_/g, " ")}` : `${c.call}`)),
    ...m.events.map((e) => `event ${e}`),
    ...m.expired.map((e) => `expired ${e}`),
    ...(m.happenings ?? []).map((h) => `unscripted: ${h.id.replace(/_/g, " ")}${h.reason ? ` (${h.reason})` : ""}`),
    ...(m.rewritten ? [`retold${m.rewritten.by === "referee" ? " by the referee" : ""}${m.rewritten.attempt > 1 ? ` (${m.rewritten.attempt}×)` : ""}: ${m.rewritten.hint || "(tell it again)"}`] : []),
    ...(m.rulings ?? []).map((r) => `${r.serious ? "ruling" : "note"} ${r.rule.replace(/_/g, " ")}: ${r.what}${r.fix && r.fix !== r.what ? ` → ${r.fix}` : ""}`),
    ...(m.levers ?? []).map((lv) => `lever ${lv.id} ${lv.status.replace("_", " ")}: ${lv.text}`),
    ...m.applied,
    ...m.rejected.map((r) => `rejected ${r.path}: ${r.reason}`),
    ...(m.drift ?? []).map((d) => `drift ${d}`),
    ...(m.issues ?? []).map((i) => `issue: ${i}`),
  ];
  if (!shown.length && !seen.length && !lines.length) return null;
  // The detail used to live in a hover tooltip, which a phone cannot show: tap to open it.
  return (
    <div className={"mechanics" + (open ? " open" : "")} onClick={() => lines.length && setOpen(!open)} role={lines.length ? "button" : undefined}>
      <div className="mechanics-head">
        {shown.length > 0 && <span>{shown.join(" ")}</span>}
        {seen.map((x, i) => (
          <span key={i} className="seen-chip">{x}</span>
        ))}
        {lines.length > 0 && <span className="mechanics-toggle" title="the engine's detail">{open ? "▾" : "▸"}</span>}
      </div>
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

/** The settings menu: the narrator guard (changeable) and the roles' backends (shown; swapping them is a todo). */
function SettingsMenu({ onClose }: { onClose: () => void }) {
  const [s, setS] = useState<Settings | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    api.settings().then(setS).catch((e) => setErr(String(e)));
  }, []);
  async function setMode(mode: string) {
    try {
      setS(await api.updateSettings({ guard: { mode } }));
    } catch (e) {
      setErr(String(e));
    }
  }
  if (!s) return <div className="settings muted small">{err ?? "loading settings…"}</div>;
  return (
    <div className="settings">
      <div className="settings-row">
        <strong>Narrator guard</strong>
        <select value={s.guard.mode} onChange={(e) => setMode(e.target.value)}>
          {Object.keys(s.modes).map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
        <span className="muted small">{s.modes[s.guard.mode]}</span>
      </div>
      <div className="settings-row muted small">
        <strong>Backends</strong>
        {Object.entries(s.roles).map(([role, r]) => (
          <span key={role}>{role}: {r.provider}:{r.model}{r.effort ? `/${r.effort}` : ""}</span>
        ))}
        <span>(swapping backends from here: todo; set in config.yml or TA_CONFIG for now)</span>
      </div>
      {err && <div className="error small">{err}</div>}
      <button className="link small" onClick={onClose}>close</button>
    </div>
  );
}

