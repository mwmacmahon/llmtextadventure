/**
 * The paper doll (FN153, the owner, 11-18: "a better equipment menu with equipment slots on a paper doll"): a figure with
 * its slots round it. Each slot shows what is in it; a tap opens what the pockets hold for it (equip) and what is in it
 * (take off), sent as the game's own Equip and Unequip commands. Armour class and what worn things give, under the figure.
 */
import { useState } from "react";
import type { DollSlot, PaperDollWidget } from "../api";

type OnCommand = (command: string, args: Record<string, unknown>) => void;

// where each slot sits on the 3-column grid round the figure (row, column)
const AT: Record<string, [number, number]> = {
  head: [1, 2], neck: [2, 1], cloak: [2, 3], main_hand: [3, 1], body: [3, 2], off_hand: [3, 3],
  hands: [4, 1], ring_1: [4, 3], ring_2: [5, 3], feet: [5, 2],
};

export function PaperDoll({ widget, onCommand, busy }: { widget: PaperDollWidget; onCommand?: OnCommand; busy?: boolean }) {
  const [open, setOpen] = useState<string | null>(null);
  const slot = widget.slots.find((s) => s.id === open) ?? null;
  return (
    <section className="panel doll-panel">
      <h3>{widget.title || "Equipment"}</h3>
      <div className="doll-grid">
        <div className="doll-figure" aria-hidden="true">
          <svg viewBox="0 0 60 120" width="100%" height="100%">
            <circle cx="30" cy="14" r="10" />
            <rect x="18" y="27" width="24" height="40" rx="6" />
            <rect x="7" y="29" width="9" height="34" rx="4" />
            <rect x="44" y="29" width="9" height="34" rx="4" />
            <rect x="19" y="68" width="9" height="44" rx="4" />
            <rect x="32" y="68" width="9" height="44" rx="4" />
          </svg>
        </div>
        {widget.slots.map((s) => (
          <SlotBox key={s.id} s={s} on={open === s.id} onClick={() => setOpen(open === s.id ? null : s.id)} />
        ))}
      </div>
      {slot && (
        <div className="doll-pick" role="dialog" aria-label={slot.label}>
          <div className="doll-pick-head"><strong>{slot.label}</strong><button className="link small" onClick={() => setOpen(null)}>close</button></div>
          {slot.item ? (
            <div className="doll-pick-row">
              <span>{slot.item.name}{slot.item.gives ? <span className="muted small"> — {slot.item.gives}</span> : null}</span>
              {slot.item.can_remove && (
                <button disabled={busy} onClick={() => { onCommand?.("unequip", { item: slot.item!.id }); setOpen(null); }}>Take off</button>
              )}
            </div>
          ) : <div className="muted small">Nothing here.</div>}
          {slot.options.length > 0 ? (
            <>
              <div className="muted small doll-pick-sub">From the pockets:</div>
              {slot.options.map((o) => (
                <div key={o.id} className="doll-pick-row">
                  <span>{o.name}{o.gives ? <span className="muted small"> — {o.gives}</span> : null}</span>
                  <button disabled={busy} onClick={() => { onCommand?.("equip", { item: o.id }); setOpen(null); }}>Wear</button>
                </div>
              ))}
            </>
          ) : <div className="muted small doll-pick-sub">Nothing carried fits here.</div>}
        </div>
      )}
      <div className="doll-sum">
        <div><strong>Armour class {widget.ac}</strong> <span className="muted small">{widget.ac_how}</span></div>
        {widget.gives.map((g, i) => <div key={i} className="small">{g}</div>)}
      </div>
    </section>
  );
}

function SlotBox({ s, on, onClick }: { s: DollSlot; on: boolean; onClick: () => void }) {
  const [r, c] = AT[s.id] ?? [6, 2];
  return (
    <button type="button" className={`doll-slot${s.item ? " full" : ""}${on ? " on" : ""}${s.options.length ? " can" : ""}`}
      style={{ gridRow: r, gridColumn: c }} onClick={onClick} title={s.item ? s.item.name : `${s.label}: empty`}>
      <span className="doll-slot-label">{s.label}</span>
      <span className="doll-slot-item">{s.item ? s.item.name : "—"}</span>
    </button>
  );
}
