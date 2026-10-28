import { useEffect, useRef, useState } from "react";
import { api, type GameInfo, type InstanceSummary, type InstanceUsage } from "../api";

export function Lobby({ onOpen }: { onOpen: (id: string) => void }) {
  const [games, setGames] = useState<GameInfo[]>([]);
  const [instances, setInstances] = useState<InstanceSummary[]>([]);
  const [setup, setSetup] = useState<Record<string, Record<string, string>>>({});
  const [err, setErr] = useState<string | null>(null);
  const [openProps, setOpenProps] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = () => api.instances().then(setInstances).catch((e) => setErr(String(e)));
  useEffect(() => {
    // The dev server is up before the API on a fresh start; keep trying for a while
    // instead of pinning a proxy error to the page.
    let cancelled = false;
    const load = async (attempt: number) => {
      try {
        const [g, i] = await Promise.all([api.games(), api.instances()]);
        if (cancelled) return;
        setGames(g);
        setInstances(i);
        setErr(null);
      } catch (e) {
        if (cancelled) return;
        if (attempt < 20) {
          setErr(`waiting for the server… (${String(e)})`);
          setTimeout(() => load(attempt + 1), 1000);
        } else {
          setErr(String(e));
        }
      }
    };
    load(0);
    return () => {
      cancelled = true;
    };
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
          <li key={i.id} style={{ flexWrap: "wrap" }}>
            <button className="link" onClick={() => onOpen(i.id)}>
              {i.title}
            </button>
            <span className="muted small">
              turn {i.turn} · {new Date(i.created).toLocaleString()}
              {i.origin.forked_from && ` · branch of ${i.origin.forked_from} @${i.origin.at_turn}`}
              {i.origin.imported && " · imported"}
            </span>
            <span className="spacer" />
            <button className="link small" onClick={() => setOpenProps(openProps === i.id ? null : i.id)} title="Rename, branch, export, delete, cost">
              {openProps === i.id ? "close" : "properties"}
            </button>
            {openProps === i.id && (
              <div className="props" style={{ flexBasis: "100%" }}>
                <Props inst={i} act={act} onDeleted={() => setOpenProps(null)} />
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Props({ inst, act, onDeleted }: { inst: InstanceSummary; act: (fn: () => Promise<unknown>) => Promise<void>; onDeleted: () => void }) {
  const [usage, setUsage] = useState<InstanceUsage | null>(null);
  useEffect(() => {
    api.usage(inst.id).then(setUsage).catch(() => setUsage(null));
  }, [inst.id, inst.turn]);
  const fmt = (n: number) => n.toLocaleString();
  return (
    <div>
      <div className="muted small">
        {inst.game} v{inst.game_version} · id {inst.id} · created {new Date(inst.created).toLocaleString()}
        {inst.origin.forked_from && ` · branched from ${inst.origin.forked_from} at turn ${inst.origin.at_turn}`}
        {inst.origin.imported && ` · imported from ${inst.origin.original_id ?? "?"}`}
      </div>
      {usage && (
        <table style={{ marginTop: 8 }}>
          <thead>
            <tr>
              <th>role</th>
              <th>model</th>
              <th>calls</th>
              <th>input</th>
              <th>cache read</th>
              <th>cache write</th>
              <th>output</th>
              <th>cost</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(usage.roles).map(([role, r]) => (
              <tr key={role}>
                <td>{role}</td>
                <td className="muted">{r.model ?? "—"}</td>
                <td>{r.calls}</td>
                <td>{fmt(r.usage.input_tokens)}</td>
                <td>{fmt(r.usage.cache_read_input_tokens)}</td>
                <td>{fmt(r.usage.cache_creation_input_tokens)}</td>
                <td>{fmt(r.usage.output_tokens)}</td>
                <td>{r.priced ? `$${r.usd.toFixed(3)}` : "—"}</td>
              </tr>
            ))}
            <tr>
              <td colSpan={7}>
                <strong>total</strong> · {usage.calls} calls over {usage.turn} turns
              </td>
              <td>
                <strong>{usage.priced ? `$${usage.usd.toFixed(2)}` : `$${usage.usd.toFixed(2)}+`}</strong>
              </td>
            </tr>
          </tbody>
        </table>
      )}
      <div className="row-actions">
        <button
          className="link small"
          onClick={() => {
            const t = prompt("Rename game", inst.title);
            if (t != null && t.trim()) act(() => api.rename(inst.id, t));
          }}
        >
          rename
        </button>
        <button className="link small" onClick={() => act(() => api.fork(inst.id))}>
          branch
        </button>
        <a className="link small" href={api.exportUrl(inst.id)} download>
          export
        </a>
        <button
          className="link small danger"
          onClick={() => {
            if (confirm(`Delete "${inst.title}"? This cannot be undone.`)) act(() => api.remove(inst.id)).then(onDeleted);
          }}
        >
          delete
        </button>
      </div>
    </div>
  );
}
