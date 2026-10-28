// Typed client for the engine API. The UI schema types mirror server/engine/game.py.

export type Chip = { label: string; value: string };
export type Tone = "neutral" | "ok" | "warn" | "bad" | "info";
export type TableCell = { text: string; tone: Tone };
export type EntityCard = { id: string; title: string; subtitle?: string | null; badges: Chip[]; details: Chip[]; notes: string[] };
export type Choice = { label: string; command: string; args: Record<string, unknown> };
export type Option = { id: string; label: string };
export type Param = { name: string; label: string; options: Option[] };
export type CommandSpec = { id: string; label: string; mode: "engine" | "narrated"; params: Param[]; hint: string };

export type Widget =
  | { type: "status_strip"; chips: Chip[] }
  | { type: "meter"; label: string; value: number; min: number; max: number; tier?: string | null; thresholds: number[] }
  | { type: "table"; title: string; columns: string[]; rows: TableCell[][] }
  | { type: "entity_cards"; title: string; cards: EntityCard[] }
  | { type: "list"; title: string; items: Chip[] }
  | { type: "log"; title: string; lines: string[] }
  | { type: "choices"; title?: string | null; choices: Choice[] }
  | { type: "commands"; title?: string | null; items: CommandSpec[] };

export type UISchema = { phase: string; free_text: boolean; placeholder: string; panels: Widget[] };

export type TranscriptRow = {
  seq: number;
  turn: number;
  role: "player" | "bulletin" | "narrator" | "system_note" | "mechanics" | "command" | "result";
  text: string;
  created: string;
};

export type CheckSummary = { label: string; outcome: string; roll: number | null; total: number; target: number };
export type Mechanics = {
  kind: string | null;
  elapsed: number;
  checks: CheckSummary[];
  events: string[];
  expired: string[];
  happenings: { id: string; who: string[]; reason: string | null }[];
  applied: string[];
  rejected: { path: string; reason: string; value?: unknown }[];
  drift?: string[];
  issues: string[];
};

export type Origin = { forked_from?: string; at_turn?: number; imported?: boolean; original_id?: string; exported?: string };
export type InstanceSummary = { id: string; game: string; game_version: string; title: string; created: string; turn: number; origin: Origin };
export type InstanceView = InstanceSummary & { ui: UISchema; transcript: TranscriptRow[]; ending?: string | null };
export type GameInfo = { name: string; title: string; description: string; version: string; setup: Record<string, { id: string; name: string }[]> };

export type LedgerEntry = { seq: number; turn: number; kind: string; created: string; payload: Record<string, any> };

export type TokenUsage = { input_tokens: number; output_tokens: number; cache_read_input_tokens: number; cache_creation_input_tokens: number };
export type RoleUsage = { calls: number; model: string | null; seconds: number; usage: TokenUsage; usd: number; priced: boolean };
export type InstanceUsage = { id: string; turn: number; roles: Record<string, RoleUsage>; usd: number; priced: boolean; calls: number };

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
  undo: (id: string, turn?: number) =>
    fetch(`/api/instances/${id}/undo`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ turn: turn ?? null }) }).then((r) => j<InstanceView>(r)),
  fork: (id: string, turn?: number, title?: string) =>
    fetch(`/api/instances/${id}/fork`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ turn: turn ?? null, title: title ?? null }) }).then((r) => j<InstanceView>(r)),
  rename: (id: string, title: string) =>
    fetch(`/api/instances/${id}`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ title }) }).then((r) => j<InstanceSummary>(r)),
  remove: (id: string) => fetch(`/api/instances/${id}`, { method: "DELETE" }).then((r) => j<{ ok: boolean }>(r)),
  exportUrl: (id: string) => `/api/instances/${id}/export`,
  importDoc: (doc: unknown) =>
    fetch("/api/instances/import", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(doc) }).then((r) => j<InstanceView>(r)),
  ledger: (id: string, turn?: number) => fetch(`/api/instances/${id}/ledger${turn != null ? `?turn=${turn}` : ""}`).then((r) => j<LedgerEntry[]>(r)),
  usage: (id: string) => fetch(`/api/instances/${id}/usage`).then((r) => j<InstanceUsage>(r)),
};

export type TurnEvent =
  | { event: "command"; data: { ok: boolean; text: string; mode: "engine" | "narrated" | null; label?: string; turn?: number } }
  | { event: "summary"; data: { status: "running" | "done" | "failed"; turns: number[]; chars?: number; error?: string } }
  | { event: "adjudication"; data: { kind: string; summary: string; time_minutes: number; clarify_question?: string | null } }
  | { event: "resolution"; data: { checks: Record<string, any>[]; fired: { event_id: string; variant: string }[]; expired: { event_id: string }[]; elapsed: number; directives: string[] } }
  | { event: "bulletin"; data: { turn: number; text: string } }
  | { event: "text"; data: { t: string } }
  | { event: "mechanic"; data: { turn: number; text: string; data: Record<string, any> } }
  | { event: "referee"; data: { delta: Record<string, any> | null; world?: Record<string, any> | null; report?: { applied: string[]; rejected: unknown[] }; error?: string } }
  | { event: "done"; data: { turn: number; text: string; note?: string | null; model: string; usage: Record<string, number>; seconds: number; mechanics: Mechanics; ending?: string | null; ui: UISchema } }
  | { event: "error"; data: { message: string; step?: string } };

/** POST a typed turn and stream server-sent events back. */
export function streamTurn(id: string, text: string, signal?: AbortSignal): AsyncGenerator<TurnEvent> {
  return streamSse(`/api/instances/${id}/turn`, { text }, signal);
}

/** POST a clicked command; engine commands answer with command+done, narrated ones stream a full turn. */
export function streamCommand(id: string, command: string, args: Record<string, unknown>, signal?: AbortSignal): AsyncGenerator<TurnEvent> {
  return streamSse(`/api/instances/${id}/command`, { command, args }, signal);
}

async function* streamSse(url: string, body: unknown, signal?: AbortSignal): AsyncGenerator<TurnEvent> {
  const r = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
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
