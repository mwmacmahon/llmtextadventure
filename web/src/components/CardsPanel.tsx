/**
 * A hand of cards (docs/PLANNER-CONTRACT.md section 3; C162): each with art, words, tags and one action, folding and
 * unfolding by its corner button. Usually placed in a pop-out, so the button under the input box opens it as a window.
 * The player's folds are kept in the browser (per card id); the engine says how each card starts.
 */
import { useState } from "react";
import type { CardsWidget, PlanCard } from "../api";
import { Portrait } from "./portraitArt";
import "./planner.css";

type OnCommand = (command: string, args: Record<string, unknown>) => void;
const FOLD_KEY = "ta-card-folds";
const readFolds = (): Record<string, boolean> => { try { return JSON.parse(localStorage.getItem(FOLD_KEY) || "{}"); } catch { return {}; } };

export function CardsPanel({ widget, onCommand, busy }: { widget: CardsWidget; onCommand?: OnCommand; busy?: boolean }) {
  const [folds, setFolds] = useState<Record<string, boolean>>(readFolds);
  const toggle = (id: string, now: boolean) => {
    const next = { ...folds, [id]: !now }; setFolds(next);
    try { localStorage.setItem(FOLD_KEY, JSON.stringify(next)); } catch { /* the browser may refuse; folds are a convenience */ }
  };
  return (
    <section className="panel cards-panel">
      <h3>{widget.title}</h3>
      {widget.sub && <div className="muted small">{widget.sub}</div>}
      <div className="plan-cards">
        {widget.cards.map((c) => {
          const folded = c.id in folds ? folds[c.id] : !!c.folded;
          return <Card key={c.id} c={c} folded={folded} onFold={() => toggle(c.id, folded)} onCommand={onCommand} busy={busy} />;
        })}
      </div>
      {widget.foot && <div className="muted small">{widget.foot}</div>}
    </section>
  );
}

function Card({ c, folded, onFold, onCommand, busy }: { c: PlanCard; folded: boolean; onFold: () => void; onCommand?: OnCommand; busy?: boolean }) {
  const [picked, setChoice] = useState<string>("");
  const open = c.pick?.options.filter((o) => !o.disabled) ?? [];
  const choice = open.some((o) => o.id === picked) ? picked : open[0]?.id ?? "";   // a stale pick falls back to the first one still open
  const cls = ["plan-card", folded ? "folded" : "", c.locked ? "locked" : "", c.done ? "done" : ""].filter(Boolean).join(" ");
  return (
    <article className={cls}>
      <div className="plan-card-top">
        {c.art && <Portrait art={c.art} size={folded ? 56 : 88} alt={`${c.title}`} />}
        <div className="plan-card-name">
          <div className="pixel-name-sm">{c.title}</div>
          {c.meta && <div className="muted small">{c.meta}</div>}
          {c.locked && <div className="plan-lockline">LOCKED</div>}
        </div>
        <button type="button" className="plan-fold" aria-expanded={!folded} aria-label={folded ? "Unfold the card" : "Fold the card"} onClick={onFold}>{folded ? "v" : "^"}</button>
      </div>
      {!folded && (
        <>
          <div className="plan-card-body">
            {c.quote && <p className="plan-quote">"{c.quote}"</p>}
            {c.text && <div>{c.text}</div>}
            {!!c.bars?.length && (
              <div className="plan-bars">
                {c.bars.map((b) => (
                  <div key={b.label} className="plan-bar-row"><span>{b.label}</span><span className="plan-track"><i style={{ width: `${(100 * b.value) / b.max}%`, background: b.colour || undefined }} /></span><span>{b.value}</span></div>
                ))}
              </div>
            )}
            {!!c.tags?.length && <div className="plan-tags">{c.tags.map((t, i) => <span key={i} className={`plan-tag ${t.tone || ""}`}>{t.text}</span>)}</div>}
            {c.locked && <div className="plan-why">{c.locked}</div>}
            {c.note && <div className="plan-note">{c.note}</div>}
          </div>
          <div className="plan-card-foot">
            {c.done ? <div className="plan-done">{c.done}</div> : (
              <>
                {c.pick && (
                  <select aria-label={c.pick.label} value={choice} onChange={(e) => setChoice(e.target.value)}>
                    {c.pick.options.map((o) => <option key={o.id} value={o.id} disabled={o.disabled}>{o.label}</option>)}
                  </select>
                )}
                {c.action && (
                  <>
                    <button type="button" className="plan-go" disabled={busy || !c.action.enabled || (!!c.pick && !choice)}
                      onClick={() => onCommand?.(c.action!.command, { ...c.action!.args, ...(c.pick ? { [c.pick.param]: choice } : {}) })}>{c.action.label}</button>
                    {!c.action.enabled && c.action.why && <div className="plan-why">{c.action.why}</div>}
                  </>
                )}
              </>
            )}
          </div>
        </>
      )}
    </article>
  );
}
