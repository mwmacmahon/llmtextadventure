import { useEffect, useState } from "react";
import { api, type LedgerEntry, type TranscriptRow } from "../api";

/** GM debug drawer: exact bulletin, narrator request, usage, per turn. */
export function DebugDrawer({ instanceId, turn, transcript, open, onClose }: { instanceId: string; turn: number; transcript: TranscriptRow[]; open: boolean; onClose: () => void }) {
  const [sel, setSel] = useState(turn);
  const [ledger, setLedger] = useState<LedgerEntry[]>([]);

  useEffect(() => setSel(turn), [turn]);
  useEffect(() => {
    if (!open) return;
    api.ledger(instanceId, sel).then(setLedger).catch(() => setLedger([]));
  }, [open, instanceId, sel, turn]);

  if (!open) return null;
  const bulletin = transcript.find((r) => r.turn === sel && r.role === "bulletin");
  const call = ledger.find((l) => l.kind === "model_call");

  return (
    <aside className="drawer">
      <div className="drawer-head">
        <strong>GM debug</strong>
        <label>
          turn{" "}
          <select value={sel} onChange={(e) => setSel(Number(e.target.value))}>
            {Array.from({ length: turn }, (_, i) => i + 1).map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
        <button onClick={onClose}>close</button>
      </div>
      {call && (
        <div className="drawer-meta">
          <span>{call.payload.provider}/{call.payload.model}</span>
          <span>{call.payload.seconds}s</span>
          <span>in {call.payload.usage?.input_tokens} · cached {call.payload.usage?.cache_read_input_tokens} · out {call.payload.usage?.output_tokens}</span>
          {call.payload.note && <span className="warn">{call.payload.note}</span>}
          {call.payload.error && <span className="warn">{call.payload.error}</span>}
        </div>
      )}
      <h4>Bulletin (injected before the player's message)</h4>
      <pre>{bulletin?.text ?? "—"}</pre>
      <h4>Messages sent to the narrator</h4>
      {call?.payload.request?.messages?.map((m: { role: string; content: string }, i: number) => (
        <details key={i} open={i === call.payload.request.messages.length - 1}>
          <summary>
            {m.role} · {m.content.length} chars
          </summary>
          <pre>{m.content}</pre>
        </details>
      ))}
      <h4>Ledger</h4>
      <pre>{JSON.stringify(ledger.map(({ payload, ...rest }) => ({ ...rest, kind: rest.kind, keys: Object.keys(payload) })), null, 1)}</pre>
    </aside>
  );
}
