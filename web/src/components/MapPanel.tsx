import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { MapPlace, MapWidget } from "../api";
import { GROUNDS, ICONS, ICON_PAL, JOB_MARK, PLAYER, type Tex } from "./mapArt";

/* The world map (docs/MAP-CONTRACT.md section 3). It draws what the widget holds and works nothing out about the world:
 * the ground, the lines, the places, the player and the journey are all in the widget. Pixel art at 8x8 a tile, scaled up
 * by whole numbers, never smoothed; the view scrolls without limit (there is no edge) and keeps only its scroll and zoom. */

const T = 8; // art pixels a tile
const mod = (a: number, n: number) => ((a % n) + n) % n;
const key = (x: number, y: number) => `${x},${y}`;

const GROUND_NAME: Record<string, string> = {
  m: "Meadow", w: "Wood", W: "Dark wood", h: "Hills", M: "Mountains", b: "Bog", f: "Farmland", "~": "Water", s: "Sand",
  B: "Burnt ground", L: "Lava", R: "Rubble", S: "Snow",
};

// ---- canvases for the art, made once ----
type Canvas = HTMLCanvasElement;
const mk = (w: number, h: number): Canvas => {
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  return c;
};
const texCache = new Map<string, Canvas>();
function texture(palette: string, g: string): Canvas {
  const k = palette + g;
  let c = texCache.get(k);
  if (c) return c;
  const set = GROUNDS[palette] ?? GROUNDS.forest;
  const t: Tex = set[g] ?? set["?"];
  c = mk(16, 8); // twice across, so a tile can start at any column (the ground is not one repeated stamp)
  const x = c.getContext("2d")!;
  t.rows.forEach((row, y) => {
    for (let i = 0; i < 8; i++) {
      x.fillStyle = t.pal[row[i]] ?? "#f0f";
      x.fillRect(i, y, 1, 1);
      x.fillRect(i + 8, y, 1, 1);
    }
  });
  texCache.set(k, c);
  return c;
}
const iconCache = new Map<string, Canvas>();
function sprite(rows: string[], mode: "bright" | "dim"): Canvas {
  const k = rows.join("") + mode;
  let c = iconCache.get(k);
  if (c) return c;
  c = mk(rows[0].length, rows.length);
  const x = c.getContext("2d")!;
  rows.forEach((row, y) => {
    for (let i = 0; i < row.length; i++) {
      const L = row[i];
      if (L === ".") continue;
      x.fillStyle = mode === "dim" ? (L === "K" ? "#1d2028" : "#7b8292") : ICON_PAL[L] ?? "#f0f";
      x.fillRect(i, y, 1, 1);
    }
  });
  iconCache.set(k, c);
  return c;
}

type Stamp = { x: number; y: number; w: number; c: string; faint: boolean };
type Card =
  | { kind: "place"; place: MapPlace }
  | { kind: "ground"; title: string; line: string | null };

export function MapPanel({ widget, onPick, big = false }: { widget: MapWidget; onPick: (text: string) => void; big?: boolean }) {
  const wrap = useRef<HTMLDivElement>(null);
  const cv = useRef<HTMLCanvasElement>(null);
  const centre = useRef<{ x: number; y: number } | null>(null); // art pixels; null until first centred
  const drag = useRef<{ id: number; sx: number; sy: number; cx: number; cy: number; moved: boolean } | null>(null);
  const [size, setSize] = useState({ w: 300, h: 260 });
  const [dpr, setDpr] = useState(() => window.devicePixelRatio || 1);
  const [close, setClose] = useState(false); // false: the country at a glance (about 30 tiles across); true: twice as close
  const [bob, setBob] = useState(0);
  const [ver, setVer] = useState(0); // bumped when the scroll changes
  const [hoverTile, setHoverTile] = useState<[number, number] | null>(null);
  const [card, setCard] = useState<{ c: Card; at: { x: number; y: number } | null } | null>(null);
  const [selected, setSelected] = useState<string | null>(null); // touch: the place whose card a second tap acts on

  // device pixels an art pixel, always a whole number: the wide view is the whole number nearest to 30 tiles across the
  // panel, the close view twice that. In the wide view the icons and the marker are drawn at twice the tile's scale (16
  // art pixels, centred on their tile) so they stay readable.
  const wide = Math.max(1, Math.round((size.w * dpr) / (30 * T)));
  const s = close ? wide * 2 : wide;
  const ik = close ? 1 : 2; // icon scale, in tiles' own scale

  const d = useMemo(() => {
    const chunks = new Map<string, { g: string; r: string }>();
    for (const c of widget.chunks) chunks.set(key(c.cx, c.cy), c);
    const at = (tx: number, ty: number): [string, string] => {
      const c = chunks.get(key(Math.floor(tx / 16), Math.floor(ty / 16)));
      if (!c) return ["?", "."];
      const i = mod(ty, 16) * 16 + mod(tx, 16);
      return [c.g[i] ?? "?", c.r[i] ?? "."];
    };
    const placeAt = new Map<string, MapPlace>();
    for (const p of widget.places) {
      const k = key(p.x, p.y);
      if (!placeAt.has(k) || p.here) placeAt.set(k, p);
    }
    // FN135: a road or river known past the ground seen (the west road drawn far off with nothing said): its name on a tap
    const lineAt = new Map<string, MapWidget["lines"][number]>();
    for (const ln of widget.lines) for (const run of ln.runs) for (const [x, y] of run) {
      const k = key(x, y);
      if (!lineAt.has(k) || ln.kind === "road") lineAt.set(k, ln);
    }
    // the line stamps: continuous pixel paths between tile centres, faint over ground not known
    const stamps: Stamp[] = [];
    const walk = (a: [number, number], b: [number, number], w: number, c: string, each: (px: number, py: number) => void) => {
      let x0 = a[0] * T + T / 2, y0 = a[1] * T + T / 2;
      const x1 = b[0] * T + T / 2, y1 = b[1] * T + T / 2;
      const dx = Math.abs(x1 - x0), dy = -Math.abs(y1 - y0), sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1;
      let err = dx + dy;
      for (;;) {
        each(Math.floor(x0 - w / 2), Math.floor(y0 - w / 2));
        if (x0 === x1 && y0 === y1) break;
        const e2 = 2 * err;
        if (e2 >= dy) { err += dy; x0 += sx; }
        if (e2 <= dx) { err += dx; y0 += sy; }
      }
      void c;
    };
    const style = (kind: string) =>
      kind === "river" ? { order: 0, edge: null, w: 3, c: "#4a86cc" }
      : kind === "lane" ? { order: 1, edge: null, w: 2, c: "#8f7a54" }
      : { order: 2, edge: "#3a2d1c", w: 2, c: "#c2a874" };
    const lines = [...widget.lines].sort((a, b) => style(a.kind).order - style(b.kind).order);
    for (const ln of lines) {
      const st = style(ln.kind);
      for (const run of ln.runs) {
        const pts = run.length === 1 ? [run[0], run[0]] : run;
        // edges first so a crossing of two roads keeps the paths' cores whole
        for (const pass of [0, 1]) {
          if (pass === 0 && !st.edge) continue;
          const w = pass === 0 ? st.w + 2 : st.w;
          const c = pass === 0 ? st.edge! : st.c;
          for (let i = 1; i < pts.length; i++)
            walk(pts[i - 1], pts[i], w, c, (px, py) => {
              const [g] = at(Math.floor((px + w / 2) / T), Math.floor((py + w / 2) / T));
              stamps.push({ x: px, y: py, w, c, faint: g === "?" });
            });
        }
      }
    }
    // region names: written once, on the first of the region's lit tiles (nearest the middle of them first) where the
    // whole name fits in view over lit ground without covering an icon; the drawing picks, these are the candidates
    const labels: { at: [number, number][]; name: string }[] = [];
    widget.regions.forEach((r, ri) => {
      const letter = String.fromCharCode(97 + ri);
      const tiles: [number, number][] = [];
      for (const c of widget.chunks)
        for (let i = 0; i < 256; i++) if (c.r[i] === letter && c.g[i] !== "?") tiles.push([c.cx * 16 + (i % 16), c.cy * 16 + Math.floor(i / 16)]);
      if (!tiles.length || !r.name) return;
      const mx = tiles.reduce((a, t) => a + t[0], 0) / tiles.length, my = tiles.reduce((a, t) => a + t[1], 0) / tiles.length;
      const dist = (t: [number, number]) => (t[0] - mx) ** 2 + (t[1] - my) ** 2;
      labels.push({ at: tiles.sort((a, b) => dist(a) - dist(b)).slice(0, 80), name: r.name });
    });
    return { at, placeAt, lineAt, stamps, labels };
  }, [widget]);

  // sized to the panel's width
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      const w = Math.max(160, Math.floor(el.clientWidth));
      // FN143: in the pop-up the map takes most of the screen's height
      setSize({ w, h: big ? Math.round(Math.max(260, Math.min(window.innerHeight * 0.72, w * 1.3))) : Math.round(Math.min(420, Math.max(200, w * 0.85))) });
      setDpr(window.devicePixelRatio || 1);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // the bob
  useEffect(() => {
    const t = setInterval(() => setBob((b) => 1 - b), 550);
    return () => clearInterval(t);
  }, []);

  const px = widget.player.x * T + T / 2, py = widget.player.y * T + T / 2;
  const recentre = useCallback(() => {
    centre.current = { x: px, y: py };
    setVer((v) => v + 1);
  }, [px, py]);
  if (!centre.current) centre.current = { x: px, y: py };

  // a new turn: keep the scroll, unless the player's marker has left the view
  useEffect(() => {
    const c = centre.current!;
    const halfW = size.w / (2 * (s / dpr)), halfH = size.h / (2 * (s / dpr));
    if (Math.abs(px - c.x) > halfW - 2 || Math.abs(py - c.y) > halfH - 2) recentre();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [widget]);

  const geom = useCallback(() => {
    const W = Math.round(size.w * dpr), H = Math.round(size.h * dpr);
    const c = centre.current!;
    return { W, H, ox: Math.round(W / 2 - c.x * s), oy: Math.round(H / 2 - c.y * s) };
  }, [size, dpr, s]);

  // ---- drawing ----
  useEffect(() => {
    const canvas = cv.current;
    if (!canvas) return;
    const { W, H, ox, oy } = geom();
    if (canvas.width !== W) canvas.width = W;
    if (canvas.height !== H) canvas.height = H;
    const ctx = canvas.getContext("2d")!;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.imageSmoothingEnabled = false;
    const ts = T * s;
    const tx0 = Math.floor(-ox / ts), tx1 = Math.floor((W - ox) / ts);
    const ty0 = Math.floor(-oy / ts), ty1 = Math.floor((H - oy) / ts);
    const pal = widget.palette;
    for (let ty = ty0; ty <= ty1; ty++)
      for (let tx = tx0; tx <= tx1; tx++) {
        const [g] = d.at(tx, ty);
        ctx.drawImage(texture(pal, g), mod(tx * 5 + ty * 3, 8), 0, 8, 8, ox + tx * ts, oy + ty * ts, ts, ts);
      }
    // lines
    for (const st of d.stamps) {
      const x = ox + st.x * s, y = oy + st.y * s, w = st.w * s;
      if (x + w < 0 || y + w < 0 || x > W || y > H) continue;
      ctx.globalAlpha = st.faint ? 0.35 : 1;
      ctx.fillStyle = st.c;
      ctx.fillRect(x, y, w, w);
    }
    ctx.globalAlpha = 1;
    // region names
    const font = `${Math.round((close ? 5 : 7) * s)}px Silkscreen, ui-monospace, monospace`;
    const text = (t: string, cx: number, cy: number, fill: string) => {
      ctx.font = font;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.lineJoin = "round";
      ctx.lineWidth = Math.max(2, s * 1.5);
      ctx.strokeStyle = "#0f1115";
      ctx.strokeText(t, cx, cy);
      ctx.fillStyle = fill;
      ctx.fillText(t, cx, cy);
    };
    // a region's name only where it fits wholly inside lit ground in view; otherwise not drawn (the hover has it)
    ctx.font = font;
    const icon = (tx: number, ty: number) => d.placeAt.has(key(tx, ty)) || (tx === widget.player.x && ty === widget.player.y);
    const reach = ik === 2 ? 1 : 0; // a double-size icon covers half a tile round its own
    // names already on the map (the place the player is at), so a region's name never writes over one
    const taken: [number, number, number, number][] = [];
    for (const p of widget.places)
      if (p.here) {
        const w = ctx.measureText(p.name).width / 2 + s, cx = ox + (p.x + 0.5) * ts, cy = oy + p.y * ts + (ts * (1 + ik)) / 2 + 3 * s;
        taken.push([cx - w, cy - 4 * s, cx + w, cy + 4 * s]);
      }
    for (const l of d.labels) {
      const hw = ctx.measureText(l.name).width / 2 + s, hh = 3.5 * s;
      for (const [lx, ly] of l.at) {
        const cx = ox + (lx + 0.5) * ts, cy = oy + (ly + 0.5) * ts;
        if (cx - hw < 0 || cx + hw > W || cy - hh < 0 || cy + hh > H) continue;
        if (taken.some(([a, b, c, e]) => cx - hw < c && cx + hw > a && cy - hh < e && cy + hh > b)) continue;
        let ok = true;
        const x0 = Math.floor((cx - hw - ox) / ts), x1 = Math.floor((cx + hw - ox) / ts);
        const y0 = Math.floor((cy - hh - oy) / ts), y1 = Math.floor((cy + hh - oy) / ts);
        for (let ty = y0 - reach; ok && ty <= y1 + reach; ty++)
          for (let tx = x0 - reach; tx <= x1 + reach; tx++) {
            const inside = tx >= x0 && tx <= x1 && ty >= y0 && ty <= y1;
            if ((inside && d.at(tx, ty)[0] === "?") || icon(tx, ty)) { ok = false; break; }
          }
        if (ok) {
          taken.push([cx - hw, cy - hh, cx + hw, cy + hh]);
          text(l.name, cx, cy, "rgba(230,230,230,.85)");
          break;
        }
      }
    }
    // the journey: a faint dotted path, its stops marked
    const j = widget.journey;
    if (j && j.path.length) {
      const pts: [number, number][] = [[widget.player.x, widget.player.y], ...j.path];
      ctx.fillStyle = "#a9c0ff";
      let n = 0;
      for (let i = 1; i < pts.length; i++) {
        let x = pts[i - 1][0] * T + T / 2, y = pts[i - 1][1] * T + T / 2;
        const x1 = pts[i][0] * T + T / 2, y1 = pts[i][1] * T + T / 2;
        const steps = Math.max(Math.abs(x1 - x), Math.abs(y1 - y));
        for (let k = 0; k < steps; k++, n++) {
          x += Math.sign(x1 - x);
          y += Math.sign(y1 - y);
          if (n % 4 === 0) ctx.fillRect(ox + (x - 1) * s, oy + (y - 1) * s, 2 * s, 2 * s);
        }
      }
      for (const [sx, sy] of j.stops) {
        const cx = ox + (sx * T + T / 2) * s, cy = oy + (sy * T + T / 2) * s;
        ctx.fillStyle = "#0f1115";
        ctx.fillRect(cx - 3 * s, cy - 3 * s, 6 * s, 6 * s);
        ctx.fillStyle = "#7aa2f7";
        ctx.fillRect(cx - 2 * s, cy - 2 * s, 4 * s, 4 * s);
        ctx.fillStyle = "#0f1115";
        ctx.fillRect(cx - s, cy - s, 2 * s, 2 * s);
      }
    }
    // places
    for (const p of widget.places) {
      const x = ox + p.x * ts, y = oy + p.y * ts;
      if (x + ts < 0 || y + ts < 0 || x > W || y > H) continue;
      const is = ts * ik, ix = x - (is - ts) / 2, iy = y - (is - ts) / 2; // centred on the tile
      ctx.drawImage(sprite(ICONS[p.kind] ?? ICONS.marker, p.state === "been" ? "bright" : "dim"), ix, iy, is, is);
      if (p.job) ctx.drawImage(sprite(JOB_MARK, "bright"), ix + is - 4 * s * ik, iy - s * ik, 5 * s * ik, 5 * s * ik);
      if (p.here) text(p.name, x + ts / 2, iy + is + 3 * s, "#e0af68");
    }
    // the player, bobbing
    ctx.drawImage(sprite(PLAYER, "bright"), ox + widget.player.x * ts - (ts * ik - ts) / 2, oy + (widget.player.y * T - bob * ik) * s - (ts * ik - ts) / 2, ts * ik, ts * ik);
    // the tile under the pointer
    if (hoverTile) {
      ctx.strokeStyle = "rgba(122,162,247,.9)";
      ctx.lineWidth = s;
      ctx.strokeRect(ox + hoverTile[0] * ts + s / 2, oy + hoverTile[1] * ts + s / 2, ts - s, ts - s);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [widget, d, s, ik, close, size, dpr, bob, ver, hoverTile]);

  // ---- pointing ----
  const tileAt = (e: React.PointerEvent): [number, number] => {
    const r = cv.current!.getBoundingClientRect();
    const { ox, oy } = geom();
    const dx = (e.clientX - r.left) * (cv.current!.width / r.width);
    const dy = (e.clientY - r.top) * (cv.current!.height / r.height);
    return [Math.floor((dx - ox) / (T * s)), Math.floor((dy - oy) / (T * s))];
  };
  const cardFor = (tx: number, ty: number): Card => {
    const p = d.placeAt.get(key(tx, ty));
    if (p) return { kind: "place", place: p };
    const [g, r] = d.at(tx, ty);
    const ln = d.lineAt.get(key(tx, ty));
    const lineWords = ln ? `${ln.name}${ln.leads ? ", " + ln.leads : ""}` : null;
    if (g === "?") return ln ? { kind: "ground", title: ln.name, line: (ln.leads ? `Leads ${ln.leads}. ` : "") + "Heard of; the land along it not seen yet." } : { kind: "ground", title: "Not known", line: null };
    const reg = r !== "." ? widget.regions[r.charCodeAt(0) - 97] : undefined;
    return reg && reg.name ? { kind: "ground", title: reg.name, line: [lineWords, reg.line].filter(Boolean).join(". ") || null }
      : { kind: "ground", title: GROUND_NAME[g] ?? "Ground", line: lineWords };
  };
  const rel = (e: React.PointerEvent) => {
    const r = wrap.current!.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  };

  const down = (e: React.PointerEvent<HTMLCanvasElement>) => {
    try { cv.current!.setPointerCapture(e.pointerId); } catch { /* no capture: the drag still works inside the canvas */ }
    const c = centre.current!;
    drag.current = { id: e.pointerId, sx: e.clientX, sy: e.clientY, cx: c.x, cy: c.y, moved: false };
  };
  const move = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const g = drag.current;
    if (g) {
      const dx = e.clientX - g.sx, dy = e.clientY - g.sy;
      if (!g.moved && Math.hypot(dx, dy) > 5) {
        g.moved = true;
        setCard(null);
        setHoverTile(null);
      }
      if (g.moved) {
        centre.current = { x: g.cx - dx / (s / dpr), y: g.cy - dy / (s / dpr) };
        setVer((v) => v + 1);
      }
      return;
    }
    if (e.pointerType === "mouse") {
      const [tx, ty] = tileAt(e);
      setHoverTile([tx, ty]);
      setCard({ c: cardFor(tx, ty), at: rel(e) });
    }
  };
  const up = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const g = drag.current;
    drag.current = null;
    if (!g || g.moved) return;
    const [tx, ty] = tileAt(e);
    const p = d.placeAt.get(key(tx, ty));
    if (e.pointerType === "mouse") {
      if (p) onPick(p.go);
      return;
    }
    // touch: the first tap shows the card, a second tap on the same place picks it
    if (p && selected === p.id) {
      onPick(p.go);
      return;
    }
    setSelected(p ? p.id : null);
    setHoverTile([tx, ty]);
    setCard({ c: cardFor(tx, ty), at: null });
  };
  const leave = (e: React.PointerEvent) => {
    if (e.pointerType === "mouse" && !drag.current) {
      setHoverTile(null);
      setCard(null);
    }
  };

  const cardView = card && (
    <div className="map-card" style={card.at ? { left: Math.min(card.at.x + 12, size.w - 190), top: Math.min(card.at.y + 12, size.h - 90) } : { left: 6, right: 6, bottom: 6 }} role="status">
      {card.c.kind === "place" ? (
        <>
          <div className="map-card-name">{card.c.place.name}</div>
          <div className="muted small">{card.c.place.state === "been" ? "been there" : "heard of"}</div>
          {card.c.place.told.map((t, i) => <div key={i} className="small">{t}</div>)}
          {card.c.place.way && <div className="small">{card.c.place.way}</div>}
          {card.c.place.job && <div className="small map-card-job">Job: {card.c.place.job}</div>}
          {card.c.place.changed && <div className="small muted">{card.c.place.changed}</div>}
          {!card.at && <div className="muted small">Tap again to go there</div>}
        </>
      ) : (
        <>
          <div className="map-card-name">{card.c.title}</div>
          {card.c.line && <div className="small">{card.c.line}</div>}
        </>
      )}
    </div>
  );

  return (
    <section className="panel map-panel">
      <div className="map-head">
        <h3>{widget.title || "Map"}</h3>
        <div className="map-buttons">
          <button className="link small" onClick={recentre}>Centre</button>
          <button className="link small" onClick={() => setClose(!close)}>{close ? "Zoom out" : "Zoom in"}</button>
        </div>
      </div>
      <div className="map-wrap" ref={wrap}>
        <canvas ref={cv} className="map-canvas" style={{ width: size.w, height: size.h }} onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={() => (drag.current = null)} onPointerLeave={leave} />
        {cardView}
      </div>
      {widget.journey && <div className="map-journey small">{widget.journey.label}</div>}
      {widget.unplaced.length > 0 && (
        <div className="map-list">
          <h4>Heard of, whereabouts unknown</h4>
          <ul>{widget.unplaced.map((n, i) => <li key={i} className="small">{n}</li>)}</ul>
        </div>
      )}
      {widget.spots.length > 0 && (
        <ul className="map-spots small">
          {widget.spots.map((p, i) => <li key={i} className={p.here ? "here" : "muted"}>{p.here ? "▸ " : ""}{p.name}</li>)}
        </ul>
      )}
    </section>
  );
}
