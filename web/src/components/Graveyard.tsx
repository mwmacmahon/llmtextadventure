import { useEffect, useState, type ReactNode } from "react";
import { api, type Character, type Gallery, type Grave, type GraveCard } from "../api";
import { Panels } from "./Panels";
import { Stone } from "./Stone";

/** Where and when: "Day 3, The Drowned Lantern". */
export function whereWhen(g: Pick<Grave, "day" | "place" | "clock">): string {
  const when = g.day != null ? `Day ${g.day}` : g.clock;
  return [when, g.place].filter(Boolean).join(", ");
}

const SCORE_LABELS: [string, string][] = [
  ["level", "Level"], ["xp", "XP"], ["renown_word", "Renown"], ["gold", "Gold"], ["quests_done", "Quests done"], ["days", "Days"], ["turns", "Turns"],
];

/** The graveyard: every death, per character, each a stone; a stone opens its card. */
export function Graveyard({ game }: { game: string | null }) {
  const [gal, setGal] = useState<Gallery | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    const load = () => api.graveyard(game ?? undefined).then(setGal).catch((e) => setErr(String(e)));
    load();
    addEventListener("ta-dev", load);
    return () => removeEventListener("ta-dev", load);
  }, [game]);

  if (!gal) return <div className="lobby">{err ?? "loading…"}</div>;
  const games = [...new Map(gal.characters.map((c) => [c.game, c.game_title])).entries()];
  return (
    <div className="lobby graveyard">
      <h1 className="pixel-heading">Graveyard</h1>
      <p className="muted">
        Every death, kept for good. Undoing a death does not dig it up: it stands here, cracked.
        {gal.deaths > 0 && ` ${gal.deaths} ${gal.deaths === 1 ? "death" : "deaths"} so far.`}
      </p>
      {(games.length > 1 || game) && (
        <nav className="grave-filter">
          <a className={!game ? "on" : ""} href="#/graveyard">All games</a>
          {games.map(([name, title]) => (
            <a key={name} className={game === name ? "on" : ""} href={`#/graveyard/${name}`}>{title}</a>
          ))}
        </nav>
      )}
      {err && <div className="error">{err}</div>}
      {gal.characters.length === 0 && <p className="muted">Nobody has died here yet.</p>}
      {gal.characters.map((c) => (
        <CharacterRow key={`${c.game}/${c.key}`} c={c} onOpen={setOpen} showGame={!game} />
      ))}
      {open && <GraveSheet id={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

function CharacterRow({ c, onOpen, showGame }: { c: Character; onOpen: (id: string) => void; showGame: boolean }) {
  const best = [c.best.level != null && `level ${c.best.level}`, c.best.turns != null && `${c.best.turns} ${c.best.turns === 1 ? "turn" : "turns"}`, c.best.days != null && `day ${c.best.days}`]
    .filter(Boolean)
    .join(", ");
  return (
    <section className="character">
      <h2>
        <span className="pixel-name">{c.name}</span>
        <span className="muted small">
          {showGame ? `${c.game_title} · ` : ""}
          {c.deaths === 1 ? "1 death" : `${c.deaths} deaths`}
          {best ? ` · best run: ${best}` : ""}
        </span>
      </h2>
      <ol className="stones">
        {c.graves.map((g) => (
          <li key={g.id}>
            <button className={`stone-tile${g.undone ? " undone" : ""}`} onClick={() => onOpen(g.id)} title="Open this grave">
              <Stone game={g.game} name={g.character} seed={g.id} undone={g.undone} scale={3} />
              <span className="stone-cause">{g.cause}</span>
              <span className="muted small">{g.line.find((x) => x.label === "character")?.value ?? ""}</span>
              <span className="muted small">{whereWhen(g)}</span>
              {g.undone && <span className="undone-mark small">undone</span>}
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}

/** A gravestone's card: the stone, the cause and a line, the epitaph, the score, what she died holding; Continue or New game. */
function GraveSheet({ id, onClose }: { id: string; onClose: () => void }) {
  const [g, setG] = useState<GraveCard | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    api.grave(id).then(setG).catch((e) => setErr(String(e)));
  }, [id]);
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    addEventListener("keydown", esc);
    return () => removeEventListener("keydown", esc);
  }, [onClose]);
  return (
    <div className="grave-sheet-backdrop" onClick={onClose}>
      <div className="grave-sheet" role="dialog" aria-label="Gravestone" onClick={(e) => e.stopPropagation()}>
        <div className="save-card-head">
          <span className="spacer" />
          <button className="link" onClick={onClose}>close</button>
        </div>
        {err && <div className="error small">{err}</div>}
        {!g ? <div className="muted small">loading…</div> : <DeathCardBody g={g} />}
      </div>
    </div>
  );
}

/** The card's body, shared with the play page's death card. `actions` replaces Continue / New game there. */
export function DeathCardBody({ g, actions }: { g: GraveCard; actions?: ReactNode }) {
  const score = SCORE_LABELS.filter(([k]) => g.score[k] != null && g.score[k] !== "");
  return (
    <div className="death-card">
      <div className="death-card-top">
        <Stone game={g.game} name={g.character} seed={g.id} undone={g.undone} scale={4} />
        <div className="death-card-words">
          <h2 className="pixel-heading">Here lies {g.character}</h2>
          <div className="muted small">{g.line.map((x) => x.value).join(" · ")}</div>
          <div className="death-cause">{g.cause.charAt(0).toUpperCase() + g.cause.slice(1)}.</div>
          <div className="muted small">{whereWhen(g)}{g.undone ? " · undone, and still standing" : ""}</div>
          {g.death_line && <p className="death-line">{g.death_line}</p>}
        </div>
      </div>
      {g.epitaph && <blockquote className="epitaph">{g.epitaph}</blockquote>}
      {score.length > 0 && (
        <dl className="score">
          {score.map(([k, label]) => (
            <div key={k}>
              <dt>{label}</dt>
              <dd>{String(g.score[k])}</dd>
            </div>
          ))}
        </dl>
      )}
      <div className="continue-row">
        {actions ?? (
          <>
            {g.save_stands && <a className="button-like primary" href={`#/g/${g.instance_id}`}>Continue that game</a>}
            <a className="button-like" href={`#/games/${g.game}`}>New game</a>
          </>
        )}
      </div>
      {g.ui && g.ui.panels.length > 0 && (
        <details className="card-state">
          <summary className="muted small">What {g.character} died holding</summary>
          <Panels panels={g.ui.panels} readOnly />
        </details>
      )}
    </div>
  );
}
