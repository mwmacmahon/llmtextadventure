import { useCallback, useEffect, useState } from "react";
import { api, type ProfileCard, type ProfileList, type TurnCost } from "../api";

const ROLE_ORDER = ["narrator", "assistant", "referee", "summarizer"];

function usd(x: number): string {
  return x < 0.01 ? `$${x.toFixed(4)}` : `$${x.toFixed(3)}`;
}

function Cost({ cost }: { cost: TurnCost }) {
  const prices = Object.entries(cost.prices);
  return (
    <div className="pcard-section">
      <strong>Cost of a turn</strong>{" "}
      {cost.usd_per_turn != null ? (
        <span>
          {usd(cost.usd_per_turn)} a turn on average, over {cost.turns} {cost.turns === 1 ? "turn" : "turns"} played on this profile
          {cost.priced ? "" : " (some calls had no price)"}
        </span>
      ) : (
        <span className="muted">no turns yet</span>
      )}
      {prices.length > 0 && (
        <div className="muted small">
          {prices.map(([m, p]) => (
            <span key={m} className="pcard-price">
              {m}: ${p.input} in, ${p.output} out, ${p.cache_read} cache read, ${p.cache_write} cache write, per million tokens
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function Card({ card }: { card: ProfileCard }) {
  const rank = (n: string) => (ROLE_ORDER.includes(n) ? ROLE_ORDER.indexOf(n) : ROLE_ORDER.length);
  const roles = Object.entries(card.roles).sort(([a], [b]) => rank(a) - rank(b));
  const offsets = Object.entries(card.dials.target_offset);
  return (
    <div className="pcard">
      <div className="pcard-head">
        <strong>{card.name}</strong>
        <span className="muted small">
          {card.local ? `on the GPU box: ${card.model}` : "hosted"} · base {card.base}
          {card.active ? " · active on this server" : ""}
        </span>
        {card.note && <div className="muted small">{card.note}</div>}
      </div>

      <div className="scroll">
        <table className="pcard-table">
          <thead>
            <tr><th>role</th><th>model</th><th>runs on</th><th>sampler</th><th>thinking</th></tr>
          </thead>
          <tbody>
            {roles.map(([name, r]) => (
              <tr key={name}>
                <td>{name}</td>
                <td>{r.provider}:{r.model}{r.effort ? ` (effort ${r.effort})` : ""}</td>
                <td>{r.where}</td>
                <td className="small">
                  {Object.keys(r.sampler).length ? Object.entries(r.sampler).map(([k, v]) => `${k} ${v}`).join(", ") : <span className="muted">the provider's defaults</span>}
                  <span className="muted"> · up to {r.max_tokens} tokens</span>
                </td>
                <td className="small">{r.thinking}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="pcard-section">
        <strong>Dials</strong>
        <span className={card.dials.stakes.value === "live" ? "" : "error"} title={card.dials.stakes.value === "live" ? undefined : "The assistant's futures are not driving the checks: the stakes are meant to be live on every game with an assistant (B94)."}>
          stakes: {String(card.dials.stakes.value)} <span className="muted small">({card.dials.stakes.from})</span>
        </span>
        <span>checks: {String(card.dials.checks.value)} <span className="muted small">({card.dials.checks.from})</span></span>
        <span>guard: {String(card.dials.guard.value)} <span className="muted small">({card.dials.guard.from})</span></span>
        <span>
          check offset:{" "}
          {offsets.map(([g, d], i) => (
            <span key={g}>
              {i > 0 && ", "}
              {g} {Number(d.value) > 0 ? `+${d.value}` : String(d.value)} <span className="muted small">({d.from})</span>
            </span>
          ))}
        </span>
      </div>

      <div className="scroll">
        <table className="pcard-table">
          <thead>
            <tr><th>context module</th><th>level</th><th>what it does at that level</th></tr>
          </thead>
          <tbody>
            {card.modules.map((m) => (
              <tr key={m.id} className={m.built ? "" : "muted"} title={`cuts: ${m.cuts}`}>
                <td>{m.label}</td>
                <td>{m.level}</td>
                <td className="small">{m.built ? m.what : "not built yet"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {card.box && (
        <div className="pcard-section">
          <strong>The box</strong>
          <span className={card.box.loading ? "loading-note" : ""}>{card.box.loading ? "loading this profile…" : card.box.state}</span>
          {card.box.configured && (
            <span className="muted small">
              loaded: {card.box.active ?? "nothing"}
              {card.box.slot_ctx ? ` · ${card.box.slots ?? "?"} slots of ${card.box.slot_ctx} tokens` : ""}
              {card.box.requested_ctx != null ? ` · context asked for: ${card.box.requested_ctx}` : ""}
            </span>
          )}
        </div>
      )}

      {card.cost && !card.local && <Cost cost={card.cost} />}
    </div>
  );
}

/** The profile picker in the settings menu: the profiles, the active one, the selected one's card, and the switch. */
export function ProfilePicker({ onSwitched }: { onSwitched: () => void }) {
  const [list, setList] = useState<ProfileList | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [card, setCard] = useState<ProfileCard | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [switching, setSwitching] = useState(false);

  const loadList = useCallback(async () => {
    const l = await api.profiles();
    setList(l);
    setSelected((s) => s ?? l.active ?? l.profiles[0]?.name ?? null);
    return l;
  }, []);

  useEffect(() => {
    loadList().catch((e) => setErr(String(e)));
  }, [loadList]);

  useEffect(() => {
    if (!selected) return;
    let live = true;
    setCard(null);
    api.profile(selected).then((c) => live && setCard(c)).catch((e) => live && setErr(String(e)));
    return () => {
      live = false;
    };
  }, [selected]);

  // While the box loads a profile, ask again every few seconds until it reports it loaded.
  const loadingName = list?.loading?.name ?? null;
  useEffect(() => {
    if (!loadingName) return;
    const t = setInterval(async () => {
      try {
        const c = await api.profile(loadingName);
        if (c.name === selected) setCard(c);
        if (!c.box?.loading) {
          await loadList();
          onSwitched();
        }
      } catch (e) {
        setErr(String(e));
      }
    }, 3000);
    return () => clearInterval(t);
  }, [loadingName, selected, loadList, onSwitched]);

  async function doSwitch() {
    if (!selected) return;
    setSwitching(true);
    setErr(null);
    try {
      setList(await api.switchProfile(selected));
      setCard(await api.profile(selected));
      onSwitched();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSwitching(false);
    }
  }

  if (!list) return <div className="muted small">{err ?? "loading profiles…"}</div>;
  const isActive = selected != null && selected === list.active;
  return (
    <div className="picker">
      <div className="settings-row">
        <strong>Profile</strong>
        <span>
          playing on <b>{list.label}</b>
          {list.loading ? <span className="loading-note"> · loading {list.loading.name} on the box…</span> : null}
        </span>
      </div>
      <div className="settings-row">
        <select value={selected ?? ""} onChange={(e) => setSelected(e.target.value)} aria-label="Profile to look at">
          {list.profiles.map((p) => (
            <option key={p.name} value={p.name}>
              {p.name} {p.local ? "(local)" : "(hosted)"}
              {p.name === list.active ? " (active)" : ""}
            </option>
          ))}
        </select>
        <button onClick={doSwitch} disabled={!selected || switching || (isActive && !list.loading) || list.busy}
                title={list.busy ? "A turn is being told; switch when it has finished" : "Play on this profile on this server from the next turn"}>
          {switching ? "switching…" : isActive ? "active" : "Switch"}
        </button>
        {list.busy && <span className="muted small">a turn is being told; switching waits for it</span>}
      </div>
      {list.errors.length > 0 && (
        <div className="error small">{list.errors.map((e) => `${e.name}: ${e.error}`).join("; ")}</div>
      )}
      {err && <div className="error small">{err}</div>}
      {card ? <Card card={card} /> : selected ? <div className="muted small">loading the card…</div> : null}
    </div>
  );
}
