import type { InstanceSummary } from "./api";

/** "3 h ago": last played, relative. */
export function ago(iso: string): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "";
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 86400 * 45) return `${Math.floor(s / 86400)} d ago`;
  return new Date(t).toLocaleDateString();
}

/** A branch or import mark for a save. */
export function originMark(i: InstanceSummary): string | null {
  if (i.origin.forked_from) return `branch @${i.origin.at_turn ?? "?"}`;
  if (i.origin.imported) return "imported";
  return null;
}

/** An ending's sentence cut short for the save's line (the card shows it whole). */
export function endingShort(e: string): string {
  return e.length > 48 ? e.slice(0, 46).replace(/\s+\S*$/, "") + "…" : e;
}
