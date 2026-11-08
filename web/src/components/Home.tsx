import { useEffect, useState } from "react";
import { api, type GameInfo } from "../api";

/** Home: one card per game, with its saved games counted; Open goes to the game's own page. */
export function Home() {
  const [games, setGames] = useState<GameInfo[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    // The dev server is up before the API on a fresh start; keep trying for a while instead of pinning a proxy error.
    let cancelled = false;
    const load = async (attempt: number) => {
      try {
        const g = await api.games();
        if (cancelled) return;
        setGames(g);
        setErr(null);
      } catch (e) {
        if (cancelled) return;
        if (attempt < 20) {
          setErr(`waiting for the server… (${String(e)})`);
          setTimeout(() => load(attempt + 1), 1000);
        } else {
          setErr(String(e));
        }
      }
    };
    load(0);
    const again = () => load(0);
    addEventListener("ta-dev", again);
    return () => {
      cancelled = true;
      removeEventListener("ta-dev", again);
    };
  }, []);

  return (
    <div className="lobby">
      <h1>Games</h1>
      {err && <div className="error">{err}</div>}
      <div className="games">
        {(games ?? []).map((g) => (
          <a key={g.name} className="game game-card" href={`#/games/${g.name}`}>
            <div className="card-title">
              {g.title}
              {g.hidden && <span className="dev-mark">dev</span>}
            </div>
            <p className="muted">{g.description}</p>
            <div className="game-card-foot">
              <span className="muted small">{g.saves === 0 ? "No saved games" : g.saves === 1 ? "1 saved game" : `${g.saves} saved games`}</span>
              <span className="button-like">Open</span>
            </div>
          </a>
        ))}
      </div>
    </div>
  );
}
