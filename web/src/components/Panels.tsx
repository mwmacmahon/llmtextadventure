import { useEffect, useState } from "react";
import type { Chip, CommandSpec, EntityCard, MeterWidget, Widget } from "../api";

type OnCommand = (command: string, args: Record<string, unknown>) => void;

// B50 (D167): after the ending only the console commands (mode "engine": no story, no clock) still run, so a Journal can be read.
// readOnly (the save card in the lobby, B75): the state as the player sees it, with nothing to run (no commands, no choices).
export function Panels({ panels, onChoice, onCommand, busy, ended, readOnly, place }: { panels: Widget[]; onChoice?: OnCommand; onCommand?: OnCommand; busy?: boolean; ended?: boolean; readOnly?: boolean; place?: "side" | "main" }) {
  // `place` picks the column's panels (a widget with no place is the side's); the pinned ones come first, in a block that
  // stays at the top of the column while the rest scrolls (the clown's girl in training).
  // B261: the game's timeline (its log) is never in a column: the Timeline overlay shows it, by day
  const mine = (place ? panels.filter((w) => (w.place || "side") === place) : panels).filter((w) => !(w.type === "log" && w.timeline));
  const shown = readOnly ? mine.filter((w) => w.type !== "commands" && w.type !== "choices") : mine;
  const pinned = shown.filter((w) => w.pinned);
  const rest = shown.filter((w) => !w.pinned);
  return (
    <div className="panels">
      {pinned.length > 0 && (
        <div className="pinned">
          {pinned.map((w, i) => (
            <Panel key={`p${i}`} w={w} onChoice={onChoice} onCommand={onCommand} busy={busy} ended={ended} />
          ))}
        </div>
      )}
      {rest.map((w, i) => (
        <Panel key={i} w={w} onChoice={onChoice} onCommand={onCommand} busy={busy} ended={ended} />
      ))}
    </div>
  );
}

function Panel({ w, onChoice, onCommand, busy, ended }: { w: Widget; onChoice?: OnCommand; onCommand?: OnCommand; busy?: boolean; ended?: boolean }) {
  switch (w.type) {
    case "commands":
      if (!w.items.length) return null;
      return (
        <section className="panel">
          {w.title && <h3>{w.title}</h3>}
          <div className="commands">
            {w.items.map((c) => (
              <CommandRow key={c.id} spec={c} onRun={onCommand} busy={busy || (ended && c.mode !== "engine")} />
            ))}
          </div>
        </section>
      );
    case "status_strip":
      return (
        <div className="strip">
          {w.chips.map((c, i) => (
            <ChipView key={`${c.label}-${i}`} c={c} />
          ))}
        </div>
      );
    case "meter":
      return (
        <section className="panel">
          <MeterBody w={w} />
        </section>
      );
    case "meter_group":
      return (
        <section className="panel">
          {w.title && <h3>{w.title}</h3>}
          <div className="meter-group">
            {w.meters.map((m) => (
              <div key={m.label} className="meter-cell">
                <MeterBody w={m} small />
              </div>
            ))}
          </div>
        </section>
      );
    case "table":
      return (
        <section className="panel">
          <h3>{w.title}</h3>
          {w.rows.length === 0 ? <div className="muted small">Nothing yet.</div> : <table>
            <thead>
              <tr>
                {w.columns.map((c) => (
                  <th key={c}>{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {w.rows.map((r, i) => (
                <tr key={i}>
                  {r.map((c, j) => (
                    <td key={j} className={`tone-${c.tone}`}>
                      {c.text}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>}
        </section>
      );
    case "list":
      if (w.fold) return <FoldedList w={w} />;
      return (
        <section className="panel">
          <h3>{w.title}</h3>
          {w.items.length === 0 ? (
            <div className="muted small">Nothing yet.</div>
          ) : w.layout === "grid" ? (
            <div className="tiles">
              {w.items.map((c, i) => (
                <div key={`${c.label}-${i}`} className={`tile${c.label ? "" : " tile-solo"}${c.tone ? ` tone-${c.tone}` : ""}`}>
                  {c.label && <span className="tile-label">{c.label}</span>}
                  <span className="tile-value">{c.value}</span>
                </div>
              ))}
            </div>
          ) : w.layout === "stack" ? (
            <ul className="stack">
              {w.items.map((c, i) => (
                <li key={`${c.label}-${i}`} className={c.tone ? `tone-${c.tone}` : undefined}>
                  {c.label && <span className="stack-label">{c.label}</span>}
                  {c.value && <span className="stack-value">{c.value}</span>}
                </li>
              ))}
            </ul>
          ) : (
            <ul className="kv">
              {w.items.map((c, i) => (
                <li key={`${c.label}-${i}`}>
                  <span className="muted">{c.label}</span>
                  <span className={c.tone ? `tone-${c.tone}` : undefined}>{c.value}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      );
    case "quests":
      return (
        <section className="panel">
          <h3>{w.title}</h3>
          {w.rows.length === 0 ? <div className="muted small">Nothing yet.</div> : <ul className="quests">
            {w.rows.map((r, i) => (
              <li key={`${r.title}-${i}`}>
                <div className="quest-head">
                  <span className="quest-title">{r.title}</span>
                  <span className={`quest-standing tone-${r.tone}`}>{r.standing}</span>
                </div>
                {r.line && <div className="quest-line">{r.line}</div>}
                {r.giver && <div className="quest-giver muted">from {r.giver}</div>}
              </li>
            ))}
          </ul>}
        </section>
      );
    case "entity_cards":
      return (
        <section className="panel">
          <h3>{w.title}</h3>
          {w.cards.length === 0 ? <div className="muted small">Nothing yet.</div> : <div className="cards">
            {w.cards.map((c) => (
              <Card key={c.id} card={c} />
            ))}
          </div>}
        </section>
      );
    case "log":
      return (
        <section className="panel">
          <h3>{w.title}</h3>
          {w.lines.length === 0 ? <div className="muted small">Nothing yet.</div> : <ul className="log">
            {w.lines.map((l, i) => (
              <li key={i}>{l}</li>
            ))}
          </ul>}
        </section>
      );
    case "choices":
      return (
        <section className="panel">
          {w.title && <h3>{w.title}</h3>}
          <div className="choices">
            {w.choices.map((c) => (
              <button key={c.label} onClick={() => onChoice?.(c.command, c.args)}>
                {c.label}
              </button>
            ))}
          </div>
        </section>
      );
  }
}

// B261: a long list (the Journal) shows its first `fold` lines (the newest: the game sends them newest first) and the rest
// behind "See more", which unfolds them in place.
type ListWidget = Extract<Widget, { type: "list" }>;
export function FoldedList({ w, open: startOpen }: { w: ListWidget; open?: boolean }) {
  const [open, setOpen] = useState(!!startOpen);
  const n = w.fold ?? 0;
  const shown = open || !n ? w.items : w.items.slice(0, n);
  const more = w.items.length - shown.length;
  return (
    <section className="panel">
      <h3>{w.title}</h3>
      {w.items.length === 0 ? (
        <div className="muted small">Nothing yet.</div>
      ) : (
        <ul className="stack">
          {shown.map((c, i) => (
            <li key={`${c.label}-${i}`} className={c.tone ? `tone-${c.tone}` : undefined}>
              {c.label && <span className="stack-label">{c.label}</span>}
              {c.value && <span className="stack-value">{c.value}</span>}
            </li>
          ))}
        </ul>
      )}
      {more > 0 && <button className="link small see-more" onClick={() => setOpen(true)}>See more ({more} older)</button>}
      {open && n > 0 && w.items.length > n && <button className="link small see-more" onClick={() => setOpen(false)}>See less</button>}
    </section>
  );
}

// B261: the Timeline, an in-page overlay over the story: the game's log by day (today open, earlier days folded) and the
// Journal, read-only; a tap outside the sheet, the close button or Escape closes it.
export function Timeline({ panels, tab, onTab, onClose }: { panels: Widget[]; tab: "timeline" | "journal"; onTab: (t: "timeline" | "journal") => void; onClose: () => void }) {
  const logs = panels.filter((w): w is Extract<Widget, { type: "log" }> => w.type === "log" && !!w.timeline);
  const journal = panels.find((w): w is ListWidget => w.type === "list" && !!w.journal);
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    addEventListener("keydown", esc);
    return () => removeEventListener("keydown", esc);
  }, [onClose]);
  const lines = logs.flatMap((w) => w.lines);
  const days: { day: string; lines: string[] }[] = [];
  for (const l of lines) {
    const m = l.match(/^(Day \d+)\s+(.*)$/);
    const day = m ? m[1] : "Earlier";
    const text = m ? m[2] : l;
    if (!days.length || days[days.length - 1].day !== day) days.push({ day, lines: [] });
    days[days.length - 1].lines.push(text);
  }
  return (
    <div className="overlay" onClick={onClose} role="presentation">
      <div className="overlay-sheet" role="dialog" aria-modal="true" aria-label="Timeline and journal" onClick={(e) => e.stopPropagation()}>
        <div className="overlay-head">
          <div className="overlay-tabs" role="tablist">
            <button role="tab" aria-selected={tab === "timeline"} className={tab === "timeline" ? "on" : ""} onClick={() => onTab("timeline")}>Timeline</button>
            {journal && <button role="tab" aria-selected={tab === "journal"} className={tab === "journal" ? "on" : ""} onClick={() => onTab("journal")}>{journal.title}</button>}
          </div>
          <button className="link overlay-close" onClick={onClose} aria-label="Close">close</button>
        </div>
        <div className="overlay-body">
          {tab === "journal" && journal ? (
            <FoldedList w={{ ...journal, fold: 0 }} />
          ) : days.length === 0 ? (
            <div className="muted small">Nothing has happened yet.</div>
          ) : (
            [...days].reverse().map((d, i) => (
              <details key={d.day} className="day" open={i === 0}>
                <summary>{d.day} <span className="muted small">· {d.lines.length} {d.lines.length === 1 ? "entry" : "entries"}</span></summary>
                <ul className="log">
                  {d.lines.map((l, k) => (
                    <li key={k}>{l}</li>
                  ))}
                </ul>
              </details>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

function MeterBody({ w, small }: { w: MeterWidget; small?: boolean }) {
  const span = w.max - w.min || 1;
  const pct = Math.max(0, Math.min(100, ((w.value - w.min) / span) * 100));
  const chips = w.chips ?? [];
  return (
    <>
      <div className={`meter-head${small ? " small" : ""}`}>
        <span className="meter-label">{w.label}</span>
        {w.tier && <span className={`meter-tier${w.tone ? ` tone-${w.tone}` : ""}`}>{w.tier}</span>}
        {w.text && <span className="meter-text">{w.text}</span>}
      </div>
      <div className={`meter${small ? " meter-small" : ""}`}>
        <div className={`meter-fill${w.tone ? ` fill-${w.tone}` : ""}`} style={{ width: `${pct}%` }} />
        {w.thresholds.map((t) => (
          <div key={t} className="meter-tick" style={{ left: `${((t - w.min) / span) * 100}%` }} />
        ))}
      </div>
      {chips.length > 0 && (
        <div className="meter-chips">
          {chips.map((c, i) => (
            <ChipView key={`${c.label}-${i}`} c={c} />
          ))}
        </div>
      )}
    </>
  );
}

export function ChipView({ c }: { c: Chip }) {
  return (
    <span className={`chip${c.tone ? ` chip-${c.tone}` : ""}`}>
      {c.label && <span className="chip-label">{c.label}</span>}
      <span className="chip-value">{c.value}</span>
    </span>
  );
}

// The level-up screen (B92): what is new, the hit points, score points to spend by clicking the scores, cards to pick,
// Confirm. Nothing lands until Confirm.
function PanelCommand({ spec, onRun, busy }: { spec: CommandSpec; onRun?: OnCommand; busy?: boolean }) {
  const p = spec.panel!;
  const [open, setOpen] = useState(false);
  const [spent, setSpent] = useState<string[]>([]);
  const [cards, setCards] = useState<string[]>([]);
  const ready = spent.length === p.points && cards.length === p.pick;
  return (
    <div className="command-row command-panel">
      <button className="command-btn" disabled={busy} onClick={() => setOpen(!open)} aria-expanded={open}>{spec.label}</button>
      {open && (
        <div className="level-panel">
          <h4>{p.title}</h4>
          <ul>
            {p.lines.map((c, i) => (
              <li key={i}><strong>{c.label}</strong>{c.value ? ` — ${c.value}` : ""}</li>
            ))}
          </ul>
          {p.points > 0 && (
            <>
              <div className="muted small">Raise scores: {p.points - spent.length} of {p.points} left{spent.length ? <> · <button className="link" onClick={() => setSpent([])}>reset</button></> : null}</div>
              <div className="level-stats">
                {p.stats.map((o) => {
                  const n = spent.filter((x) => x === o.id).length;
                  return (
                    <button key={o.id} className={`check-chip${n ? " on" : ""}`} disabled={busy || (spent.length >= p.points) || n >= p.per_stat}
                      onClick={() => setSpent([...spent, o.id])}>{o.label}{n ? ` +${n}` : ""}</button>
                  );
                })}
              </div>
            </>
          )}
          {p.pick > 0 && (
            <>
              <div className="muted small">Pick {p.pick}</div>
              <div className="level-cards">
                {p.cards.map((c) => {
                  const on = cards.includes(c.label);
                  return (
                    <button key={c.label} className={`check-chip${on ? " on" : ""}`} disabled={busy || (!on && cards.length >= p.pick)}
                      onClick={() => setCards(on ? cards.filter((x) => x !== c.label) : [...cards, c.label])}>{c.value}</button>
                  );
                })}
              </div>
            </>
          )}
          <button className="primary" disabled={busy || !ready} onClick={() => { onRun?.(spec.id, { stats: spent.join(","), cards: cards.join(",") }); setOpen(false); setSpent([]); setCards([]); }}>
            {p.confirm}
          </button>
        </div>
      )}
    </div>
  );
}

function CommandRow({ spec, onRun, busy }: { spec: CommandSpec; onRun?: OnCommand; busy?: boolean }) {
  return spec.panel && spec.enabled !== false ? <PanelCommand key="panel" spec={spec} onRun={onRun} busy={busy} /> : <SelectCommand key="select" spec={spec} onRun={onRun} busy={busy} />;
}

function SelectCommand({ spec, onRun, busy }: { spec: CommandSpec; onRun?: OnCommand; busy?: boolean }) {
  const [args, setArgs] = useState<Record<string, string>>(() => Object.fromEntries(spec.params.map((p) => [p.name, p.options[0]?.id ?? ""])));
  const ready = spec.params.every((p) => args[p.name]);
  const enabled = spec.enabled !== false;
  return (
    <div className={`command-row${enabled ? "" : " command-off"}`} title={spec.hint + (spec.mode === "narrated" ? " (played in the story)" : "")}>
      <button className="command-btn" disabled={busy || !ready || !enabled} onClick={() => onRun?.(spec.id, args)}>
        {spec.label}
      </button>
      {enabled &&
        spec.params.map((p) => (
          <label key={p.name} className="command-param">
            {p.label !== spec.label && <span className="muted small">{p.label}</span>}
            <select value={args[p.name] ?? ""} onChange={(e) => setArgs({ ...args, [p.name]: e.target.value })} aria-label={p.label}>
              {p.options.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
        ))}
    </div>
  );
}

function Card({ card }: { card: EntityCard }) {
  const [open, setOpen] = useState(false);
  const more = card.details.length > 0 || card.notes.length > 0;
  return (
    <div className={`card ${open ? "open" : ""}${more ? "" : " card-flat"}`} onClick={() => more && setOpen(!open)}>
      <div className="card-head">
        <div>
          <div className="card-title">{card.title}</div>
          {card.subtitle && <div className="muted small">{card.subtitle}</div>}
        </div>
        <div className="badges">
          {card.badges.map((b, i) => (
            <span key={`${b.label}-${i}`} className={`badge${b.tone ? ` chip-${b.tone}` : ""}`} title={b.label}>
              {b.value}
            </span>
          ))}
        </div>
      </div>
      {open && more && (
        <div className="card-body">
          <ul className="kv">
            {card.details.map((d, i) => (
              <li key={`${d.label}-${i}`}>
                <span className="muted">{d.label}</span>
                <span>{d.value}</span>
              </li>
            ))}
          </ul>
          {card.notes.length > 0 && (
            <ul className="notes">
              {card.notes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
