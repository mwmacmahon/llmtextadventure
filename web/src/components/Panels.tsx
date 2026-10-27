import { useState } from "react";
import type { CommandSpec, EntityCard, Widget } from "../api";

type OnCommand = (command: string, args: Record<string, unknown>) => void;

export function Panels({ panels, onChoice, onCommand, busy }: { panels: Widget[]; onChoice?: OnCommand; onCommand?: OnCommand; busy?: boolean }) {
  return (
    <div className="panels">
      {panels.map((w, i) => (
        <Panel key={i} w={w} onChoice={onChoice} onCommand={onCommand} busy={busy} />
      ))}
    </div>
  );
}

function Panel({ w, onChoice, onCommand, busy }: { w: Widget; onChoice?: OnCommand; onCommand?: OnCommand; busy?: boolean }) {
  switch (w.type) {
    case "commands":
      if (!w.items.length) return null;
      return (
        <section className="panel">
          {w.title && <h3>{w.title}</h3>}
          <div className="commands">
            {w.items.map((c) => (
              <CommandRow key={c.id} spec={c} onRun={onCommand} busy={busy} />
            ))}
          </div>
        </section>
      );
    case "status_strip":
      return (
        <div className="strip">
          {w.chips.map((c) => (
            <span key={c.label} className="chip">
              <span className="chip-label">{c.label}</span>
              <span className="chip-value">{c.value}</span>
            </span>
          ))}
        </div>
      );
    case "meter": {
      const pct = Math.max(0, Math.min(100, ((w.value - w.min) / (w.max - w.min)) * 100));
      return (
        <section className="panel">
          <h3>
            {w.label} <span className="muted">{w.tier ?? ""}</span>
          </h3>
          <div className="meter">
            <div className="meter-fill" style={{ width: `${pct}%` }} />
            {w.thresholds.map((t) => (
              <div key={t} className="meter-tick" style={{ left: `${((t - w.min) / (w.max - w.min)) * 100}%` }} />
            ))}
          </div>
        </section>
      );
    }
    case "table":
      return (
        <section className="panel">
          <h3>{w.title}</h3>
          <table>
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
          </table>
        </section>
      );
    case "list":
      return (
        <section className="panel">
          <h3>{w.title}</h3>
          <ul className="kv">
            {w.items.map((c) => (
              <li key={c.label}>
                <span className="muted">{c.label}</span>
                <span>{c.value}</span>
              </li>
            ))}
          </ul>
        </section>
      );
    case "entity_cards":
      return (
        <section className="panel">
          <h3>{w.title}</h3>
          <div className="cards">
            {w.cards.map((c) => (
              <Card key={c.id} card={c} />
            ))}
          </div>
        </section>
      );
    case "log":
      return (
        <section className="panel">
          <h3>{w.title}</h3>
          <ul className="log">
            {w.lines.map((l, i) => (
              <li key={i}>{l}</li>
            ))}
          </ul>
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

function CommandRow({ spec, onRun, busy }: { spec: CommandSpec; onRun?: OnCommand; busy?: boolean }) {
  const [args, setArgs] = useState<Record<string, string>>(() => Object.fromEntries(spec.params.map((p) => [p.name, p.options[0]?.id ?? ""])));
  const ready = spec.params.every((p) => args[p.name]);
  return (
    <div className="command-row" title={spec.hint}>
      <span className="command-label">
        {spec.label}
        {spec.mode === "narrated" && <span className="muted small"> · narrated</span>}
      </span>
      {spec.params.map((p) => (
        <select key={p.name} value={args[p.name] ?? ""} onChange={(e) => setArgs({ ...args, [p.name]: e.target.value })} aria-label={p.label}>
          {p.options.map((o) => (
            <option key={o.id} value={o.id}>
              {o.label}
            </option>
          ))}
        </select>
      ))}
      <button className="small-btn" disabled={busy || !ready} onClick={() => onRun?.(spec.id, args)}>
        run
      </button>
    </div>
  );
}

function Card({ card }: { card: EntityCard }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={`card ${open ? "open" : ""}`} onClick={() => setOpen(!open)}>
      <div className="card-head">
        <div>
          <div className="card-title">{card.title}</div>
          {card.subtitle && <div className="muted small">{card.subtitle}</div>}
        </div>
        <div className="badges">
          {card.badges.map((b) => (
            <span key={b.label} className="badge" title={b.label}>
              {b.value}
            </span>
          ))}
        </div>
      </div>
      {open && (
        <div className="card-body">
          <ul className="kv">
            {card.details.map((d) => (
              <li key={d.label}>
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
