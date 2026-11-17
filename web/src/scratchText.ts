// The scratch pad's export/import format (D326): one text blob <-> a system text and a list of messages.
//
//   ### system
//   Be brief.
//
//   ### user
//   Hello.
//
//   ### assistant
//   Hi.
//
// A header is a line of its own: "###", then system, user or assistant ("model" reads as assistant). Import also takes a
// JSON list of {role, content} or {messages: [...]} (the shape every chat API logs). A blob with no header and no JSON is
// plain text: the caller decides where it goes.

export type Role = "user" | "assistant";
export type Turn = { role: Role; content: string };
export type Exchange = { system: string; messages: Turn[] };

const HEADER = /^###[ \t]*(system|user|assistant|model)[ \t]*$/i;

export function formatExchange(x: Exchange): string {
  const parts: string[] = [];
  if (x.system.trim()) parts.push(`### system\n${x.system}`);
  for (const m of x.messages) parts.push(`### ${m.role}\n${m.content}`);
  return parts.join("\n\n") + "\n";
}

/** The blob as an exchange, or null when it is plain text (no header line, not a JSON message list). */
export function parseExchange(blob: string): Exchange | null {
  return fromJson(blob) ?? fromHeaders(blob);
}

function fromHeaders(blob: string): Exchange | null {
  const lines = blob.replace(/\r\n?/g, "\n").split("\n");
  if (!lines.some((l) => HEADER.test(l))) return null;
  const x: Exchange = { system: "", messages: [] };
  let role: string | null = null;
  let buf: string[] = [];
  const flush = () => {
    if (role === null) return;
    const content = buf.join("\n").replace(/^\n+|\n+$/g, "");      // the blank lines around a section, not its own spaces
    if (role === "system") x.system = x.system ? `${x.system}\n\n${content}` : content;
    else x.messages.push({ role: role === "user" ? "user" : "assistant", content });
  };
  for (const line of lines) {
    const m = line.match(HEADER);
    if (m) {
      flush();
      role = m[1].toLowerCase();
      buf = [];
    } else if (role !== null) buf.push(line);
  }
  flush();
  return x;
}

function fromJson(blob: string): Exchange | null {
  let data: unknown;
  try {
    data = JSON.parse(blob);
  } catch {
    return null;
  }
  const list = Array.isArray(data) ? data : (data as { messages?: unknown })?.messages;
  if (!Array.isArray(list) || !list.length) return null;
  const x: Exchange = { system: (data as { system?: unknown })?.system as string ?? "", messages: [] };
  if (typeof x.system !== "string") x.system = "";
  for (const m of list) {
    const role = String((m as { role?: unknown })?.role ?? "").toLowerCase();
    const c = (m as { content?: unknown })?.content;
    const content = typeof c === "string" ? c : Array.isArray(c) ? c.map((p) => (typeof p === "string" ? p : p?.text ?? "")).join("") : "";
    if (role === "system") x.system = x.system ? `${x.system}\n\n${content}` : content;
    else if (role === "user" || role === "assistant" || role === "model") x.messages.push({ role: role === "user" ? "user" : "assistant", content });
    else return null;
  }
  return x;
}
