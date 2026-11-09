// Typed client for the engine API. The UI schema types mirror server/engine/game.py.

export type Tone = "neutral" | "ok" | "warn" | "bad" | "info";
export type Chip = { label: string; value: string; tone?: Tone | null };
export type TableCell = { text: string; tone: Tone };
// B93: one quest shape in every game: the title, one line (what is wanted, by whom, for what), the standing word, the giver.
export type QuestRow = { title: string; line: string; standing: string; giver: string; tone: Tone };
export type EntityCard = { id: string; title: string; subtitle?: string | null; badges: Chip[]; details: Chip[]; notes: string[] };
export type Choice = { label: string; command: string; args: Record<string, unknown> };
export type Option = { id: string; label: string };
export type Param = { name: string; label: string; options: Option[] };
// A command's own panel (the level-up screen, B92): what is new, score points to spend, cards to pick, Confirm.
export type CommandPanel = {
  title: string; lines: Chip[]; points: number; per_stat: number; stats: { id: string; label: string }[];
  cards: Chip[]; pick: number; confirm: string;
};
export type CommandSpec = { id: string; label: string; mode: "engine" | "narrated"; params: Param[]; hint: string; enabled?: boolean; panel?: CommandPanel | null };
export type MeterWidget = {
  type: "meter"; label: string; value: number; min: number; max: number; tier?: string | null; thresholds: number[];
  text?: string | null; tone?: Tone | null; chips?: Chip[];
};

export type Widget =
  | { type: "status_strip"; chips: Chip[] }
  | MeterWidget
  | { type: "meter_group"; title?: string | null; meters: MeterWidget[] }
  | { type: "table"; title: string; columns: string[]; rows: TableCell[][] }
  | { type: "entity_cards"; title: string; cards: EntityCard[] }
  | { type: "list"; title: string; items: Chip[]; layout?: "rows" | "grid" | "stack" }
  | { type: "log"; title: string; lines: string[] }
  | { type: "choices"; title?: string | null; choices: Choice[] }
  | { type: "commands"; title?: string | null; items: CommandSpec[] }
  | { type: "quests"; title: string; rows: QuestRow[] };

export type UISchema = { phase: string; free_text: boolean; placeholder: string; panels: Widget[] };

export type TranscriptRow = {
  seq: number;
  turn: number;
  role: "player" | "bulletin" | "narrator" | "system_note" | "mechanics" | "command" | "result" | "ask" | "aside";
  text: string;
  created: string;
  undone: number;     // 0: live; else the undo that undid it (the log strikes it through; nothing a model reads sees it)
};

export type CheckSummary = { label: string; outcome: string; roll: number | null; total: number; target: number };
export type Mechanics = {
  kind: string | null;
  elapsed: number;
  calls: { call: string | null; mechanic: string | null; outcome: string | null;
           consequence?: { roll: number; tier: string; source: string; complication?: { kind: string; fact: string }; mark?: { kind: string; fact: string }; way_closed?: { fact: string } } }[];
  events: string[];
  expired: string[];
  happenings: { id: string; who: string[]; reason: string | null }[];
  applied: string[];
  rejected: { path: string; reason: string; value?: unknown }[];
  drift?: string[];
  levers?: { id: string; status: "applied" | "blocked" | "not_completed"; text: string }[];
  pending?: { fired: string[]; new: string[]; resolved: string[] };
  issues: string[];
  rewritten?: { hint: string; attempt: number; by?: string } | null;
  rulings?: { rule: string; what: string; fix: string; serious: boolean }[];
  seen?: string[];   // what the player should see change this turn (ISSUES B18, D143)
  timing?: { result_minutes: number; lost_asked: number; lost: number; added: number; stopped_at?: string };   // D146
};

export type Settings = {
  guard: { mode: string; max_retells: number };
  modes: Record<string, string>;
  progress: { default_chars: number };
  guard_from: "settings" | "profile" | "this server";
  shared_guard: string;
  profile: string;
  profile_guard: string | null;
  roles: Record<string, { provider: string; model: string; effort: string | null }>;
  dev_pin: boolean;                                  // dev mode asks for a pin on this server
  dev_mode?: boolean;                                // false: this server has no dev mode (a player's server, B232)
  difficulties: { id: string; name: string }[];
};

// The profile picker (server/engine/picker.py): a profile is the whole configuration of a play.
export type ProfileSummary = { name: string; note: string; local: boolean; base: string; model: string | null };
export type ProfileList = {
  active: string | null;
  label: string;
  base: string;
  local: boolean;
  loading: { name: string; model: string; since: number } | null;
  busy: boolean;
  profiles: ProfileSummary[];
  errors: { name: string; error: string }[];
};
export type RoleCard = {
  provider: string; model: string; where: string; max_tokens: number; effort: string | null;
  sampler: Record<string, number>; thinking: string;
};
export type Dial = { value: string | number | null; from: string };
export type ModuleLevel = { id: string; label: string; cuts: string; built: boolean; level: string; what: string; levels: string[] };
export type BoxState = {
  configured: boolean; state: string; loading: boolean; active: string | null; model: string | null;
  slots: number | null; slot_ctx: number | null; sleeping: boolean | null; requested_ctx: string | number | null; box_ctx: string | null;
};
export type Price = { input: number; output: number; cache_read: number; cache_write: number };
export type TurnCost = { turns: number; calls: number; usd_total: number; usd_per_turn: number | null; priced: boolean; prices: Record<string, Price> };
export type ProfileCard = ProfileSummary & {
  active: boolean;
  roles: Record<string, RoleCard>;
  dials: { stakes: Dial; checks: Dial; guard: Dial; target_offset: Record<string, Dial> };
  modules: ModuleLevel[];
  server: Record<string, string>;
  box?: BoxState;
  cost?: TurnCost;
};

export type Origin = { forked_from?: string; at_turn?: number; imported?: boolean; original_id?: string; exported?: string };
export type InstanceSummary = {
  id: string; game: string; game_version: string; title: string; created: string; turn: number; origin: Origin;
  updated: string;                 // last played (ISO)
  difficulty: string;              // easy | normal | hard
  save_line: Chip[];               // the game's line for this save (who, where, when), plus the difficulty when not normal
  ending: string | null;
  hidden: boolean;                 // a hidden game's save (shown in dev mode only)
};
export type InstanceView = InstanceSummary & {
  ui: UISchema; transcript: TranscriptRow[];
  redo?: { mark: number; to_turn: number; from_turn: number } | null;   // the undo a Redo brings back, while nothing has diverged
};
export type SaveCard = InstanceSummary & { ui: UISchema; last: { turn: number; text: string; clock: string } | null };
export type SetupOption = { id: string; name: string };
// A setup key is the plain list (a select) or a field (ISSUES B21): the label is the whole hint unless the game gives one.
export type SetupField = {
  kind?: "select" | "text" | "textarea" | "checks";
  label?: string;
  show_if?: Record<string, string>;   // shown (and sent) only when these fields hold these values: a class's kit (B92)
  pick?: number;                      // checks: exactly this many ticked
  hint?: string;
  required?: boolean;
  options?: (SetupOption | string)[];
  default?: string | null;
};
export type GameInfo = {
  name: string; title: string; description: string; version: string; setup: Record<string, SetupOption[] | SetupField>;
  saves: number; deaths: number; hidden: boolean;
};

// The graveyard (server/engine/graveyard.py): every death, kept for good, an undone one too. No model reads it.
export type Grave = {
  id: string; game: string; instance_id: string; turn: number; created: string; character: string; line: Chip[];
  place: string; day: number | null; clock: string; cause: string; epitaph: string; score: Record<string, number | string>; undone: boolean;
};
/** A gravestone's card (and the play page's death card): the grave, the final state as panels, one line under the cause. */
export type GraveCard = Grave & { game_title: string; save_stands: boolean; ui: UISchema | null; death_line: string | null; cause_from: string };
export type Character = { game: string; game_title: string; key: string; name: string; save?: string; deaths: number; best: { level?: number; turns?: number; days?: number }; last: string; graves: Grave[] };
export type Gallery = { characters: Character[]; deaths: number };

export type LedgerEntry = { seq: number; turn: number; kind: string; created: string; payload: Record<string, any> };

export type TokenUsage = { input_tokens: number; output_tokens: number; cache_read_input_tokens: number; cache_creation_input_tokens: number };
export type RoleUsage = { calls: number; model: string | null; seconds: number; usage: TokenUsage; usd: number; priced: boolean };
export type InstanceUsage = { id: string; turn: number; roles: Record<string, RoleUsage>; usd: number; priced: boolean; calls: number };

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(`${r.status} ${(await r.text()) || r.statusText}`);
  return r.json();
}

// Dev mode (Settings): kept in this browser; while it is on, every request carries X-Dev (and the pin, when the server
// asks for one), and the server shows the hidden games.
const DEV_KEY = "ta.dev";
const PIN_KEY = "ta.devPin";

function readKey(k: string): string | null {
  try {
    return localStorage.getItem(k);
  } catch {
    return null;
  }
}

function writeKey(k: string, v: string | null) {
  try {
    if (v == null) localStorage.removeItem(k);
    else localStorage.setItem(k, v);
  } catch {
    /* storage blocked: dev mode lasts this page only */
  }
}

let devOn = readKey(DEV_KEY) === "1";
let devPin = readKey(PIN_KEY) ?? "";

export const devMode = {
  on: () => devOn,
  set(on: boolean, pin = "") {
    devOn = on;
    devPin = on ? pin : "";
    writeKey(DEV_KEY, on ? "1" : null);
    writeKey(PIN_KEY, on && pin ? pin : null);
    dispatchEvent(new Event("ta-dev"));
  },
};

function devHeaders(): Record<string, string> {
  if (!devOn) return {};
  return devPin ? { "X-Dev": "1", "X-Dev-Pin": devPin } : { "X-Dev": "1" };
}

/** fetch with the dev-mode headers on every request while dev mode is on. A 403 to them means the server's pin changed
 *  (or was set since): dev mode turns off in this browser and the request goes again without them. */
async function req(url: string, init: RequestInit = {}): Promise<Response> {
  const own = (init.headers as Record<string, string>) ?? {};
  const r = await fetch(url, { ...init, headers: { ...devHeaders(), ...own } });
  if (r.status === 403 && devOn) {
    devMode.set(false);
    return fetch(url, { ...init, headers: own });
  }
  return r;
}

const JSON_HEADERS = { "content-type": "application/json" };

export const api = {
  games: () => req("/api/games").then((r) => j<GameInfo[]>(r)),
  /** Try the dev headers before keeping them: a wrong pin answers 403. */
  checkDev: (pin: string) => fetch("/api/games", { headers: pin ? { "X-Dev": "1", "X-Dev-Pin": pin } : { "X-Dev": "1" } }).then((r) => r.ok),
  instances: (game?: string) => req(`/api/instances${game ? `?game=${encodeURIComponent(game)}` : ""}`).then((r) => j<InstanceSummary[]>(r)),
  instance: (id: string) => req(`/api/instances/${id}`).then((r) => j<InstanceView>(r)),
  card: (id: string) => req(`/api/instances/${id}/card`).then((r) => j<SaveCard>(r)),
  setDifficulty: (id: string, difficulty: string) =>
    req(`/api/instances/${id}/difficulty`, { method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ difficulty }) }).then((r) => j<InstanceSummary>(r)),
  create: (game: string, setup: Record<string, unknown>) =>
    req("/api/instances", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ game, setup }) }).then((r) => j<InstanceView>(r)),
  // B105: a question to the game master out of the story; nothing moves
  ask: (id: string, text: string) =>
    req(`/api/instances/${id}/ask`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ text }) })
      .then((r) => j<{ ok: boolean; text: string; view?: InstanceView }>(r)),
  redo: (id: string) => req(`/api/instances/${id}/redo`, { method: "POST" }).then((r) => j<InstanceView>(r)),
  undo: (id: string, turn?: number) =>
    req(`/api/instances/${id}/undo`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ turn: turn ?? null }) }).then((r) => j<InstanceView>(r)),
  fork: (id: string, turn?: number, title?: string) =>
    req(`/api/instances/${id}/fork`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ turn: turn ?? null, title: title ?? null }) }).then((r) => j<InstanceView>(r)),
  rename: (id: string, title: string) =>
    req(`/api/instances/${id}`, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ title }) }).then((r) => j<InstanceSummary>(r)),
  remove: (id: string) => req(`/api/instances/${id}`, { method: "DELETE" }).then((r) => j<{ ok: boolean }>(r)),
  exportUrl: (id: string) => `/api/instances/${id}/export`,
  importDoc: (doc: unknown) =>
    req("/api/instances/import", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(doc) }).then((r) => j<InstanceView>(r)),
  ledger: (id: string, turn?: number) => req(`/api/instances/${id}/ledger${turn != null ? `?turn=${turn}` : ""}`).then((r) => j<LedgerEntry[]>(r)),
  usage: (id: string) => req(`/api/instances/${id}/usage`).then((r) => j<InstanceUsage>(r)),
  /** The play page's death card: this save's death as it stands, or null. */
  death: (id: string) => req(`/api/instances/${id}/death`).then((r) => j<GraveCard | null>(r)),
  graveyard: (game?: string) => req(`/api/graveyard${game ? `?game=${encodeURIComponent(game)}` : ""}`).then((r) => j<Gallery>(r)),
  grave: (id: string) => req(`/api/graveyard/${id}`).then((r) => j<GraveCard>(r)),
  settings: () => req("/api/settings").then((r) => j<Settings>(r)),
  updateSettings: (patch: { guard?: Partial<Settings["guard"]>; progress?: Partial<Settings["progress"]> }) =>
    req("/api/settings", { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify(patch) }).then((r) => j<Settings>(r)),
  profiles: () => req("/api/profiles").then((r) => j<ProfileList>(r)),
  profile: (name: string) => req(`/api/profiles/${encodeURIComponent(name)}`).then((r) => j<ProfileCard>(r)),
  switchProfile: (name: string) =>
    req("/api/profiles/switch", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name }) }).then(async (r) => {
      if (!r.ok) {
        let msg = r.statusText;
        try {
          msg = (await r.json()).detail ?? msg;
        } catch {
          /* not json */
        }
        throw new Error(msg);
      }
      return (await r.json()) as ProfileList;
    }),
};

export type TurnEvent =
  | { event: "command"; data: { ok: boolean; text: string; mode: "engine" | "narrated" | null; label?: string; turn?: number } }
  | { event: "summary"; data: { status: "running" | "done" | "failed"; turns: number[]; chars?: number; error?: string } }
  | { event: "adjudication"; data: { kind: string; summary: string; time_minutes: number; clarify_question?: string | null } }
  | { event: "resolution"; data: { assessed: { label: string; stat: string; difficulty: string; target: string }[]; fired: { event_id: string; variant: string }[]; expired: { event_id: string }[]; elapsed: number; directives: string[] } }
  | { event: "bulletin"; data: { turn: number; text: string } }
  | { event: "rewrite"; data: { turn: number; hint: string; attempt: number; by?: string } }
  | { event: "retell"; data: { turn: number; attempt: number; rulings: { rule: string; what: string; fix: string }[]; hint: string } }
  | { event: "progress"; data: { stage: string; chars: number; expected: number; pct: number; slow: boolean } }
  | { event: "text"; data: { t: string } }
  | { event: "mechanic"; data: { turn: number; text: string; data: Record<string, any> } }
  | { event: "referee"; data: { delta: Record<string, any> | null; report?: { applied: string[]; rejected: unknown[] }; error?: string } }
  | { event: "done"; data: { turn: number; text: string; note?: string | null; model: string; usage: Record<string, number>; seconds: number; mechanics: Mechanics; ending?: string | null; ui: UISchema } }
  | { event: "error"; data: { message: string; step?: string } };

/** POST a typed turn and stream server-sent events back. */
export function streamTurn(id: string, text: string, signal?: AbortSignal): AsyncGenerator<TurnEvent> {
  return streamSse(`/api/instances/${id}/turn`, { text }, signal);
}

/** POST a ruling on the last turn (or none: just tell it again): same facts and dice, the referee reads it again. */
export function streamRewrite(id: string, hint: string, signal?: AbortSignal): AsyncGenerator<TurnEvent> {
  return streamSse(`/api/instances/${id}/rewrite`, { hint }, signal);
}

/** POST a clicked command; engine commands answer with command+done, narrated ones stream a full turn. */
export function streamCommand(id: string, command: string, args: Record<string, unknown>, signal?: AbortSignal): AsyncGenerator<TurnEvent> {
  return streamSse(`/api/instances/${id}/command`, { command, args }, signal);
}

async function* streamSse(url: string, body: unknown, signal?: AbortSignal): AsyncGenerator<TurnEvent> {
  const r = await req(url, {
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
