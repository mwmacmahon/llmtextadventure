/* Stand-in portraits (docs/PLANNER-CONTRACT.md section 1): a 16x16 pixel face drawn from a hint (skin, hair, style, coat,
 * nose, extra) or, with no hint, from the key alone, seeded so the same key always gives the same face. Drawn once into a
 * data URL and cached; shown scaled up whole with image-rendering: pixelated, in the manner of the map's sprites. A game's
 * own picture (Art.url) always wins over this. */
import type { Art } from "../api";

const SKINS = ["#f0c9a6", "#ecc2a0", "#e3b48c", "#d9a57c", "#c98e62", "#b67c54", "#8e5a3a"];
const HAIRS = ["#2a1d14", "#3a2a26", "#5a3a22", "#8a2a1e", "#c26a2c", "#e0c060", "#9aa0a8", "#1e1612"];
const COATS = ["#3f5f8a", "#7a4a2a", "#4a6a4a", "#5a7a6a", "#2a2a3a", "#6a4a6a", "#8a2a2a", "#2a3a4a"];
const STYLES = ["crop", "bun", "long", "curls"];

function seeded(key: string) {
  let h = 2166136261;
  for (let i = 0; i < key.length; i++) { h ^= key.charCodeAt(i); h = Math.imul(h, 16777619); }
  return (n: number) => { h = Math.imul(h ^ (h >>> 15), 2246822507); h ^= h >>> 13; return Math.abs(h) % n; };
}

const cache = new Map<string, string>();

export function portraitUrl(art: Art | null | undefined): string | null {
  if (!art) return null;
  if (art.url) return art.url;
  const ck = art.key + JSON.stringify(art.hint ?? {});
  const hit = cache.get(ck);
  if (hit) return hit;
  if (typeof document === "undefined") return null;
  const r = seeded(art.key);
  const h = art.hint ?? {};
  const s = {
    skin: h.skin ?? SKINS[r(SKINS.length)], hair: h.hair ?? HAIRS[r(HAIRS.length)], style: h.style ?? STYLES[r(STYLES.length)],
    coat: h.coat ?? COATS[r(COATS.length)], nose: h.nose ?? "", extra: h.extra ?? "",
  };
  const g: (string | null)[][] = Array.from({ length: 16 }, () => Array(16).fill(null));
  const set = (x: number, y: number, c: string | null) => { if (x >= 0 && x < 16 && y >= 0 && y < 16) g[y][x] = c; };
  for (let y = 13; y < 16; y++) for (let x = 2; x < 14; x++) if (!(y === 13 && (x < 4 || x > 11))) set(x, y, s.coat);
  set(7, 12, s.skin); set(8, 12, s.skin);
  for (let y = 2; y < 13; y++) for (let x = 2; x < 14; x++) { const dx = (x - 7.5) / 4.4, dy = (y - 7.3) / 4.9; if (dx * dx + dy * dy <= 1) set(x, y, s.skin); }
  const H = s.hair;
  const top = () => { for (let x = 4; x < 12; x++) set(x, 2, H); for (let x = 3; x < 13; x++) set(x, 3, H); [3, 4, 11, 12].forEach((x) => set(x, 4, H)); };
  if (s.style === "crop") top();
  if (s.style === "bun") { top(); for (let x = 6; x < 10; x++) { set(x, 0, H); set(x, 1, H); } }
  if (s.style === "long") { top(); for (let y = 4; y < 13; y++) { set(2, y, H); set(3, y, H); set(12, y, H); set(13, y, H); } }
  if (s.style === "curls") { top(); [3, 5, 7, 9, 11].forEach((x) => set(x, 1, H)); for (let y = 4; y < 10; y += 2) { set(2, y, H); set(13, y, H); set(3, y + 1, H); set(12, y + 1, H); } }
  if (s.style === "wig") { for (let x = 3; x < 13; x++) { set(x, 1, H); set(x, 2, H); set(x, 3, H); } for (let y = 3; y < 13; y++) { set(1, y, H); set(2, y, H); set(13, y, H); set(14, y, H); } }
  if (s.extra === "grey") { set(4, 3, "#9aa0a8"); set(10, 3, "#9aa0a8"); }
  set(6, 7, "#1a1410"); set(9, 7, "#1a1410");
  set(5, 9, "#e88a8a"); set(10, 9, "#e88a8a");
  if (s.nose === "red") { set(7, 9, "#d8342c"); set(8, 9, "#d8342c"); set(7, 8, "#f05a50"); } else set(7, 9, "#b07a5a");
  [6, 7, 8, 9].forEach((x) => set(x, 11, "#7a2a22")); set(5, 10, "#7a2a22"); set(10, 10, "#7a2a22");
  if (s.extra === "moustache") { for (let x = 5; x < 11; x++) set(x, 10, "#3a2a1e"); set(4, 11, "#3a2a1e"); set(11, 11, "#3a2a1e"); }
  if (s.extra === "spectacles") { [5, 6, 7, 8, 9, 10].forEach((x) => { set(x, 6, "#c0c0c0"); set(x, 8, "#c0c0c0"); }); set(5, 7, "#c0c0c0"); set(10, 7, "#c0c0c0"); set(7, 7, "#c0c0c0"); set(8, 7, "#c0c0c0"); }
  if (s.extra === "fur") for (let x = 2; x < 14; x++) set(x, 13, x % 2 ? "#c8a878" : "#a88858");
  const out = g.map((row) => row.slice());
  for (let y = 0; y < 16; y++) for (let x = 0; x < 16; x++) if (!g[y][x] && [[1, 0], [-1, 0], [0, 1], [0, -1]].some(([a, b]) => g[y + b]?.[x + a])) out[y][x] = "#14100c";
  const c = document.createElement("canvas"); c.width = 16; c.height = 16;
  const x = c.getContext("2d");
  if (!x) return null;
  out.forEach((row, y) => row.forEach((v, i) => { if (v) { x.fillStyle = v; x.fillRect(i, y, 1, 1); } }));
  const url = c.toDataURL();
  cache.set(ck, url);
  return url;
}

export function Portrait({ art, size, alt }: { art: Art | null | undefined; size: number; alt?: string }) {
  const url = portraitUrl(art);
  if (!url) return null;
  return <img className="portrait" src={url} width={size} height={size} alt={alt ?? ""} />;
}
