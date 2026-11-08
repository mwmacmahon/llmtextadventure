import { useMemo } from "react";

/* A gravestone in the manner of an early-90s Windows tile RPG: drawn on a 32x40 grid of square pixels, a limited palette
 * per game (a warm sandstone for the fantasy, slate for noir, a steel-green for the station), ordered dither on the face,
 * a chiselled R I P, grass and turned earth at the foot. Original art, drawn here pixel by pixel; scaled up whole
 * (shape-rendering crispEdges), never smoothed. The name goes on the face in the period bitmap font. */

const W = 32;
const H = 40;

type Palette = { K: string; D: string; M: string; L: string; H: string };
const STONE: Record<string, Palette> = {
  fantasy: { K: "#1c1814", D: "#5c5248", M: "#8a7f72", L: "#b0a594", H: "#d8cfbf" },
  noir: { K: "#121418", D: "#444a56", M: "#6c7484", L: "#959daa", H: "#c3c9d3" },
  station: { K: "#10161a", D: "#3e4f55", M: "#627a80", L: "#8ca3a8", H: "#bcd0d2" },
  other: { K: "#161616", D: "#505050", M: "#808080", L: "#a8a8a8", H: "#d4d4d4" },
};
const EARTH = { e: "#3d2a19", E: "#5e4127", g: "#1f4a1c", G: "#2f6b2a", B: "#4f9a3a" };

// 4x4 Bayer matrix: the period's ordered dither
const BAYER = [
  [0, 8, 2, 10],
  [12, 4, 14, 6],
  [3, 11, 1, 9],
  [15, 7, 13, 5],
];

// 3x5 glyphs, carved into the face
const GLYPH: Record<string, string[]> = {
  R: ["##.", "#.#", "##.", "#.#", "#.#"],
  I: ["###", ".#.", ".#.", ".#.", "###"],
  P: ["##.", "#.#", "##.", "#..", "#.."],
};

const CX = 15.5;
const TOP = 3;
const ARCH = 9; // the arch's radius: the tablet is 18 pixels wide
const BODY_END = 31;

function inTablet(x: number, y: number): boolean {
  const px = x + 0.5;
  if (y < TOP || y > BODY_END) return false;
  if (Math.abs(px - CX) > ARCH) return false;
  const cy = TOP + ARCH;
  if (y + 0.5 < cy) return (px - CX) ** 2 + (y + 0.5 - cy) ** 2 <= ARCH * ARCH;
  return true;
}

function inPlinth(x: number, y: number): boolean {
  return y >= 32 && y <= 34 && x >= 6 && x <= 25;
}

/** The stone as a grid of palette keys (null: transparent). Pure: the same game and seed give the same stone. */
function draw(seed: number, cracked: boolean): (string | null)[][] {
  const g: (string | null)[][] = Array.from({ length: H }, () => Array<string | null>(W).fill(null));
  // the ground: a mound of turned earth, grass tufts along its top
  for (let y = 33; y < H; y++) {
    const half = 12 + Math.min(4, y - 33);
    for (let x = 0; x < W; x++) {
      if (Math.abs(x + 0.5 - CX) <= half) g[y][x] = (x * 7 + y * 3 + seed) % 5 === 0 ? "E" : "e";
    }
  }
  for (let x = 2; x < W - 2; x++) {
    const h = (x * 13 + seed * 5) % 7 < 3 ? 2 : (x * 5 + seed) % 4 === 0 ? 3 : 1;
    for (let k = 0; k < h; k++) {
      const y = 36 - k;
      if (y >= 0) g[y][x] = k === h - 1 ? "B" : k === 0 ? "g" : "G";
    }
  }
  // the plinth
  for (let y = 32; y <= 34; y++) for (let x = 6; x <= 25; x++) if (inPlinth(x, y)) g[y][x] = y === 32 ? "L" : y === 34 ? "D" : "M";
  // the tablet: outline, a lit left edge, a shadowed right edge, a dithered face darkening toward the foot
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      if (!inTablet(x, y)) continue;
      const edge = !inTablet(x - 1, y) || !inTablet(x + 1, y) || !inTablet(x, y - 1) || (!inTablet(x, y + 1) && y < BODY_END);
      if (edge) {
        g[y][x] = "K";
        continue;
      }
      const fromLeft = [1, 2].filter((d) => !inTablet(x - d, y)).length;
      const fromRight = [1, 2, 3].filter((d) => !inTablet(x + d, y)).length;
      if (fromLeft >= 1 && !inTablet(x - 2, y)) g[y][x] = "H";
      else if (fromRight >= 1) g[y][x] = fromRight >= 2 ? "D" : "M";
      else {
        const t = (y - TOP) / (BODY_END - TOP); // 0 at the top, 1 at the foot
        const level = Math.floor(t * 18) - 2;
        g[y][x] = BAYER[y % 4][x % 4] < level ? "M" : "L";
      }
    }
  }
  for (let x = 6; x <= 25; x++) g[31][x] = inTablet(x, 31) ? "K" : g[31][x];
  for (let y = 32; y <= 34; y++) {
    g[y][5] = "K";
    g[y][26] = "K";
  }
  for (let x = 5; x <= 26; x++) g[35][x] = g[35][x] ?? "K";
  // R I P, chiselled: the cut in dark, a lit lip under it
  const word = ["R", "I", "P"];
  let x0 = 10;
  for (const ch of word) {
    GLYPH[ch].forEach((row, dy) =>
      [...row].forEach((c, dx) => {
        if (c !== "#") return;
        const x = x0 + dx;
        const y = 9 + dy;
        g[y][x] = "D";
        if (y + 1 < H && GLYPH[ch][dy + 1]?.[dx] !== "#" && inTablet(x, y + 1)) g[y + 1][x] = "H";
      }),
    );
    x0 += 4;
  }
  // a crack, for a death that was undone: the stone stands, a little broken
  if (cracked) {
    let x = 20 + (seed % 3);
    for (let y = 5; y < 26; y++) {
      if (inTablet(x, y) && g[y][x] !== "K") g[y][x] = "K";
      if ((y + seed) % 3 === 0) x += (y + seed) % 2 ? 1 : -1;
      x = Math.max(9, Math.min(22, x));
    }
  }
  return g;
}

function hash(s: string): number {
  let h = 7;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return h % 97;
}

/** The stone, `scale` screen pixels to the art pixel. `name` is lettered on its face. */
export function Stone({ game, name, seed = "", scale = 4, undone = false, title }: { game: string; name?: string; seed?: string; scale?: number; undone?: boolean; title?: string }) {
  const s = hash(seed || name || game);
  const grid = useMemo(() => draw(s, undone), [s, undone]);
  const pal = { ...(STONE[game] ?? STONE.other), ...EARTH } as Record<string, string>;
  // one <rect> per run of same-coloured pixels in a row: a few hundred rects, not a thousand
  const rects: JSX.Element[] = [];
  grid.forEach((row, y) => {
    let x = 0;
    while (x < W) {
      const c = row[x];
      let n = 1;
      while (x + n < W && row[x + n] === c) n++;
      if (c) rects.push(<rect key={`${x}-${y}`} x={x} y={y} width={n} height={1} fill={pal[c]} />);
      x += n;
    }
  });
  const shown = (name ?? "").toUpperCase();
  const long = shown.length > 6;
  return (
    <svg
      className={`stone${undone ? " stone-undone" : ""}`}
      viewBox={`0 0 ${W} ${H}`}
      width={W * scale}
      height={H * scale}
      shapeRendering="crispEdges"
      role="img"
      aria-label={title ?? (name ? `Gravestone of ${name}` : "Gravestone")}
    >
      {rects}
      {shown && (
        <text
          x={16}
          y={20.5}
          textAnchor="middle"
          className="stone-name"
          fontSize={long ? 3 : 3.8}
          fill={pal.K}
          {...(shown.length > 5 ? { textLength: 15, lengthAdjust: "spacingAndGlyphs" } : {})}
        >
          {shown.slice(0, 14)}
        </text>
      )}
      <rect x={11} y={24} width={10} height={1} fill={pal.M} />
      <rect x={12} y={26} width={8} height={1} fill={pal.M} />
    </svg>
  );
}
