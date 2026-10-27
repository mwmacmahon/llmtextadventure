// Typed client for the engine API. The UI schema types mirror server/engine/game.py.

export type Chip = { label: string; value: string };
export type Tone = "neutral" | "ok" | "warn" | "bad" | "info";
export type TableCell = { text: string; tone: Tone };
export type EntityCard = { id: string; title: string; subtitle?: string | null; badges: Chip[]; details: Chip[]; notes: string[] };
export type Choice = { label: string; command: string; args: Record<string, unknown> };

export type Widget =
  | { type: "status_strip"; chips: Chip[] }
  | { type: "meter"; label: string; value: number; min: number; max: number; tier?: string | null; thresholds: number[] }
  | { type: "table"; title: string; columns: string[]; rows: TableCell[][] }
  | { type: "entity_cards"; title: string; cards: EntityCard[] }
  | { type: "list"; title: string; items: Chip[] }
  | { type: "log"; title: string; lines: string[] }
  | { type: "choices"; title?: string | null; choices: Choice[] };

export type UISchema = { phase: string; free_text: boolean; placeholder: string; panels: Widget[] };

export type TranscriptRow = { seq: number; turn: number; role: "player" | "bulletin" | "narrator" | "system_note"; text: string; created: string };

export type InstanceView = { id: string; game: string; title: string; created: string; turn: number; ui: UISchema; transcript: TranscriptRow[] };
export type InstanceSummary = { id: string; game: string; title: string; created: string; turn: number };
export type GameInfo = { name: string; title: string; description: string; version: string; setup: Record<string, { id: string; name: string }[]> };

export type LedgerEntry = { seq: number; turn: number; kind: string; created: string; payload: Record<string, any> };

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

export const api = {
  games: () => fetch("/api/games").then((r) => j<GameInfo[]>(r)),
  instances: () => fetch("/api/instances").then((r) => j<InstanceSummary[]>(r)),
  instance: (id: string) => fetch(`/api/instances/${id}`).then((r) => j<InstanceView>(r)),
  create: (game: string, setup: Record<string, unknown>) =>
    fetch("/api/instances", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ game, setup }) }).then((r) => j<InstanceView>(r)),
  undo: (id: string) => fetch(`/api/instances/${id}/undo`, { method: "POST" }).then((r) => j<InstanceView>(r)),
  ledger: (id: string, turn?: number) => fetch(`/api/instances/${id}/ledger${turn != null ? `?turn=${turn}` : ""}`).then((r) => j<LedgerEntry[]>(r)),
};

export type TurnEvent =
  | { event: "bulletin"; data: { turn: number; text: string } }
  | { event: "text"; data: { t: string } }
  | { event: "done"; data: { turn: number; text: string; note?: string | null; model: string; usage: Record<string, number>; seconds: number; ui: UISchema } }
  | { event: "error"; data: { message: string } };

/** POST a turn and stream server-sent events back. */
export async function* streamTurn(id: string, text: string, signal?: AbortSignal): AsyncGenerator<TurnEvent> {
  const r = await fetch(`/api/instances/${id}/turn`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ text }),
    signal,
  });
  if (!r.ok || !r.body) throw new Error(`${r.status} ${await r.text()}`);
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      let event = "message";
      let data = "";
      for (const line of chunk.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (data) yield { event, data: JSON.parse(data) } as TurnEvent;
    }
  }
}
