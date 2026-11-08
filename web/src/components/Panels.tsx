import { useState } from "react";
import type { Chip, CommandSpec, EntityCard, MeterWidget, Widget } from "../api";

type OnCommand = (command: string, args: Record<string, unknown>) => void;

// B50 (D167): after the ending only the console commands (mode "engine": no story, no clock) still run, so a Journal can be read.
export function Panels({ panels, onChoice, onCommand, busy, ended }: { panels: Widget[]; onChoice?: OnCommand; onCommand?: OnCommand; busy?: boolean; ended?: boolean }) {
  return (
    <div className="panels">
      {panels.map((w, i) => (
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

function ChipView({ c }: { c: Chip }) {
  return (
    <span className={`chip${c.tone ? ` chip-${c.tone}` : ""}`}>
      {c.label && <span className="chip-label">{c.label}</span>}
      <span className="chip-value">{c.value}</span>
    </span>
  );
}

function CommandRow({ spec, onRun, busy }: { spec: CommandSpec; onRun?: OnCommand; busy?: boolean }) {
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
