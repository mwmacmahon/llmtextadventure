/**
 * The detail (docs/PLANNER-CONTRACT.md section 4; C176): a person's or a thing's own window, with tabs of sections. The
 * roster puts one line a person in the side column and opens the detail over the screen; the profile draws a detail in
 * place (in a pop-out). Sections are drawn as sent; actions and choices send the game's own commands and close the window.
 */
import { useEffect, useState } from "react";
import type { Detail, DetailSection, PlanAction, ProfileWidget, RosterWidget } from "../api";
import { Portrait } from "./portraitArt";
import "./planner.css";

type OnCommand = (command: string, args: Record<string, unknown>) => void;

export function RosterPanel({ widget, onCommand, busy }: { widget: RosterWidget; onCommand?: OnCommand; busy?: boolean }) {
  const [open, setOpen] = useState<string | null>(null);
  const item = widget.items.find((x) => x.id === open) ?? null;
  useEffect(() => {
    if (!open) return;
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(null); };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [open]);
  return (
    <section className="panel roster-panel">
      <h3>{widget.title}</h3>
      <div className="roster">
        {widget.items.map((x) => (
          <button key={x.id} type="button" className="roster-line" onClick={() => setOpen(x.id)} aria-label={`Open ${x.name}`}>
            <Portrait art={x.art} size={34} />
            <span className="roster-name">{x.name} {x.badge && <small>{x.badge}</small>}</span>
            <span className="roster-now">
              <b>{x.line}</b>
              {x.meter && <span className="roster-meter" title={`${x.meter.label} ${x.meter.value}`}><i style={{ width: `${(100 * x.meter.value) / x.meter.max}%` }} /></span>}
            </span>
          </button>
        ))}
      </div>
      {item && (
        <div className="overlay" onClick={() => setOpen(null)}>
          <div className="overlay-sheet detail-sheet" onClick={(e) => e.stopPropagation()} role="dialog" aria-label={item.detail.title}>
            <div className="overlay-head">
              <strong className="pixel-heading detail-title">{item.detail.title}</strong>
              <span className="spacer" />
              <button type="button" onClick={() => setOpen(null)}>close</button>
            </div>
            <div className="overlay-body">
              <DetailView detail={item.detail} onCommand={(c, a) => { setOpen(null); onCommand?.(c, a); }} busy={busy} />
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

export function ProfilePanel({ widget, onCommand, busy }: { widget: ProfileWidget; onCommand?: OnCommand; busy?: boolean }) {
  return (
    <section className="panel profile-panel">
      <h3>{widget.detail.title}</h3>
      <DetailView detail={widget.detail} onCommand={onCommand} busy={busy} />
    </section>
  );
}

export function DetailView({ detail, onCommand, busy }: { detail: Detail; onCommand?: OnCommand; busy?: boolean }) {
  const [tab, setTab] = useState(detail.tabs[0]?.id ?? "");
  const t = detail.tabs.find((x) => x.id === tab) ?? detail.tabs[0];
  return (
    <div className="detail">
      <div className="detail-top">
        {detail.art && <Portrait art={detail.art} size={104} alt={detail.title} />}
        <div className="detail-words">
          {detail.sub && <div className="muted small">{detail.sub}</div>}
          {detail.quote && <p className="plan-quote">"{detail.quote}"</p>}
          {!!detail.tags?.length && <div className="plan-tags">{detail.tags.map((x) => <span key={x} className="plan-tag want">{x}</span>)}</div>}
          {detail.meter && (
            <div className="plan-bar-row"><span>{detail.meter.label}</span><span className="plan-track"><i style={{ width: `${(100 * detail.meter.value) / detail.meter.max}%` }} /></span><span>{detail.meter.value}</span></div>
          )}
        </div>
      </div>
      {detail.tabs.length > 1 && (
        <div className="detail-tabs" role="tablist">
          {detail.tabs.map((x) => (
            <button key={x.id} type="button" role="tab" aria-selected={x.id === t?.id} className={x.id === t?.id ? "on" : ""} onClick={() => setTab(x.id)}>{x.label}</button>
          ))}
        </div>
      )}
      <div className="detail-pane">
        {t?.sections.map((s, i) => <SectionView key={i} s={s} onCommand={onCommand} busy={busy} />)}
      </div>
    </div>
  );
}

function ActionButton({ a, onCommand, busy }: { a: PlanAction; onCommand?: OnCommand; busy?: boolean }) {
  return (
    <span className="detail-action">
      <button type="button" disabled={busy || !a.enabled} onClick={() => onCommand?.(a.command, a.args)}>{a.label}</button>
      {!a.enabled && a.why && <span className="muted small"> {a.why}</span>}
    </span>
  );
}

function SectionView({ s, onCommand, busy }: { s: DetailSection; onCommand?: OnCommand; busy?: boolean }) {
  return (
    <div className="detail-section">
      {s.title && <h4>{s.title}</h4>}
      {s.kind === "bars" && s.rows.map((r) => (
        <div key={r.label} className="plan-bar-row" title={r.note || undefined}>
          <span>{r.label}</span><span className="plan-track"><i style={{ width: `${(100 * r.value) / r.max}%`, background: r.colour || undefined }} /></span><span>{r.value}</span>
          {r.note && <span className="detail-note">{r.note}</span>}
        </div>
      ))}
      {s.kind === "rows" && <ul className="kv">{s.rows.map((r) => <li key={r.label}><span className="muted">{r.label}</span><span>{r.value}</span></li>)}</ul>}
      {s.kind === "text" && <div className="small">{s.text}</div>}
      {s.kind === "items" && s.items.map((it) => (
        <div key={it.name} className="detail-item">
          <span className="pixel-name-sm">{it.name}</span>
          {it.lines.map((l, i) => <span key={i} className="small">{l}</span>)}
          {it.action && <ActionButton a={it.action} onCommand={onCommand} busy={busy} />}
        </div>
      ))}
      {s.kind === "choice" && (
        <>
          {s.text && <div className="small">{s.text}</div>}
          <div className="detail-seg" role="group" aria-label={s.title || "Choose"}>
            {s.options.map((o) => (
              <button key={o.id} type="button" aria-pressed={o.on} className={o.on ? "on" : ""} disabled={busy}
                onClick={() => onCommand?.(s.command, { ...(s.args || {}), [s.param]: o.id })}>{o.label}</button>
            ))}
          </div>
        </>
      )}
      {s.kind === "actions" && <div className="detail-actions">{s.items.map((a) => <ActionButton key={a.label} a={a} onCommand={onCommand} busy={busy} />)}</div>}
    </div>
  );
}
