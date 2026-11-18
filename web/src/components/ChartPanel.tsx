/**
 * The paint chart (docs/PLANNER-CONTRACT.md section 2; C159, C175): columns by rows, a choice a cell. Pick a choice, press on
 * a cell and drag across others; a row's or a column's label fills the rest of it. Pointing at a cell lights the choices
 * open there; pointing at a choice lights its cells; with a choice picked, the open cells it cannot go in are hatched.
 * When a stroke ends the chart sends its command once, with only the cells that changed; Undo sends the old values back.
 * The engine decides everything shown (states, marks, where a choice may go); this draws it and reports paints.
 */
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import type { ChartWidget, PlanChoice } from "../api";
import { Portrait } from "./portraitArt";
import "./planner.css";

type OnCommand = (command: string, args: Record<string, unknown>) => void;
type Cells = Record<string, string | null>;

export function ChartPanel({ widget, onCommand, busy }: { widget: ChartWidget; onCommand?: OnCommand; busy?: boolean }) {
  const ncols = widget.columns.length;
  const [local, setLocal] = useState<(string | null)[]>(() => widget.cells.map((c) => c.v));
  const [pick, setPick] = useState<string | null>(widget.choices[0]?.id ?? null);
  const [lit, setLit] = useState<{ cells: Set<number>; choices: Set<string> | null } | null>(null);
  const [refused, setRefused] = useState<string | null>(null);
  const undo = useRef<Cells[]>([]);
  const stroke = useRef<{ before: Cells; after: Cells } | null>(null);
  const gridRef = useRef<HTMLDivElement>(null);

  // the engine's view wins whenever a new one arrives
  useEffect(() => { setLocal(widget.cells.map((c) => c.v)); }, [widget.cells]);

  const byId = useMemo(() => Object.fromEntries(widget.choices.map((c) => [c.id, c])), [widget.choices]);
  const groups = useMemo(() => {
    const g: [string, PlanChoice[]][] = [];
    widget.choices.forEach((c) => { const at = g.find(([n]) => n === c.group); if (at) at[1].push(c); else g.push([c.group, [c]]); });
    return g;
  }, [widget.choices]);
  const paintable = (i: number) => widget.cells[i]?.state === "open" && widget.rows[Math.floor(i / ncols)]?.paintable !== false;
  const allowed = (choice: string | null, i: number) => {
    if (choice === null) return widget.erase;
    const w = byId[choice]?.where;
    return !w || w.includes(i);
  };

  const paint = (i: number) => {
    if (!paintable(i) || busy) return;
    if (!allowed(pick, i)) { setRefused(pick ? byId[pick]?.hint || `${byId[pick]?.label} cannot go there.` : null); return; }
    if (local[i] === pick) return;
    const s = stroke.current ?? (stroke.current = { before: {}, after: {} });
    if (!(String(i) in s.before)) s.before[String(i)] = local[i];
    s.after[String(i)] = pick;
    setLocal((l) => { const n = l.slice(); n[i] = pick; return n; });
  };
  const send = (cells: Cells) => { if (Object.keys(cells).length) onCommand?.(widget.command, { ...widget.args, cells }); };
  const endStroke = () => {
    const s = stroke.current; stroke.current = null;
    if (!s || !Object.keys(s.after).length) return;
    undo.current.push(s.before); if (undo.current.length > 40) undo.current.shift();
    send(s.after);
  };
  useEffect(() => {
    const move = (e: PointerEvent) => {
      if (!stroke.current) return;
      const el = document.elementFromPoint(e.clientX, e.clientY) as HTMLElement | null;
      const c = el?.closest?.("[data-cell]") as HTMLElement | null;
      if (c && gridRef.current?.contains(c)) paint(Number(c.dataset.cell));
    };
    const up = () => endStroke();
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", up); window.addEventListener("pointercancel", up);
    return () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); window.removeEventListener("pointercancel", up); };
  });
  const fill = (idx: number[]) => {
    const before: Cells = {}, after: Cells = {};   // held here: the state updater below runs after the stroke is cleared
    idx.forEach((i) => { if (paintable(i) && allowed(pick, i) && local[i] !== pick) { before[String(i)] = local[i]; after[String(i)] = pick; } });
    if (!Object.keys(after).length) return;
    setLocal((l) => { const n = l.slice(); Object.keys(after).forEach((k) => (n[Number(k)] = pick)); return n; });
    stroke.current = { before, after };
    endStroke();
  };
  const doUndo = () => {
    const before = undo.current.pop(); if (!before) return;
    setLocal((l) => { const n = l.slice(); Object.entries(before).forEach(([k, v]) => (n[Number(k)] = v)); return n; });
    send(before);
  };

  const litFromCell = (i: number) => { if (!paintable(i)) return; setLit({ cells: new Set([i]), choices: new Set(widget.choices.filter((c) => allowed(c.id, i)).map((c) => c.id)) }); };
  const litFromChoice = (id: string) => setLit({ cells: new Set(widget.cells.map((_, i) => i).filter((i) => paintable(i) && allowed(id, i))), choices: new Set([id]) });

  return (
    <section className="panel chart-panel">
      <div className="chart-head">
        {widget.art && <Portrait art={widget.art} size={22} />}
        <h3>{widget.title}</h3>
        <span className="muted small">{widget.who}</span>
        <span className="spacer" />
        <button type="button" className="small-btn" onClick={doUndo} disabled={busy || !undo.current.length}>Undo</button>
      </div>
      <div className="chart-box" onPointerLeave={() => setLit(null)}>
        {groups.map(([name, cs]) => (
          <div key={name} className="chart-grp">
            <span className="chart-grp-name">{name}</span>
            {cs.map((c) => (
              <button key={c.id} type="button" title={c.hint || c.label} aria-pressed={pick === c.id}
                className={`chart-choice${pick === c.id ? " on" : ""}${lit?.choices ? (lit.choices.has(c.id) ? " glow" : " dimmed") : ""}`}
                style={{ background: c.colour }} onClick={() => { setPick(c.id); setRefused(null); }}
                onPointerEnter={() => litFromChoice(c.id)} onPointerLeave={() => setLit(null)}>{c.label}</button>
            ))}
            {widget.erase && name === groups[groups.length - 1][0] && (
              <button type="button" className={`chart-choice eraser${pick === null ? " on" : ""}`} aria-pressed={pick === null} onClick={() => setPick(null)}>Eraser</button>
            )}
          </div>
        ))}
      </div>
      <div className="chart-scroll">
        <div className="chart-grid" ref={gridRef} style={{ gridTemplateColumns: `86px repeat(${ncols}, minmax(40px, 1fr))` }} onPointerLeave={() => setLit(null)}>
          <span />
          {widget.columns.map((col, ci) => (
            <button key={col.id} type="button" className={`chart-col${col.today ? " today" : ""}`} title={`Fill the rest of ${col.label}`}
              onClick={() => fill(widget.rows.map((_, ri) => ri * ncols + ci))}>{col.label}{col.sub && <span>{col.sub}</span>}</button>
          ))}
          {widget.rows.map((_, ri) => rowCells(ri))}
        </div>
      </div>
      {refused && <div className="chart-refused" role="status">{refused}</div>}
      {widget.bars && (
        <div className="chart-scroll">
          <div className="chart-grid chart-bars" style={{ gridTemplateColumns: `86px repeat(${ncols}, minmax(40px, 1fr))` }}>
            <span className="chart-row-label"><b>{widget.bars.label}</b>{widget.bars.sub}</span>
            {widget.bars.values.map((v, i) => (
              <span key={i} className="chart-bar">
                {v === null ? <em>–</em> : <><i className={v >= widget.bars!.bad ? "bad" : v >= widget.bars!.warn ? "warn" : ""} style={{ height: `${Math.round((100 * v) / widget.bars!.max)}%` }} /><em>{v}</em></>}
              </span>
            ))}
          </div>
        </div>
      )}
      {widget.under?.map((u, i) => <div key={i} className="chart-under small">{u}</div>)}
    </section>
  );

  function rowCells(ri: number) {
    const row = widget.rows[ri];
    return (
      <Fragment key={row.id}>
        <button type="button" className="chart-row-label" disabled={!row.paintable} title={row.paintable ? "Fill the rest of this row" : undefined}
          onClick={() => fill(widget.columns.map((_, ci) => ri * ncols + ci))}><b>{row.label}</b>{row.sub}</button>
        {widget.columns.map((_, ci) => {
          const i = ri * ncols + ci;
          const cell = widget.cells[i];
          const v = local[i];
          const ch = v ? byId[v] : null;
          const open = paintable(i);
          const shut = open && !allowed(pick, i);
          const cls = ["chart-cell", `st-${cell.state}`, !row.paintable ? "unplanned" : "", !ch && cell.state !== "fixed" ? "empty" : "",
            shut ? "shut" : "", lit?.cells.has(i) ? "glow" : ""].filter(Boolean).join(" ");
          return (
            <div key={ci} className={cls} data-cell={open ? i : undefined} title={cell.note || (ch ? ch.label : "")}
              style={ch && cell.state !== "fixed" ? { background: ch.colour } : undefined}
              onPointerDown={(e) => { if (!open) return; e.preventDefault(); stroke.current = { before: {}, after: {} }; paint(i); }}
              onPointerEnter={() => { if (!stroke.current) litFromCell(i); }}>
              {cell.state === "now" && <span className="chart-now">NOW</span>}
              {cell.state === "fixed" ? cell.label : ch ? ch.short : row.paintable ? "·" : cell.label || ""}
              {cell.mark === "spark" && <span className="chart-spark" aria-hidden="true">✦</span>}
            </div>
          );
        })}
      </Fragment>
    );
  }
}
