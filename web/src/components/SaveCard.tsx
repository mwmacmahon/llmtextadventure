import { useEffect, useState } from "react";
import { api, type InstanceUsage, type SaveCard as Card } from "../api";
import { ChipView, Panels } from "./Panels";
import { ago, originMark } from "../saves";

/** A save's card, opened in place from its line (a full-width sheet at phone width): the save line as chips, the last
 *  telling's opening, the state as the player sees it (the game's panels, read-only), the properties, Continue. */
export function SaveCard({ id, onClose, onChanged, onGone }: { id: string; onClose: () => void; onChanged: () => void; onGone: () => void }) {
  const [card, setCard] = useState<Card | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = () => api.card(id).then(setCard).catch((e) => setErr(String(e)));
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function act(fn: () => Promise<unknown>) {
    setErr(null);
    try {
      await fn();
      await load();
      onChanged();
    } catch (e) {
      setErr(String(e));
    }
  }

  return (
    <div className="save-card" role="dialog" aria-label={card ? card.title : "saved game"}>
      <div className="save-card-head">
        <strong>{card?.title ?? "…"}</strong>
        <span className="spacer" />
        <button className="link" onClick={onClose} aria-label="Close">close</button>
      </div>
      {err && <div className="error small">{err}</div>}
      {!card ? (
        <div className="muted small">loading…</div>
      ) : (
        <>
          <div className="strip save-chips">
            {card.save_line.map((c, i) => (
              <ChipView key={i} c={c} />
            ))}
            <ChipView c={{ label: "turn", value: String(card.turn) }} />
            <ChipView c={{ label: "last played", value: ago(card.updated) }} />
            {originMark(card) && <ChipView c={{ label: "", value: originMark(card)! }} />}
          </div>
          {card.ending && <div className="ending">The End. {card.ending}</div>}
          {card.last && (
            <div className="last-telling">
              <div className="muted small">
                The last telling: turn {card.last.turn}
                {card.last.clock ? `, ${card.last.clock}` : ""}
              </div>
              <p>{card.last.text}</p>
            </div>
          )}
          <div className="continue-row">
            <a className="button-like primary" href={`#/g/${card.id}`}>Continue</a>
          </div>
          <details className="card-props">
            <summary>Properties: rename, branch, export, cost, delete</summary>
            <Properties card={card} act={act} onGone={onGone} />
          </details>
          <div className="card-state">
            <h3 className="muted small">Where things stand</h3>
            <Panels panels={card.ui.panels} readOnly />
          </div>
        </>
      )}
    </div>
  );
}

function Properties({ card, act, onGone }: { card: Card; act: (fn: () => Promise<unknown>) => Promise<void>; onGone: () => void }) {
  const [usage, setUsage] = useState<InstanceUsage | null>(null);
  const [confirm, setConfirm] = useState("");
  const [deleting, setDeleting] = useState(false);
  useEffect(() => {
    api.usage(card.id).then(setUsage).catch(() => setUsage(null));
  }, [card.id, card.turn]);
  const fmt = (n: number) => n.toLocaleString();
  return (
    <div className="props">
      <div className="muted small">
        {card.game} v{card.game_version} · id {card.id} · created {new Date(card.created).toLocaleString()} · difficulty {card.difficulty}
        {card.origin.forked_from && ` · branched from ${card.origin.forked_from} at turn ${card.origin.at_turn}`}
        {card.origin.imported && ` · imported from ${card.origin.original_id ?? "?"}`}
      </div>
      <div className="row-actions">
        <button
          className="link small"
          onClick={() => {
            const t = prompt("Rename game", card.title);
            if (t != null && t.trim()) act(() => api.rename(card.id, t));
          }}
        >
          rename
        </button>
        <button className="link small" onClick={() => act(() => api.fork(card.id))} title="Copy this game as a new branch from its latest turn">
          branch
        </button>
        <a className="link small" href={api.exportUrl(card.id)} download title="Download this game as a file">
          export
        </a>
        <button className="link small danger" onClick={() => setDeleting(!deleting)}>
          delete…
        </button>
      </div>
      {deleting && (
        <div className="delete-confirm">
          <label className="setup-field">
            <span className="small">To delete it for good, type its title: <b>{card.title}</b></span>
            <input type="text" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="off" />
          </label>
          <button className="danger-btn" disabled={confirm.trim() !== card.title.trim()} onClick={() => act(() => api.remove(card.id)).then(onGone)}>
            Delete this game
          </button>
        </div>
      )}
      {usage && (
        <div className="scroll">
          <table className="usage">
            <thead>
              <tr>
                <th>role</th><th>model</th><th>calls</th><th>input</th><th>cache read</th><th>cache write</th><th>output</th><th>cost</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(usage.roles).map(([role, r]) => (
                <tr key={role}>
                  <td>{role}</td>
                  <td className="muted">{r.model ?? "—"}</td>
                  <td>{r.calls}</td>
                  <td>{fmt(r.usage.input_tokens)}</td>
                  <td>{fmt(r.usage.cache_read_input_tokens)}</td>
                  <td>{fmt(r.usage.cache_creation_input_tokens)}</td>
                  <td>{fmt(r.usage.output_tokens)}</td>
                  <td>{r.priced ? `$${r.usd.toFixed(3)}` : "—"}</td>
                </tr>
              ))}
              <tr>
                <td colSpan={7}>
                  <strong>total</strong> · {usage.calls} calls over {usage.turn} turns
                </td>
                <td>
                  <strong>{usage.priced ? `$${usage.usd.toFixed(2)}` : `$${usage.usd.toFixed(2)}+`}</strong>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
