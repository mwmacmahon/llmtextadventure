import { useCallback, useEffect, useState } from "react";
import { api, devMode, type SaveCard, type Settings } from "../api";
import { prefs } from "../saves";
import { ProfilePicker } from "./ProfilePicker";

const ROLE_ORDER = ["narrator", "assistant", "referee", "summarizer"];

/** Settings, one page, opened from the bar everywhere: the game in play's difficulty (when opened from a game), the
 *  narrator guard, undo's dice, the story log, the roles and the profile picker, and dev mode. */
export function SettingsPage({ iid }: { iid: string | null }) {
  const [s, setS] = useState<Settings | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const reload = useCallback(() => {
    api.settings().then(setS).catch((e) => setErr(String(e)));
  }, []);
  useEffect(reload, [reload]);

  async function setMode(mode: string) {
    try {
      setS(await api.updateSettings({ guard: { mode } }));
    } catch (e) {
      setErr(String(e));
    }
  }

  const switched = useCallback(() => {
    reload();
    dispatchEvent(new Event("ta-settings"));       // the bar names the profile
  }, [reload]);

  if (!s) return <div className="lobby">{err ?? "loading settings…"}</div>;
  const rank = (n: string) => (ROLE_ORDER.includes(n) ? ROLE_ORDER.indexOf(n) : ROLE_ORDER.length);
  return (
    <div className="lobby settings-page">
      <h1>Settings</h1>
      {err && <div className="error">{err}</div>}
      {iid && <ThisGame iid={iid} difficulties={s.difficulties} />}

      <section className="settings">
        <h2>Narrator guard</h2>
        <div className="settings-row">
          <select value={s.guard.mode} onChange={(e) => setMode(e.target.value)} aria-label="Narrator guard">
            {Object.keys(s.modes).map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
          <span className="muted small">{s.modes[s.guard.mode]}</span>
        </div>
        {s.guard_from !== "settings" && (
          <div className="settings-row muted small">
            {s.guard_from === "profile"
              ? `Set by the profile ${s.profile}, on this server only; a change here stays on this server until the next switch.`
              : `Changed here, on this server only (the profile ${s.profile} says ${s.profile_guard}); the other servers keep ${s.shared_guard}.`}
          </div>
        )}
      </section>

      <section className="settings">
        <h2>Undo</h2>
        <label className="settings-row">
          <input
            type="checkbox"
            checked={!!s.dice?.keep_on_undo}
            onChange={async (e) => {
              try {
                setS(await api.updateSettings({ dice: { keep_on_undo: e.target.checked } }));
              } catch (err) {
                setErr(String(err));
              }
            }}
          />
          <span>Keep the dice on undo</span>
        </label>
        <div className="muted small">
          Off: a turn played again after an undo rolls new dice. On: it rolls the same dice it rolled before. For every game on
          this server; a rewrite always keeps its dice.
        </div>
      </section>

      <StoryLog />

      {s.dev_mode !== false && <DevMode needsPin={s.dev_pin} />}

      <section className="settings">
        <h2>Roles</h2>
        <div className="scroll">
          <table className="pcard-table">
            <thead>
              <tr><th>role</th><th>model</th></tr>
            </thead>
            <tbody>
              {Object.entries(s.roles).sort(([a], [b]) => rank(a) - rank(b)).map(([name, r]) => (
                <tr key={name}>
                  <td>{name}</td>
                  <td>{r.provider}:{r.model}{r.effort ? ` (effort ${r.effort})` : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <ProfilePicker onSwitched={switched} />
      </section>
    </div>
  );
}

/** The game this page was opened from: its difficulty, for the rest of it. */
function ThisGame({ iid, difficulties }: { iid: string; difficulties: Settings["difficulties"] }) {
  const [card, setCard] = useState<SaveCard | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    api.card(iid).then(setCard).catch((e) => setErr(String(e)));
  }, [iid]);

  async function change(d: string) {
    setErr(null);
    setSaved(false);
    try {
      const sum = await api.setDifficulty(iid, d);
      setCard(card ? { ...card, difficulty: sum.difficulty } : card);
      setSaved(true);
    } catch (e) {
      setErr(String(e));
    }
  }

  if (!card) return err ? <div className="error small">{err}</div> : null;
  return (
    <section className="settings this-game">
      <h2>This game: {card.title}</h2>
      <label className="settings-row">
        <strong>Difficulty</strong>
        <select value={card.difficulty} onChange={(e) => change(e.target.value)}>
          {difficulties.map((d) => (
            <option key={d.id} value={d.id}>{d.name}</option>
          ))}
        </select>
        <span className="muted small">{saved ? "Saved. It counts from the next roll." : "Easier or harder dice, for the rest of this game."}</span>
      </label>
      {err && <div className="error small">{err}</div>}
      <a className="link" href={`#/g/${iid}`}>← Back to the game</a>
    </section>
  );
}

/** The story log: undone turns struck through, or hidden. Kept in this browser. */
function StoryLog() {
  const [hide, setHide] = useState(prefs.hideUndone());
  return (
    <section className="settings">
      <h2>Story log</h2>
      <label className="settings-row">
        <input
          type="checkbox"
          checked={hide}
          onChange={(e) => {
            prefs.setHideUndone(e.target.checked);
            setHide(e.target.checked);
          }}
        />
        <span>Hide undone turns</span>
      </label>
      <div className="muted small">Undone turns stay in the log, struck through, unless this is on. Kept in this browser only.</div>
    </section>
  );
}

/** Dev mode: kept in this browser; asks for the server's pin when it has one. */
function DevMode({ needsPin }: { needsPin: boolean }) {
  const [on, setOn] = useState(devMode.on());
  const [asking, setAsking] = useState(false);
  const [pin, setPin] = useState("");
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    const sync = () => setOn(devMode.on());
    addEventListener("ta-dev", sync);
    return () => removeEventListener("ta-dev", sync);
  }, []);

  async function turnOn(p: string) {
    setErr(null);
    if (!(await api.checkDev(p))) {
      setErr(needsPin ? "That pin is not right." : "The server refused dev mode.");
      return;
    }
    devMode.set(true, p);
    setOn(true);
    setAsking(false);
    setPin("");
  }

  function toggle(want: boolean) {
    if (!want) {
      devMode.set(false);
      setOn(false);
      setAsking(false);
      return;
    }
    if (needsPin) setAsking(true);
    else turnOn("");
  }

  return (
    <section className="settings">
      <h2>Dev mode</h2>
      <label className="settings-row">
        <input type="checkbox" checked={on || asking} onChange={(e) => toggle(e.target.checked)} />
        <span>Dev mode: show hidden games and tools</span>
      </label>
      {asking && !on && (
        <form
          className="settings-row"
          onSubmit={(e) => {
            e.preventDefault();
            turnOn(pin);
          }}
        >
          <input type="password" inputMode="numeric" autoComplete="off" value={pin} onChange={(e) => setPin(e.target.value)} placeholder="pin" aria-label="Dev mode pin" />
          <button type="submit" disabled={!pin}>Turn on</button>
          <button type="button" className="link small" onClick={() => setAsking(false)}>cancel</button>
        </form>
      )}
      {err && <div className="error small">{err}</div>}
      <div className="muted small">Kept in this browser only.</div>
    </section>
  );
}
