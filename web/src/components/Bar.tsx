import { useEffect, useRef, useState } from "react";
import { api, devMode } from "../api";

/** The bar on every page: the site's name (home), Games, Settings, Import; on the right, the server and profile this page
 *  talks to, so a save that lives on another server is explained. `settingsHref` opens Settings for the game in play. */
export function Bar({ settingsHref }: { settingsHref: string }) {
  const [profile, setProfile] = useState<string | null>(null);
  const [dev, setDev] = useState(devMode.on());
  const [err, setErr] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  // A tab open since an older web build offers a reload (the owner's undo showed nothing on a page from before the change).
  useEffect(() => {
    const mine = (document.querySelector('script[src*="/assets/index-"]') as HTMLScriptElement | null)?.src.split("/assets/")[1] ?? "";
    if (!mine) return;
    const check = () => fetch("/api/build").then((r) => r.json()).then((b: { build: string }) => setStale(!!b.build && b.build !== mine)).catch(() => {});
    check();
    const t = setInterval(check, 60_000);
    addEventListener("focus", check);
    return () => { clearInterval(t); removeEventListener("focus", check); };
  }, []);

  useEffect(() => {
    const load = () => api.settings().then((s) => {
      setProfile(s.profile);
      if (s.dev_mode === false && devMode.on()) devMode.set(false);    // B232: a server with no dev mode clears this browser's switch
    }).catch(() => setProfile(null));
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
      {stale && (
        <div className="bar-error small" role="status">
          A new version of the game is ready. <button className="link small" onClick={() => location.reload()}>Reload</button>
        </div>
      )}
      {err && (
        <div className="bar-error error small" role="alert">
          {err} <button className="link small" onClick={() => setErr(null)}>dismiss</button>
        </div>
      )}
    </nav>
  );
}
