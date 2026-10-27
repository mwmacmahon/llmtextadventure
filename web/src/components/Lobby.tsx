import { useEffect, useRef, useState } from "react";
import { api, type GameInfo, type InstanceSummary } from "../api";

export function Lobby({ onOpen }: { onOpen: (id: string) => void }) {
  const [games, setGames] = useState<GameInfo[]>([]);
  const [instances, setInstances] = useState<InstanceSummary[]>([]);
  const [setup, setSetup] = useState<Record<string, Record<string, string>>>({});
  const [err, setErr] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = () => api.instances().then(setInstances).catch((e) => setErr(String(e)));
  useEffect(() => {
    api.games().then(setGames).catch((e) => setErr(String(e)));
    refresh();
  }, []);

  async function start(g: GameInfo) {
    try {
      const v = await api.create(g.name, setup[g.name] ?? {});
      onOpen(v.id);
    } catch (e) {
      setErr(String(e));
    }
  }

  async function act(fn: () => Promise<unknown>) {
    setErr(null);
    try {
      await fn();
      await refresh();
    } catch (e) {
      setErr(String(e));
    }
  }

  async function importFile(f: File) {
    const text = await f.text();
    await act(async () => {
      const v = await api.importDoc(JSON.parse(text));
      onOpen(v.id);
    });
  }

  return (
    <div className="lobby">
      <h1>Text Adventure</h1>
      {err && <div className="error">{err}</div>}
      <h2>New game</h2>
      <div className="games">
        {games.map((g) => (
          <div key={g.name} className="game">
            <div className="card-title">{g.title}</div>
            <p className="muted">{g.description}</p>
            {Object.entries(g.setup).map(([key, opts]) => (
              <label key={key}>
                {key}{" "}
                <select value={setup[g.name]?.[key] ?? opts[0]?.id} onChange={(e) => setSetup({ ...setup, [g.name]: { ...(setup[g.name] ?? {}), [key]: e.target.value } })}>
                  {opts.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.name}
                    </option>
                  ))}
                </select>
              </label>
            ))}
            <button onClick={() => start(g)}>Start</button>
          </div>
        ))}
      </div>
      <h2>
        Continue
        <input ref={fileRef} type="file" accept="application/json,.json" hidden onChange={(e) => e.target.files?.[0] && importFile(e.target.files[0])} />
        <button className="small-btn" onClick={() => fileRef.current?.click()}>
          import…
        </button>
      </h2>
      {instances.length === 0 && <p className="muted">No saved games yet.</p>}
      <ul className="instances">
        {instances.map((i) => (
          <li key={i.id}>
            <button className="link" onClick={() => onOpen(i.id)}>
              {i.title}
            </button>
            <span className="muted small">
              turn {i.turn} · {new Date(i.created).toLocaleString()}
              {i.origin.forked_from && ` · branch of ${i.origin.forked_from} @${i.origin.at_turn}`}
              {i.origin.imported && " · imported"}
            </span>
            <span className="spacer" />
            <span className="row-actions">
              <button
                className="link small"
                onClick={() => {
                  const t = prompt("Rename game", i.title);
                  if (t != null && t.trim()) act(() => api.rename(i.id, t));
                }}
              >
                rename
              </button>
              <button className="link small" onClick={() => act(() => api.fork(i.id))}>
                branch
              </button>
              <a className="link small" href={api.exportUrl(i.id)} download>
                export
              </a>
              <button
                className="link small danger"
                onClick={() => {
                  if (confirm(`Delete "${i.title}"? This cannot be undone.`)) act(() => api.remove(i.id));
                }}
              >
                delete
              </button>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
