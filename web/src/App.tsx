import { useCallback, useEffect, useRef, useState } from "react";
import { api, streamCommand, streamRewrite, streamTurn, type GraveCard, type InstanceView, type Mechanics, type TranscriptRow, type TurnEvent } from "./api";
import { Bar } from "./components/Bar";
import { DebugDrawer } from "./components/DebugDrawer";
import { GamePage } from "./components/GamePage";
import { DeathCardBody, Graveyard } from "./components/Graveyard";
import { Home } from "./components/Home";
import { Panels } from "./components/Panels";
import { SettingsPage } from "./components/SettingsPage";
import { prefs } from "./saves";

// The pages, by hash: #/ home (the games), #/games/<name> a game's page (its saves, New game), #/g/<id> play,
// #/settings Settings (#/settings/<id>: opened from that game, with its difficulty), #/graveyard (#/graveyard/<game>).
type Route =
  | { page: "home" }
  | { page: "game"; name: string }
  | { page: "play"; id: string }
  | { page: "settings"; id: string | null }
  | { page: "graveyard"; game: string | null };

function readRoute(): Route {
  const h = location.hash.replace(/^#/, "");
  let m: RegExpMatchArray | null;
  if ((m = h.match(/^\/g\/([^/?]+)/))) return { page: "play", id: decodeURIComponent(m[1]) };
  if ((m = h.match(/^\/graveyard(?:\/([^/?]+))?/))) return { page: "graveyard", game: m[1] ? decodeURIComponent(m[1]) : null };
  if ((m = h.match(/^\/games\/([^/?]+)/))) return { page: "game", name: decodeURIComponent(m[1]) };
  if ((m = h.match(/^\/settings(?:\/([^/?]+))?/))) return { page: "settings", id: m[1] ? decodeURIComponent(m[1]) : null };
  return { page: "home" };
}

function useRoute(): Route {
  const [route, setRoute] = useState<Route>(readRoute);
  useEffect(() => {
    const h = () => {
      setRoute(readRoute());
      scrollTo(0, 0);
    };
    addEventListener("hashchange", h);
    return () => removeEventListener("hashchange", h);
  }, []);
  return route;
}

export default function App() {
  const route = useRoute();
  const settingsHref = route.page === "play" ? `#/settings/${route.id}` : route.page === "settings" && route.id ? `#/settings/${route.id}` : "#/settings";
  return (
    <div className={`app app-${route.page}`}>
      <Bar settingsHref={settingsHref} />
      <div className="page">
        {route.page === "home" && <Home />}
        {route.page === "game" && <GamePage key={route.name} name={route.name} />}
        {route.page === "play" && <Game key={route.id} id={route.id} />}
        {route.page === "settings" && <SettingsPage key={route.id ?? ""} iid={route.id} />}
        {route.page === "graveyard" && <Graveyard key={route.game ?? ""} game={route.game} />}
      </div>
    </div>
  );
}

const SHOWN: TranscriptRow["role"][] = ["player", "narrator", "mechanics", "command", "result", "system_note", "ask", "aside"];

function Game({ id }: { id: string }) {
  const [view, setView] = useState<InstanceView | null>(null);
  const [input, setInput] = useState("");
  const [asking, setAsking] = useState(false);       // the Ask toggle (B105): the box's words go to the game master as a question
  const [askBusy, setAskBusy] = useState(false);
  const [streaming, setStreaming] = useState<string | null>(null);
  const [stage, setStage] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [debug, setDebug] = useState(false);
  const [hideUndone, setHideUndone] = useState(prefs.hideUndone());
  const [death, setDeath] = useState<GraveCard | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const load = useCallback(() => api.instance(id).then(setView).catch((e) => setErr(String(e))), [id]);
  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    const sync = () => setHideUndone(prefs.hideUndone());
    addEventListener("ta-prefs", sync);
    return () => removeEventListener("ta-prefs", sync);
  }, []);
  // the death card (the graveyard's record of this save's death), fetched when the story ends
  const ended = view?.ending ?? null;
  useEffect(() => {
    if (!ended) {
      setDeath(null);
      return;
    }
    let live = true;
    api.death(id).then((d) => live && setDeath(d)).catch(() => live && setDeath(null));
    return () => {
      live = false;
    };
  }, [id, ended]);
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
    if (asking || text.trim().startsWith("?")) return askGM(text);
    setInput("");
    return run(streamTurn(id, text), text);
  }

  // B105 (c): Ask mode, a question to the game master out of the story: no clock, no events, no referee
  async function askGM(text: string) {
    const q = text.trim().replace(/^\?+/, "").trim();
    if (!q) return;
    setInput("");
    setErr(null);
    setAskBusy(true);
    try {
      const res = await api.ask(id, q);
      if (res.view) setView(res.view);
      else if (!res.ok) setErr(res.text);
    } catch (e) {
      setErr(String(e));
    } finally {
      setAskBusy(false);
    }
  }

  function sendCommand(command: string, args: Record<string, unknown>) {
    if (!view || streaming !== null) return;
    if (command === "reread_sheet") {
      // B90: before the first turn, whatever is in the text box is the player's correction to the sheet
      const text = input.trim();
      setInput("");
      return run(streamCommand(id, command, { ...args, text }), text ? `Re-read my sheet: ${text}` : "Re-read my sheet");
    }
    return run(streamCommand(id, command, args), command);
  }

  // B228: a clicked command's turn cannot be told again (no words to retell); the rewrite button is not offered for it
  const lastWasCommand = !!view && view.transcript.some((r) => r.turn === view.turn && r.role === "command");

  /** "You're out of line": the last turn is told again, same facts, same dice. Whatever is in the text box is the
   * ruling or the instructions; an empty box just asks for it told again. The referee's writes are undone with the turn. */
  function rewrite() {
    if (!view || streaming !== null || view.turn === 0 || lastWasCommand) return;
    const hint = input.trim();
    setInput("");
    const last = [...view.transcript].reverse().find((r) => r.role === "player");
    return run(streamRewrite(id, hint), `${last ? last.text : ""}  ↺ ${hint || "tell it again"}`.trim());
  }

  async function redo() {
    if (streaming !== null) return;
    setErr(null);
    try {
      setView(await api.redo(id));
    } catch (e) {
      setErr(String(e));
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

  // undone turns stay in the log, struck through (their engine rows and summaries are not shown), unless hidden in Settings
  const rows = view.transcript.filter((r) => SHOWN.includes(r.role) && (!r.undone || (!hideUndone && (r.role === "player" || r.role === "narrator" || r.role === "command"))));
  const firstOfUndo = new Set<number>();
  {
    const seen = new Set<number>();
    for (const r of rows) if (r.undone && !seen.has(r.undone)) (seen.add(r.undone), firstOfUndo.add(r.seq));
  }
  const goBack = (r: TranscriptRow) => {
    const back = view.turn - (r.turn - 1);
    if (back > 1 && !confirm(`Go back to before turn ${r.turn}? ${back} turns will be undone. They stay in the log, struck through.`)) return;
    undo(r.turn - 1);
  };

  return (
    <div className="layout">
      <header>
        <a className="link" href={`#/games/${view.game}`} title="This game's saved games and New game">
          ← saves
        </a>
        <strong>{view.title}</strong>
        <span className="muted">turn {view.turn}</span>
        <span className="spacer" />
        <button onClick={() => undo()} disabled={view.turn === 0 || streaming !== null} title="Rewind one turn">
          undo
        </button>
        {view.redo && (
          <button onClick={() => redo()} disabled={streaming !== null} title={`Bring back turns ${view.redo.to_turn + 1} to ${view.redo.from_turn}: nothing has happened since the undo`}>
            redo
          </button>
        )}
        <button onClick={() => rewrite()} disabled={view.turn === 0 || streaming !== null || lastWasCommand}
                title={lastWasCommand ? "The last turn was a command, not words: there is nothing to tell again" : "Request a rewrite of the last turn: same facts, same dice, the referee's changes undone. Whatever is in the text box is your explanation or instructions; empty just tells it again."}>
          rewrite
        </button>
        <a className="button-like" href={`#/settings/${id}`} title="Settings: this game's difficulty, the narrator guard, the profile this server plays on">settings</a>
        <button onClick={() => branch()} disabled={streaming !== null} title="Copy this game as a new branch from here">
          branch
        </button>
        <a className="link small" href={api.exportUrl(id)} download title="Download this game as JSON">
          export
        </a>
        <button onClick={() => setDebug(!debug)}>GM debug</button>
      </header>
      <main>
        <div className="centre">
        <section className="narrative" ref={scrollRef}>
          {rows.map((r) => (
            <Row key={r.seq} r={r} first={firstOfUndo.has(r.seq)} onRedo={view.redo && r.undone === view.redo.mark && streaming === null ? () => redo() : undefined} onUndo={streaming === null && !r.undone && r.turn > 0 && (r.role === "player" || r.role === "command") ? () => goBack(r) : undefined} />
          ))}
          {pending && <div className="msg player">{pending}</div>}
          {streaming !== null && streaming && <div className="msg narrator streaming"><Prose text={streaming} /></div>}
          {streaming !== null && stage && <div className="muted small stage">{stage}</div>}
          {view.ending && death && (
            <div className="ending death-ending">
              <DeathCardBody
                g={death}
                actions={
                  <>
                    <button className="primary" onClick={() => undo()} disabled={streaming !== null || view.turn === 0}>Undo the last turn</button>
                    {death.turn - 1 < view.turn - 1 && (
                      <button onClick={() => undo(death.turn - 1)} disabled={streaming !== null}>Go back to before the fall</button>
                    )}
                    <a className="button-like" href="#/graveyard">Graveyard</a>
                    <a className="button-like" href={`#/games/${view.game}`}>New game</a>
                  </>
                }
              />
            </div>
          )}
          {view.ending && !death && (
            <div className="ending">
              The End. {view.ending}
              <div className="continue-row">
                <button onClick={() => undo()} disabled={streaming !== null || view.turn === 0}>Undo the last turn</button>
              </div>
            </div>
          )}
          {err && <div className="error">{err}</div>}
        </section>
        {view.ui.panels.some((w) => w.place === "main") && (
          <section className="main-panels">
            <Panels panels={view.ui.panels} place="main" onChoice={(cmd) => send(cmd)} onCommand={sendCommand} busy={streaming !== null} ended={!!view.ending} />
          </section>
        )}
        </div>
        <aside className="side">
          <Panels panels={view.ui.panels} place="side" onChoice={(cmd) => send(cmd)} onCommand={sendCommand} busy={streaming !== null} ended={!!view.ending} />
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
            placeholder={asking ? "Ask the game master (nothing happens in the story)" : view.ui.placeholder}
            disabled={!view.ui.free_text || streaming !== null || askBusy}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send(input);
              }
            }}
            rows={2}
          />
          <div className="send-stack">
            <button type="submit" disabled={streaming !== null || askBusy || !input.trim()}>
              {asking || input.trim().startsWith("?") ? "Ask" : "Send"}
            </button>
            {/* B105: with words in the box, Ask sends them as a question at once; with none, it switches to asking */}
            <button type="button" className={`ask-toggle small${asking ? " on" : ""}`} aria-pressed={asking} disabled={streaming !== null || askBusy}
              title="Ask the game master a question out of the story: no time passes and nothing happens. Or start your words with ?"
              onClick={() => (input.trim() ? askGM(input) : setAsking(!asking))}>
              Ask
            </button>
          </div>
        </form>
      </footer>
      <DebugDrawer
        instanceId={id}
        turn={view.turn}
        transcript={view.transcript.filter((r) => !r.undone)}
        open={debug}
        onClose={() => setDebug(false)}
        onRewind={(t) => undo(t)}
        onBranch={(t) => branch(t)}
      />
    </div>
  );
}

function Row({ r, first, onUndo, onRedo }: { r: TranscriptRow; first?: boolean; onUndo?: () => void; onRedo?: () => void }) {
  if (r.undone) {
    // an undone turn: kept in the record, struck through; nothing a model reads sees it
    return (
      <div className={`undone-row ${r.role}`}>
        {first && (
          <div className="undone-mark small">
            undone{onRedo && <> · <button className="link small redo-link" onClick={onRedo} title="Bring these turns back: nothing has happened since">↻ redo</button></>}
          </div>
        )}
        <div className={`msg ${r.role} undone`}>{r.role === "narrator" ? <Prose text={r.text} /> : r.text}</div>
      </div>
    );
  }
  if (onUndo) {
    return (
      <div className={`row-with-undo ${r.role}`}>
        <button className="link small row-undo" onClick={onUndo} title={`Undo turn ${r.turn} and everything after it`} aria-label={`Undo turn ${r.turn} and everything after it`}>
          ↺ undo
        </button>
        <div className={`msg ${r.role}`}>{r.text}</div>
      </div>
    );
  }
  switch (r.role) {
    case "mechanics":
      return <MechanicsRow text={r.text} />;
    case "ask":
      return <div className="msg ask"><span className="aside-tag">asked</span> {r.text}</div>;
    case "aside":
      return <div className="msg aside"><span className="aside-tag">game master</span> {r.text}</div>;
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
    ...(m.calls ?? []).map((c) => (c.outcome ? `${c.call}: ${c.outcome.replace(/_/g, " ")}` : `${c.call}`)
      + (c.consequence ? ` · consequence ${c.consequence.roll}: ${c.consequence.tier} (${c.consequence.source})`
        + (c.consequence.complication ? ` · ${c.consequence.complication.kind}` : "") + (c.consequence.mark ? ` · mark ${c.consequence.mark.kind}` : "")
        + (c.consequence.way_closed ? " · way closed" : "") : "")),
    ...(m.timing ? [`clock after the prose: +${m.timing.added} min (results ${m.timing.result_minutes}, time lost ${m.timing.lost} of ${m.timing.lost_asked} asked${m.timing.stopped_at ? `, stopped at ${m.timing.stopped_at}` : ""})`] : []),
    ...m.events.map((e) => `event ${e}`),
    ...m.expired.map((e) => `expired ${e}`),
    ...(m.holds ?? []),
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
