import { useCallback, useEffect, useRef, useState } from "react";
import { api, streamTurn, type InstanceView, type TranscriptRow } from "./api";
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
    let acc = "";
    try {
      for await (const ev of streamTurn(id, text)) {
        if (ev.event === "text") {
          acc += ev.data.t;
          setStreaming(acc);
        } else if (ev.event === "error") {
          setErr(ev.data.message);
        } else if (ev.event === "done" && ev.data.note) {
          setErr(ev.data.note);
        }
      }
    } catch (e) {
      setErr(String(e));
    } finally {
      setStreaming(null);
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

  const rows: TranscriptRow[] = view.transcript.filter((r) => r.role === "player" || r.role === "narrator");

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
            <div key={r.seq} className={`msg ${r.role}`}>
              {r.text}
            </div>
          ))}
          {pending && <div className="msg player">{pending}</div>}
          {streaming !== null && <div className="msg narrator streaming">{streaming || "…"}</div>}
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
