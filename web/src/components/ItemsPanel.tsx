/**
 * The sorted pockets (FN171) and the shop's window (FN172, FN180). Pockets: what is carried by category, an icon for each
 * type, tabs that filter. Shop: Buy and Sell tabs and a basket; nothing changes until the one button, which sends the whole
 * basket as the game's `deal` command.
 */
import { useState } from "react";
import type { HotbarWidget, IconRow, ItemsWidget, ShopWidget } from "../api";
import { ItemIcon } from "./ItemIcon";

type OnCommand = (command: string, args: Record<string, unknown>) => void;

function Row({ r, right }: { r: IconRow; right?: React.ReactNode }) {
  return (
    <div className="item-row">
      <ItemIcon kind={r.icon} />
      <span className="item-name">
        {r.name}{r.tag === "on" && <span className="item-tag on">on</span>}
        {r.note && <small>{r.note}</small>}
      </span>
      <span className="item-count">{r.count > 1 ? `×${r.count}` : ""}</span>
      {right ?? (r.price != null ? <span className="item-price">{r.price} g</span> : <span />)}
    </div>
  );
}

/** A widget's heading: plain, or a button that opens the menu it is the short form of (FN188). */
function Head({ title, opens, onOpen }: { title: string; opens?: string; onOpen?: (group: string) => void }) {
  if (!title) return null;
  return opens && onOpen
    ? <h3><button type="button" className="widget-open" onClick={() => onOpen(opens)}>{title} <span aria-hidden="true">›</span></button></h3>
    : <h3>{title}</h3>;
}

export function Hotbar({ widget, onCommand, onOpen, busy }: { widget: HotbarWidget; onCommand?: OnCommand; onOpen?: (group: string) => void; busy?: boolean }) {
  return (
    <section className="panel hotbar-panel">
      <Head title={widget.title} opens={widget.opens} onOpen={onOpen} />
      <div className="hotbar">
        {widget.slots.map((s) => (
          <button key={s.id} type="button" className="hot-slot" disabled={busy || !s.enabled} title={s.label}
            onClick={(e) => { e.currentTarget.blur(); if (s.opens) onOpen?.(s.opens); else onCommand?.(s.command, s.args); }}>
            <ItemIcon kind={s.icon} />
            <span className="hot-label">{s.label}</span>
            {s.count != null && <span className="hot-count">{s.count}</span>}
          </button>
        ))}
      </div>
    </section>
  );
}

export function ItemsPanel({ widget, onOpen }: { widget: ItemsWidget; onOpen?: (group: string) => void }) {
  const [tab, setTab] = useState(0);
  const only = widget.tabs[tab]?.[2] ?? [];
  const groups = widget.groups.filter((g) => !only.length || only.includes(g.title));
  return (
    <section className="panel items-panel">
      <div className="items-head">
        <Head title={widget.title} opens={widget.opens} onOpen={onOpen} />
        {widget.purse != null && <span className="purse"><ItemIcon kind="gold" />{widget.purse} gold</span>}
      </div>
      {widget.tabs.length > 1 && (
        <div className="item-tabs">
          {widget.tabs.map(([title, icon], i) => (
            <button key={title} type="button" className={`item-tab${i === tab ? " on" : ""}`} aria-pressed={i === tab} onClick={() => setTab(i)}>
              <ItemIcon kind={icon} />{title}
            </button>
          ))}
        </div>
      )}
      {groups.length === 0 && <p className="muted small">Nothing.</p>}
      {groups.map((g) => (
        <div key={g.title}>
          <div className="item-cat">{g.title}{g.note ? ` · ${g.note}` : ""}</div>
          {g.rows.map((r) => <Row key={r.id} r={r} right={r.tag && r.tag !== "on" ? <span className="item-tag bad">{r.tag}</span> : undefined} />)}
        </div>
      ))}
    </section>
  );
}

export function ShopPanel({ widget, onCommand, busy }: { widget: ShopWidget; onCommand?: OnCommand; busy?: boolean }) {
  const canBuy = widget.stock.length > 0;
  const services = widget.services ?? [];
  const [tab, setTab] = useState<"buy" | "sell" | "services">(canBuy ? "buy" : widget.sells.length ? "sell" : "services");
  const [basket, setBasket] = useState<Record<string, number>>({});
  const [selling, setSelling] = useState<Record<string, boolean>>({});
  const cost = widget.stock.reduce((a, r) => a + (basket[r.id] ?? 0) * (r.price ?? 0), 0);
  const income = widget.sells.reduce((a, r) => a + (selling[r.id] ? r.price ?? 0 : 0), 0);
  const bought = Object.values(basket).reduce((a, n) => a + n, 0);
  const sold = Object.values(selling).filter(Boolean).length;
  const room = widget.gold + income - cost;
  const loot = widget.sells.filter((r) => r.tag === "loot");
  const lootTotal = loot.reduce((a, r) => a + (r.price ?? 0), 0);
  const allLoot = loot.length > 0 && loot.every((r) => selling[r.id]);
  const label = bought && sold ? `Buy and sell · ${income - cost >= 0 ? "+" : ""}${income - cost} gold`
    : sold ? `Sell · +${income} gold` : bought ? `Buy · ${cost} gold` : tab === "buy" ? "Buy" : "Sell";
  const go = () => onCommand?.(widget.command, {
    buy: Object.entries(basket).filter(([, n]) => n > 0).map(([id, n]) => `${id}*${n}`).join(","),
    sell: Object.entries(selling).filter(([, on]) => on).map(([id]) => id).join(","),
  });
  return (
    <section className="panel items-panel shop-panel">
      <div className="items-head">
        <h3>{widget.title}</h3>
        <span className="purse"><ItemIcon kind="gold" />{widget.gold} gold</span>
      </div>
      <div className="item-tabs">
        {canBuy && <button type="button" className={`item-tab${tab === "buy" ? " on" : ""}`} aria-pressed={tab === "buy"} onClick={() => setTab("buy")}>Buy</button>}
        {widget.sells.length > 0 && <button type="button" className={`item-tab${tab === "sell" ? " on" : ""}`} aria-pressed={tab === "sell"} onClick={() => setTab("sell")}>Sell</button>}
        {services.length > 0 && <button type="button" className={`item-tab${tab === "services" ? " on" : ""}`} aria-pressed={tab === "services"} onClick={() => setTab("services")}>Services</button>}
        {widget.keeper && <span className="muted small shop-keeper">{widget.keeper}</span>}
      </div>
      {tab === "buy" && widget.stock.map((r) => (
        <Row key={r.id} r={r} right={
          <span className="shop-pick">
            <span className="item-price">{r.price} g</span>
            {(basket[r.id] ?? 0) > 0 && <button type="button" className="shop-step" aria-label={`One fewer ${r.name}`} onClick={() => setBasket({ ...basket, [r.id]: basket[r.id] - 1 })}>−</button>}
            {(basket[r.id] ?? 0) > 0 && <span className="item-count">{basket[r.id]}</span>}
            <button type="button" className="shop-step" aria-label={`Add ${r.name}`} disabled={(r.price ?? 0) > room} onClick={() => setBasket({ ...basket, [r.id]: (basket[r.id] ?? 0) + 1 })}>+</button>
          </span>} />
      ))}
      {tab === "sell" && (
        <>
          {loot.length > 0 && <div className="item-cat">Loot · {lootTotal} gold</div>}
          {loot.map((r) => <SellRow key={r.id} r={r} on={!!selling[r.id]} toggle={() => setSelling({ ...selling, [r.id]: !selling[r.id] })} />)}
          {widget.sells.some((r) => r.tag !== "loot") && <div className="item-cat">Will also buy</div>}
          {widget.sells.filter((r) => r.tag !== "loot").map((r) => <SellRow key={r.id} r={r} on={!!selling[r.id]} toggle={() => setSelling({ ...selling, [r.id]: !selling[r.id] })} />)}
          {loot.length > 0 && (
            <button type="button" className="shop-all" onClick={() => setSelling({ ...selling, ...Object.fromEntries(loot.map((r) => [r.id, !allLoot])) })}>
              {allLoot ? "Keep loot" : `Sell all loot · ${lootTotal} gold`}
            </button>
          )}
        </>
      )}
      {tab === "services" && services.map((r) => (
        <Row key={r.id} r={r} right={
          <span className="shop-pick">
            <span className="item-price">{r.price} g</span>
            <button type="button" className="shop-step" disabled={busy || (r.price ?? 0) > widget.gold} onClick={() => onCommand?.(widget.service_command ?? "service", { what: r.id })}>Pay</button>
          </span>} />
      ))}
      {tab !== "services" && (
        <div className="shop-foot">
          <button type="button" className="shop-go" disabled={busy || (!bought && !sold) || room < 0} onClick={go}>{label}</button>
          {(bought > 0 || sold > 0) && <button type="button" className="link small" onClick={() => { setBasket({}); setSelling({}); }}>Clear</button>}
        </div>
      )}
    </section>
  );
}

function SellRow({ r, on, toggle }: { r: IconRow; on: boolean; toggle: () => void }) {
  return (
    <Row r={r} right={
      <span className="shop-pick">
        <span className="item-price">{r.price != null ? `${r.price} g` : "?"}</span>
        <button type="button" className={`shop-step${on ? " on" : ""}`} aria-pressed={on} aria-label={`Sell ${r.name}`} onClick={toggle}>{on ? "✓" : "+"}</button>
      </span>} />
  );
}
