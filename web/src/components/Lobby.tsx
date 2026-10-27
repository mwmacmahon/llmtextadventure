import { useEffect, useState } from "react";
import { api, type GameInfo, type InstanceSummary } from "../api";

export function Lobby({ onOpen }: { onOpen: (id: string) => void }) {
  const [games, setGames] = useState<GameInfo[]>([]);
  const [instances, setInstances] = useState<InstanceSummary[]>([]);
  const [setup, setSetup] = useState<Record<string, Record<string, string>>>({});
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.games().then(setGames).catch((e) => setErr(String(e)));
    api.instances().then(setInstances).catch((e) => setErr(String(e)));
  }, []);

  async function start(g: GameInfo) {
    try {
      const v = await api.create(g.name, setup[g.name] ?? {});
      onOpen(v.id);
    } catch (e) {
      setErr(String(e));
    }
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
      {instances.length > 0 && (
        <>
          <h2>Continue</h2>
          <ul className="instances">
            {instances.map((i) => (
              <li key={i.id}>
                <button className="link" onClick={() => onOpen(i.id)}>
                  {i.title}
                </button>
                <span className="muted small">
                  turn {i.turn} · {new Date(i.created).toLocaleString()}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
