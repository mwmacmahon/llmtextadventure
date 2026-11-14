import { useCallback, useEffect, useRef, useState } from "react";
import { api, type GameInfo, type InstanceSummary, type ModInfo, type SetupField, type SetupOption } from "../api";
import { ago, countsLine, endingShort, originMark } from "../saves";
import { SaveCard } from "./SaveCard";

type Field = {
  key: string; plain: boolean; kind: "select" | "text" | "textarea" | "checks"; label: string; hint: string; required: boolean;
  options: SetupOption[]; initial: string; showIf: Record<string, string>; pick: number;
};

// Each setup key as one shape: the plain list is a select labelled by its key (station, noir); a field keeps its kind.
// The engine appends its own Difficulty select to every game's fields.
function fieldsOf(g: GameInfo): Field[] {
  return Object.entries(g.setup).map(([key, spec]) => {
    if (Array.isArray(spec)) return { key, plain: true, kind: "select", label: key.charAt(0).toUpperCase() + key.slice(1), hint: "", required: false, options: spec, initial: spec[0]?.id ?? "", showIf: {}, pick: 0 };
    const f = spec as SetupField;
    const options = (f.options ?? []).map((o) => (typeof o === "string" ? { id: o, name: o } : o));
    const kind = f.kind ?? "select";
    const initial = f.default ?? (kind === "select" ? options[0]?.id ?? "" : "");
    return { key, plain: false, kind, label: f.label || key, hint: f.hint ?? "", required: !!f.required, options, initial, showIf: f.show_if ?? {}, pick: f.pick ?? 0 };
  });
}

// B79: the ticked mods are remembered per browser, per game (the owner, 11-08)
const modsKey = (game: string) => `ta.mods.${game}`;
function readTicked(game: string): string[] {
  try {
    return JSON.parse(localStorage.getItem(modsKey(game)) ?? "[]");
  } catch {
    return [];
  }
}
function writeTicked(game: string, files: string[]) {
  try {
    localStorage.setItem(modsKey(game), JSON.stringify(files));
  } catch {
    /* storage blocked: remembered for this page only */
  }
}

/** A game's own page: New game first, then its saved games (most recently played first) (the owner, 11-08). */
export function GamePage({ name }: { name: string }) {
  const [game, setGame] = useState<GameInfo | null>(null);
  const [saves, setSaves] = useState<InstanceSummary[] | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [open, setOpen] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [missingGame, setMissingGame] = useState(false);
  const [mods, setMods] = useState<ModInfo[]>([]);
  const [ticked, setTicked] = useState<string[]>(() => readTicked(name));
  const upRef = useRef<HTMLInputElement>(null);
  const loadMods = useCallback(() => api.mods(name).then(setMods).catch(() => setMods([])), [name]);
  useEffect(() => { loadMods(); }, [loadMods]);

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

  const all = fieldsOf(game);
  const valueOf = (f: Field) => values[f.key] ?? f.initial;
  // a field with show_if is for one class (its kit, its Expertise): shown and sent only when that class is picked (B92)
  const fields = all.filter((f) => Object.entries(f.showIf).every(([k, v]) => { const o = all.find((x) => x.key === k); return o ? valueOf(o) === v : false; }));
  const tickedOf = (f: Field) => valueOf(f).split(",").filter(Boolean);
  const missing = fields.filter((f) => (f.required && !valueOf(f).trim()) || (f.kind === "checks" && f.pick > 0 && tickedOf(f).length !== f.pick));
  const usable = mods.filter((m) => !m.error && m.kind !== "deck");
  const on = ticked.filter((f) => usable.some((m) => m.file === f));
  const toggle = (file: string) => {
    const next = on.includes(file) ? on.filter((x) => x !== file) : [...on, file];
    setTicked(next);
    writeTicked(name, next);
  };

  async function download(file: string) {
    try {
      const text = await api.modText(name, file);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([text], { type: "text/yaml" }));
      a.download = file;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) {
      setErr(String(e));
    }
  }
  async function remove(file: string) {
    if (!confirm(`Delete the mod ${file} from this server? Saves made with it keep its text.`)) return;
    try {
      await api.deleteMod(name, file);
      loadMods();
    } catch (e) {
      setErr(String(e));
    }
  }
  async function upload(f: File) {
    setErr(null);
    try {
      await api.putMod(name, f.name, await f.text());
      loadMods();
    } catch (e) {
      const m = String(e).match(/^Error: 400 ([\s\S]*)$/);
      let msg = String(e);
      if (m) { try { msg = JSON.parse(m[1]).detail ?? m[1]; } catch { msg = m[1]; } }
      setErr(`Could not upload ${f.name}: ${msg}`);
    } finally {
      if (upRef.current) upRef.current.value = "";
    }
  }

  async function start() {
    setErr(null);
    try {
      const shown = Object.fromEntries(fields.map((f) => [f.key, valueOf(f)]));   // what the fields show, selects' defaults included
      const v = await api.create(game!.name, shown, on);
      location.hash = `#/g/${v.id}`;
    } catch (e) {
      // a refusal (400) shows its own plain line, not the status and the JSON (B45: a name the city already has)
      const m = String(e).match(/^Error: 400 ([\s\S]*)$/);
      let msg = String(e);
      if (m) { try { msg = JSON.parse(m[1]).detail ?? m[1]; } catch { msg = m[1]; } }
      setErr(msg);
    }
  }

  const newGame = (
    <section className="new-game" key="new">
      <h2>New game</h2>
      <div className="game">
        {fields.map((f) => { const Wrap = f.kind === "checks" ? "div" : "label"; return (
          <Wrap key={f.key} className="setup-field">
            <span>{f.label}</span>
            {f.kind === "select" ? (
              <select value={valueOf(f)} onChange={(e) => setValues({ ...values, [f.key]: e.target.value })}>
                {f.options.map((o) => (
                  <option key={o.id} value={o.id}>{o.name}</option>
                ))}
              </select>
            ) : f.kind === "checks" ? (
              <span className="setup-checks">
                {f.options.map((o) => {
                  const on = tickedOf(f).includes(o.id);
                  const full = !on && f.pick > 0 && tickedOf(f).length >= f.pick;
                  return (
                    <button type="button" key={o.id} className={`check-chip${on ? " on" : ""}`} disabled={full} aria-pressed={on}
                      onClick={() => setValues({ ...values, [f.key]: (on ? tickedOf(f).filter((x) => x !== o.id) : [...tickedOf(f), o.id]).join(",") })}>
                      {o.name}
                    </button>
                  );
                })}
              </span>
            ) : f.kind === "textarea" ? (
              <textarea rows={4} value={valueOf(f)} placeholder={f.hint || undefined} onChange={(e) => setValues({ ...values, [f.key]: e.target.value })} />
            ) : (
              <input type="text" value={valueOf(f)} placeholder={f.hint || undefined} onChange={(e) => setValues({ ...values, [f.key]: e.target.value })} />
            )}
          </Wrap>
        ); })}
        {usable.length > 0 && (
          <div className="setup-field mods-slot">
            <span>Mods</span>
            <span className="mod-checks">
              {usable.map((m) => (
                <label key={m.file} className="mod-check" title={m.file}>
                  <input type="checkbox" checked={m.forced || on.includes(m.file)} disabled={m.forced} onChange={() => toggle(m.file)} />
                  <span><strong>{m.name}</strong>{m.forced ? <span className="muted"> (always on in this game)</span> : null}{m.about ? <span className="muted"> — {m.about}</span> : null}</span>
                </label>
              ))}
            </span>
          </div>
        )}
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
      <p className="muted small game-counts">
        {countsLine(game.saves, game.deaths ?? 0)}
        {(game.deaths ?? 0) > 0 && (
          <>
            {" · "}
            <a className="link" href={`#/graveyard/${game.name}`}>Graveyard</a>
          </>
        )}
      </p>
      {err && <div className="error">{err}</div>}
      {saves.length ? [newGame, saved] : [newGame]}
      <section className="mods-list">
        <h2>Mods</h2>
        <p className="muted small">YAML files that patch this game's content, prompts and starting state when a new game starts (the shape: notes/content/fantasy/mods/example.yml). A deck is a file a mod swaps in whole (cards, bookings, the house file, the narrator's and the referee's words); it is uploaded and downloaded here like a mod.</p>
        {mods.length > 0 && (
          <ul className="mod-files">
            {mods.map((m) => (
              <li key={m.file}>
                <span className="mod-name">{m.name}</span> <span className="muted small">{m.kind === "deck" ? "deck · " : ""}{m.file} · {m.size} bytes · {ago(new Date(m.modified * 1000).toISOString())}</span>
                {m.kind === "deck" && m.holds && <div className="muted small">Holds: {m.holds.join(", ")}</div>}
                {m.kind !== "deck" && m.decks && m.decks.length > 0 && <div className="muted small">Its decks: {m.decks.join(", ")}</div>}
                {m.error && <div className="error small">Not offered: {m.error}</div>}
                {m.about && !m.error && <div className="muted small">{m.about}</div>}
                <span className="mod-actions">
                  <button onClick={() => download(m.file)}>download</button>
                  <button onClick={() => remove(m.file)}>delete</button>
                </span>
              </li>
            ))}
          </ul>
        )}
        <input ref={upRef} type="file" accept=".yml,.yaml" hidden onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
        <button onClick={() => upRef.current?.click()}>Upload a mod or a deck</button>
      </section>
    </div>
  );
}
