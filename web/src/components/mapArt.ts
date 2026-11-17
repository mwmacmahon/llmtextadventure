/* The map's art, in the manner of Stone.tsx: 8x8 pixel tiles and icons defined in code as rows of letters, a small palette
 * per palette name, no image files. Drawn scaled up whole, never smoothed. To add a ground, an icon or a palette: add a few
 * lines here (every row is exactly 8 letters; `.` is transparent in an icon). `checkArt()` is run by the demo page. */

export type Tex = { pal: Record<string, string>; rows: string[] };

/** The 14 grounds' textures (the `?` one included), per palette name. `forest` is the only palette so far. */
export const GROUNDS: Record<string, Record<string, Tex>> = {
  forest: {
    // not known: a shade above the panel's own colour, with a faint pattern, so it reads as "not known" and not as empty
    "?": { pal: { a: "#1b1f28", b: "#222733" }, rows: ["aaaaaaaa", "aaabaaaa", "aaaaaaaa", "aaaaaaab", "aaaaaaaa", "abaaaaaa", "aaaaaaaa", "aaaabaaa"] },
    m: { pal: { a: "#437c35", b: "#4d8b3e", c: "#376b2c", d: "#62a04c" }, rows: ["aaabaaaa", "aaaaaaca", "abaaaaaa", "aaaaadaa", "aaaaaaaa", "aacaaaba", "aaaaaaaa", "abaaaaad"] },
    w: { pal: { a: "#2f6b2a", b: "#3f8a35", c: "#1f4a1c", d: "#66b24e" }, rows: ["aabbaaaa", "abddbaab", "bbbbbaad", "acbbcabb", "aaccaaaa", "aabbaaaa", "baddbaab", "caabbcaa"] },
    W: { pal: { a: "#1d3f1c", b: "#2a5626", c: "#112a12", d: "#3c7234" }, rows: ["aabbaaaa", "abdbbaab", "bbbbbaaa", "acbbcabb", "aaccaaaa", "aabbaaaa", "abdbbaab", "caabbcaa"] },
    h: { pal: { a: "#6f7f3a", b: "#8a9a4a", c: "#566330", d: "#a4b25e" }, rows: ["aaaaaaaa", "aaabbaaa", "aabddbaa", "abbbbbca", "bbbbbccc", "acccccca", "aaaaaaaa", "aaaaaaaa"] },
    M: { pal: { a: "#6a6f78", b: "#8b919b", c: "#464a52", d: "#d6dae0" }, rows: ["aaaddaaa", "aaabbdaa", "aabbbbca", "abbbbbcc", "bbbbbcca", "bbbccccc", "acccccca", "aaaaaaaa"] },
    b: { pal: { a: "#4a5a30", b: "#3a4826", c: "#5a6a3a", d: "#2f5a58" }, rows: ["aaaaaaaa", "abbaaddd", "aaaaadda", "aaacaaaa", "ddaaaabb", "dddaaabb", "aaaaacaa", "aabaaaaa"] },
    f: { pal: { a: "#8a7a38", b: "#a08c42", c: "#6c5e2c", d: "#c0a850" }, rows: ["bbbbbbbb", "aaaaaaaa", "cccccccc", "adaadaad", "bbbbbbbb", "aaaaaaaa", "cccccccc", "aaaaaaaa"] },
    "~": { pal: { a: "#2c5a9a", b: "#3a6cb0", c: "#244a82", d: "#7aa8d8" }, rows: ["aaaaaaaa", "aadbaaaa", "aaaaaaaa", "aaaaaabb", "caaaaaaa", "aaaabbaa", "aaaaaaaa", "bbaaaaca"] },
    s: { pal: { a: "#c8b478", b: "#d8c68a", c: "#b09c62", d: "#e8dca8" }, rows: ["aaaaaaaa", "aaabaaaa", "aaaaaaca", "aaaaaaaa", "abaaadaa", "aaaaaaaa", "aaacaaaa", "aaaaaaba"] },
    B: { pal: { a: "#2a2420", b: "#3a3029", c: "#1a1512", d: "#5a3a26" }, rows: ["aaaaaaaa", "abaaaaca", "aaaaaaaa", "aaacaabb", "aaaaaaaa", "dabaaaaa", "aaaaacaa", "aaaaaaaa"] },
    L: { pal: { a: "#c8421c", b: "#e8741e", c: "#8a2a14", d: "#f8c84a" }, rows: ["aabaaaca", "baaadaaa", "aaaabbaa", "caaaaaaa", "aabaaadb", "aaaaaaaa", "dbaacaab", "aaaaaaaa"] },
    R: { pal: { a: "#5c5650", b: "#78726a", c: "#3a3631", d: "#9a948a" }, rows: ["abbaaccb", "bddbaaaa", "aaaaabba", "ccaabddb", "bbaaaaaa", "ddbaacca", "aaaabbba", "acaaaddb"] },
    S: { pal: { a: "#dfe6ee", b: "#f2f6fa", c: "#b8c4d4", d: "#ffffff" }, rows: ["aaaaaaaa", "aabaaaca", "aaaaaaaa", "aaadaaaa", "caaaaaba", "aaaaaaaa", "abaaacaa", "aaaaaaaa"] },
  },
};

/** An icon's own colours, shared by every palette so far: one letter, one colour. `K` is the outline. */
export const ICON_PAL: Record<string, string> = {
  K: "#14100c", k: "#3a2f26", n: "#7a5a3a", t: "#c0a070", s: "#aab0b8", S: "#646b76", w: "#ececec", r: "#c0452f",
  y: "#e8b84a", b: "#4a7fc0", g: "#4a9a3a", G: "#2a5a24", o: "#f08a2a", p: "#7a5a9a",
};

export const ICONS: Record<string, string[]> = {
  house: ["...KK...", "..KrrK..", ".KrrrrK.", "KrrrrrrK", ".KttttK.", ".KtyKtK.", ".KttKtK.", ".KKKKKK."],
  village: ["..K..K..", ".KrK.KrK", "KrrrKrrK", "KttKKttK", "KtKKtKtK", "KttKtKtK", "KKKKKKKK", "........"],
  town: ["...K..K.", "..KsKKsK", "..KsKKsK", ".KKKKKKK", "KrKrrKrK", "KtKttKtK", "KtKtyKtK", "KKKKKKKK"],
  hut: ["........", "...KK...", "..KttK..", ".KttttK.", "KttttttK", ".KnnKnK.", ".KnnKnK.", ".KKKKKK."],
  camp: ["...K....", "..KtK...", ".KtttK.o", "KttKttKo", "KtKKKtKy", "KKKnnKKK", "..nKKn..", "........"],
  tower: ["..K..K..", "..KssK..", "..KssK..", "..KsSK..", "..KsSK..", "..KsSK..", ".KKsSKK.", ".KKKKKK."],
  fort: ["K.K..K.K", "KsKKKKsK", "KssssssK", "KsSssSsK", "KssKKssK", "KsSKKSsK", "KssKKssK", "KKKKKKKK"],
  castle: ["K.K.KK.K", "KsKKssKs", "KssssssK", "KssSSssK", "KsKssKsK", "KssKKssK", "KsSKKSsK", "KKKKKKKK"],
  ruin: ["........", ".K..K...", ".sK.sK.K", ".sK.sKsK", ".sSKsSsK", ".sSKKSsK", "KKSKKKKK", "K.KK.KK."],
  cave: ["..KKKK..", ".KSSSSK.", "KSSSSSSK", "KSSkkSSK", "KSkkkkSK", "KSkkkkSK", "KSkkkkSK", "KKKKKKKK"],
  mine: ["..KKKK..", ".KnnnnK.", "KnKKKKnK", "KnKkkKnK", "KnKkkKnK", "KnKkkKnK", "KnKkkKnK", "KKKKKKKK"],
  shrine: ["...KK...", "..KyyK..", "...KK...", "..KssK..", ".KsssSK.", "..KssK..", ".KsssSK.", ".KKKKKK."],
  stones: ["........", "..K.K...", ".KsKsK.K", ".KsKsKsK", ".KsKsKsK", ".KSKSKSK", "KKSKSKSK", "KKKKKKKK"],
  grave: ["..KKKK..", ".KssssK.", ".KsKKsK.", ".KssssK.", ".KssKsK.", ".KssssK.", "GGKSSKGG", "KKKKKKKK"],
  well: ["..KKKK..", "..KnnK..", ".KKKKKK.", "KsKbbKsK", "KssbbssK", "KsSSSSsK", "KSSSSSSK", "KKKKKKKK"],
  mill: ["..K..K..", "...KK...", "K.KnnK.K", ".KKnnKK.", "..KnnK..", ".KtttK..", ".KtKtK..", ".KKKKK.."],
  farm: ["........", "..KrrK..", ".KrrrrK.", ".KttttK.", ".KtKKtK.", "gGgGgGgG", "GgGgGgGg", "gGgGgGgG"],
  ford: ["........", "........", "bbbbbbbb", "b.sbb.sb", "bbbsbbbb", "bsbbbsbb", "bbbbbbbb", "........"],
  bridge: ["........", "KKKKKKKK", "KtntntnK", "KttttttK", "KKKKKKKK", "bKbbbbKb", "bKbbbbKb", "bbbbbbbb"],
  pond: ["........", "..KKKK..", ".KbbbbK.", "KbwbbbbK", "KbbbbbbK", ".KbbbbK.", "..KKKK..", "........"],
  clearing: ["..g..g..", ".gGg.gGg", "........", "..y..w..", "........", ".gGg.gGg", "..g..g..", "........"],
  crater: ["..oK.Ko.", ".KoooKK.", "KKoyyoKK", "KoyyyyoK", "KoyyyyoK", "KKooooKK", ".KKKoKK.", "..K.KK.."],
  inn: ["..K.yK..", ".KrrrrK.", "KrrrrrrK", "KttttttK", "KtbKtbKK", "KttKttKt", "KttKttKK", "KKKKKKKK"],
  quarry: ["........", "K.....K.", "KsK..KsK", "KssKKssK", "KsSssSsK", "KsSsSSsK", "KSSSSSSK", "KKKKKKKK"],
  marker: ["..KKKK..", ".KyyyyK.", ".KyKKyK.", "..KyyK..", "...KyK..", "...KK...", "..KyyK..", "...KK..."],
};

/** The player's marker: two frames (the bob is a one-pixel lift, done by the panel). */
export const PLAYER: string[] = ["..KKKK..", ".KwwwwK.", ".KwKKwK.", "..KwwK..", ".KbbbbK.", "KbbKKbbK", ".KbbbbK.", ".KK..KK."];

/** A small gold mark for "a job points here". */
export const JOB_MARK: string[] = [".KKK.", "KyyyK", "KyKyK", "KyyyK", ".KKK."];

/** Dev check: every texture and icon is 8x8 and uses only letters its palette has. Returns the problems found. */
export function checkArt(): string[] {
  const bad: string[] = [];
  const grid = (name: string, rows: string[], w: number, h: number, has: (c: string) => boolean) => {
    if (rows.length !== h) bad.push(`${name}: ${rows.length} rows`);
    rows.forEach((r, i) => {
      if (r.length !== w) bad.push(`${name} row ${i}: ${r.length} letters`);
      for (const c of r) if (c !== "." && !has(c)) bad.push(`${name} row ${i}: letter ${c} not in palette`);
    });
  };
  for (const [p, set] of Object.entries(GROUNDS)) {
    for (const g of "?mwWhMbf~sBLRS") if (!set[g]) bad.push(`${p}: no ground ${g}`);
    for (const [g, t] of Object.entries(set)) grid(`${p}/${g}`, t.rows, 8, 8, (c) => c in t.pal);
  }
  for (const [k, rows] of Object.entries(ICONS)) grid(`icon ${k}`, rows, 8, 8, (c) => c in ICON_PAL);
  grid("player", PLAYER, 8, 8, (c) => c in ICON_PAL);
  grid("job mark", JOB_MARK, 5, 5, (c) => c in ICON_PAL);
  return bad;
}
