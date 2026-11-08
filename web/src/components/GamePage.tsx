import { useCallback, useEffect, useState } from "react";
import { api, type GameInfo, type InstanceSummary, type SetupField, type SetupOption } from "../api";
import { ago, endingShort, originMark } from "../saves";
import { SaveCard } from "./SaveCard";

type Field = { key: string; plain: boolean; kind: "select" | "text" | "textarea"; label: string; hint: string; required: boolean; options: SetupOption[]; initial: string };

// Each setup key as one shape: the plain list is a select labelled by its key (station, noir); a field keeps its kind.
// The engine appends its own Difficulty select to every game's fields.
function fieldsOf(g: GameInfo): Field[] {
  return Object.entries(g.setup).map(([key, spec]) => {
    if (Array.isArray(spec)) return { key, plain: true, kind: "select", label: key.charAt(0).toUpperCase() + key.slice(1), hint: "", required: false, options: spec, initial: spec[0]?.id ?? "" };
    const f = spec as SetupField;
    const options = (f.options ?? []).map((o) => (typeof o === "string" ? { id: o, name: o } : o));
    const kind = f.kind ?? "select";
    const initial = f.default ?? (kind === "select" ? options[0]?.id ?? "" : "");
    return { key, plain: false, kind, label: f.label || key, hint: f.hint ?? "", required: !!f.required, options, initial };
  });
}

/** A game's own page: New game first, then its saved games (most recently played first) (the owner, 11-08). */
export function GamePage({ name }: { name: string }) {
  const [game, setGame] = useState<GameInfo | null>(null);
  const [saves, setSaves] = useState<InstanceSummary[] | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [open, setOpen] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [missingGame, setMissingGame] = useState(false);

  const refresh = useCallback(() => api.instances(name).then(setSaves).catch((e) => setErr(String(e))), [name]);
  useEffect(() => {
    const load = () => {
      api.games()
        .then((gs) => {
          const g = gs.find((x) => x.name === name) ?? null;
          setGame(g);
          setMissingGame(!g);
        })
        .catch((e) => setErr(String(e)));
      refresh();
    };
    load();
    addEventListener("ta-dev", load);
    return () => removeEventListener("ta-dev", load);
  }, [name, refresh]);

  if (missingGame) return <div className="lobby"><h1>No such game</h1><p className="muted">There is no game called “{name}” here. <a className="link" href="#/">All games</a></p></div>;
  if (!game || !saves) return <div className="lobby">{err ?? "loading…"}</div>;

  const fields = fieldsOf(game);
  const valueOf = (f: Field) => values[f.key] ?? f.initial;
  const missing = fields.filter((f) => f.required && !valueOf(f).trim());

  async function start() {
    setErr(null);
    try {
      const shown = Object.fromEntries(fields.map((f) => [f.key, valueOf(f)]));   // what the fields show, selects' defaults included
      const v = await api.create(game!.name, shown);
      location.hash = `#/g/${v.id}`;
    } catch (e) {
      setErr(String(e));
    }
  }

  const newGame = (
    <section className="new-game" key="new">
      <h2>New game</h2>
      <div className="game">
        {fields.map((f) => (
          <label key={f.key} className="setup-field">
            <span>{f.label}</span>
            {f.kind === "select" ? (
              <select value={valueOf(f)} onChange={(e) => setValues({ ...values, [f.key]: e.target.value })}>
                {f.options.map((o) => (
                  <option key={o.id} value={o.id}>{o.name}</option>
                ))}
              </select>
            ) : f.kind === "textarea" ? (
              <textarea rows={4} value={valueOf(f)} placeholder={f.hint || undefined} onChange={(e) => setValues({ ...values, [f.key]: e.target.value })} />
            ) : (
              <input type="text" value={valueOf(f)} placeholder={f.hint || undefined} onChange={(e) => setValues({ ...values, [f.key]: e.target.value })} />
            )}
          </label>
        ))}
        {/* Reserved: the game's mods as checkboxes go here, under the setup fields (the mods design). Empty on purpose. */}
        <div className="mods-slot" data-slot="mods" />
        <button className="primary" onClick={start} disabled={missing.length > 0} title={missing.length ? `Fill in: ${missing.map((f) => f.label).join(", ")}` : undefined}>
          Start
        </button>
      </div>
    </section>
  );

  const saved = (
    <section className="saves" key="saves">
      <h2>Saved games</h2>
      <ul className="save-list">
        {saves.map((i) => (
          <li key={i.id} className={open === i.id ? "open" : ""}>
            <button className="save-line" onClick={() => setOpen(open === i.id ? null : i.id)} aria-expanded={open === i.id}>
              <span className="save-title">{i.title}</span>
              {i.save_line.map((c, k) => (
                <span key={k} className={`save-bit${c.tone ? ` tone-${c.tone}` : ""}`}>{c.value}</span>
              ))}
              <span className="save-bit muted">turn {i.turn}</span>
              <span className="save-bit muted" title={new Date(i.updated).toLocaleString()}>{ago(i.updated)}</span>
              {i.ending && <span className="save-bit ended" title={i.ending}>ended: {endingShort(i.ending)}</span>}
              {originMark(i) && <span className="save-bit mark">{originMark(i)}</span>}
              {i.hidden && <span className="dev-mark">dev</span>}
            </button>
            {open === i.id && <SaveCard id={i.id} onClose={() => setOpen(null)} onChanged={refresh} onGone={() => { setOpen(null); refresh(); }} />}
          </li>
        ))}
      </ul>
    </section>
  );

  return (
    <div className="lobby">
      <h1>
        {game.title}
        {game.hidden && <span className="dev-mark">dev</span>}
      </h1>
      <p className="muted">{game.description}</p>
      {err && <div className="error">{err}</div>}
      {saves.length ? [newGame, saved] : [newGame]}
      {/* Reserved: the game's Mods list (files with download, delete, upload) goes here (the mods design). Empty on purpose. */}
      <section className="mods-list" data-slot="mods-list" />
    </div>
  );
}
