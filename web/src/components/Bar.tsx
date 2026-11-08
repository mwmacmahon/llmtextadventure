import { useEffect, useRef, useState } from "react";
import { api, devMode } from "../api";

/** The bar on every page: the site's name (home), Games, Settings, Import; on the right, the server and profile this page
 *  talks to, so a save that lives on another server is explained. `settingsHref` opens Settings for the game in play. */
export function Bar({ settingsHref }: { settingsHref: string }) {
  const [profile, setProfile] = useState<string | null>(null);
  const [dev, setDev] = useState(devMode.on());
  const [err, setErr] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const load = () => api.settings().then((s) => setProfile(s.profile)).catch(() => setProfile(null));
    load();
    const onDev = () => setDev(devMode.on());
    addEventListener("ta-settings", load);
    addEventListener("ta-dev", onDev);
    return () => {
      removeEventListener("ta-settings", load);
      removeEventListener("ta-dev", onDev);
    };
  }, []);

  async function importFile(f: File) {
    setErr(null);
    try {
      const v = await api.importDoc(JSON.parse(await f.text()));
      location.hash = `#/g/${v.id}`;
    } catch (e) {
      setErr(`Could not import that file: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <nav className="bar">
      <a className="bar-name" href="#/">Text Adventure</a>
      <a href="#/">Games</a>
      <a href="#/graveyard">Graveyard</a>
      <a href={settingsHref}>Settings</a>
      <button className="link" onClick={() => fileRef.current?.click()} title="Open a saved game from a file you exported">
        Import
      </button>
      <input ref={fileRef} type="file" accept="application/json,.json" hidden onChange={(e) => e.target.files?.[0] && importFile(e.target.files[0])} />
      <span className="spacer" />
      <span className="bar-where muted small" title="The server and profile this page plays on. Saves live on the server that made them.">
        {dev && <span className="dev-mark">dev</span>}
        {location.host}
        {profile ? ` · ${profile}` : ""}
      </span>
      {err && (
        <div className="bar-error error small" role="alert">
          {err} <button className="link small" onClick={() => setErr(null)}>dismiss</button>
        </div>
      )}
    </nav>
  );
}
