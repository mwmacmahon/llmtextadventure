/** A dev page (never built into the game): the sorted pockets, the shop's window and the company list on made-up sample
 * data, to look at them without a played game. `npm run dev`, then /items-demo.html. */
import { createRoot } from "react-dom/client";
import "./styles.css";
import { Panels } from "./components/Panels";
import type { IconRow, Widget } from "./api";

const row = (id: string, icon: string, name: string, extra: Partial<IconRow> = {}): IconRow => ({ id, icon, name, note: "", count: 1, price: null, tag: "", ...extra });
const items: Widget = {
  type: "items", title: "Pockets", purse: 40,
  tabs: [["All", "bag", []], ["Arms", "weapon", ["Equipped", "Weapons", "Armour", "Worn"]], ["Use", "potion", ["Potions", "Throwables", "Scrolls and wands"]],
         ["Curios", "curio", ["Curios"]], ["Loot", "loot", ["Loot"]]],
  groups: [
    { title: "Equipped", note: "", rows: [row("a", "weapon", "sample sword", { tag: "on", note: "plain" }), row("b", "armour", "sample mail", { tag: "on" }), row("c", "worn", "sample cloak", { tag: "on" })] },
    { title: "Potions", note: "", rows: [row("d", "potion", "sample potion", { count: 2, note: "heals" })] },
    { title: "Throwables", note: "", rows: [row("e", "throw", "sample flask")] },
    { title: "Scrolls and wands", note: "", rows: [row("f", "scroll", "sample scroll"), row("g", "wand", "sample wand")] },
    { title: "Curios", note: "", rows: [row("h", "curio", "sample curio", { note: "does something odd; 2 uses" })] },
    { title: "Gear", note: "", rows: [row("i", "bag", "sample pack"), row("j", "bag", "torches", { count: 3 })] },
    { title: "Loot", note: "20 gold", rows: [row("k", "loot", "sample pelt", { count: 3, price: 12 }), row("l", "loot", "sample ring", { price: 8 })] },
  ],
};
const shop: Widget = {
  type: "shop", title: "The sample store", keeper: "Sample Keeper, storekeeper", gold: 40, command: "deal",
  stock: [row("p", "potion", "sample potion", { price: 12 }), row("q", "throw", "sample flask", { price: 10 }), row("gear:x", "weapon", "sample sword", { price: 15 })],
  sells: [row("k", "loot", "sample pelt", { count: 3, price: 12, tag: "loot" }), row("l", "loot", "sample ring", { price: 8, tag: "loot" }), row("d", "potion", "sample potion", { price: 6 })],
};
const company: Widget = { type: "list", title: "Company", layout: "stack", items: [{ label: "Sample Friend", value: "a sellsword · HP 11/11 · companion" }, { label: "Sample Helper", value: "a huntsman · HP 16/16 · for: Wolves at the den" }] };
const sheet = { background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 10, padding: 12, width: 420 } as const;

createRoot(document.getElementById("root")!).render(
  <div style={{ display: "flex", flexWrap: "wrap", gap: 16, padding: 16, alignItems: "flex-start" }}>
    <div style={sheet}><Panels panels={[items]} /></div>
    <div style={sheet}><Panels panels={[shop]} onCommand={(c, a) => { document.title = `${c} ${JSON.stringify(a)}`; }} /></div>
    <div style={sheet}><Panels panels={[{ ...shop, stock: [] } as Widget]} /></div>
    <div style={{ ...sheet, width: 300 }}><Panels panels={[company]} /></div>
  </div>,
);
