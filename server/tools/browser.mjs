#!/usr/bin/env node
// A small browser driver for play-testing the web client (FN192; the owner, 11-19: "Can you have opus agents try playing
// through the web ui or something to test all the ui stuff?"). It drives the Chrome already on this machine over the
// DevTools protocol with Node's own WebSocket: nothing to install. One command a call; the browser stays up between calls.
//
//   browser.mjs start [--port 9333] [--size 1280x900] [--phone]   launch headless Chrome (a profile of its own in the temp dir)
//   browser.mjs goto <url>                         open a page and wait for it to load
//   browser.mjs text [selector]                    the visible text of the page (or of one element), trimmed to 6000 chars
//   browser.mjs buttons                            every visible button, link, select and input: its text, kind and state
//   browser.mjs click "<text>" [--nth N] [--in selector]    click the visible control whose text contains this (exact wins)
//   browser.mjs clickxy <x> <y>                    click at a point (the map)
//   browser.mjs select "<label or current text>" "<option text>"   choose in a <select>
//   browser.mjs fill "<selector or placeholder/label text>" "<text>"   put text in an input or textarea (replaces it)
//   browser.mjs press <Enter|Escape|Tab>
//   browser.mjs wait "<text>" [seconds]            until the page shows this text (default 120 s); `wait --gone "<text>"`
//   browser.mjs shot <file.png>                    a screenshot of the window
//   browser.mjs eval "<js expression>"             run JavaScript in the page, print the JSON result
//   browser.mjs errors                             console errors and failed requests seen since `goto` (kept in the page)
//   browser.mjs stop
//
// Port: --port or TA_BROWSER_PORT (default 9333), so several testers can each have a browser.
import { spawn } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const argv = process.argv.slice(2);
const flag = (name, dflt = null) => { const i = argv.indexOf(`--${name}`); if (i < 0) return dflt; const v = argv[i + 1]; argv.splice(i, 2); return v; };
const has = (name) => { const i = argv.indexOf(`--${name}`); if (i < 0) return false; argv.splice(i, 1); return true; };
const PORT = Number(flag("port", process.env.TA_BROWSER_PORT || 9333));
const CHROME = process.env.TA_CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function target() {
  const list = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json();
  const page = list.find((t) => t.type === "page");
  if (!page) throw new Error("no page open in the browser");
  return page.webSocketDebuggerUrl;
}

async function cdp() {
  const ws = new WebSocket(await target());
  await new Promise((ok, bad) => { ws.onopen = ok; ws.onerror = () => bad(new Error("cannot reach the browser; run `browser.mjs start`")); });
  let id = 0;
  const waiting = new Map();
  ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && waiting.has(d.id)) { const [ok, bad] = waiting.get(d.id); waiting.delete(d.id); d.error ? bad(new Error(d.error.message)) : ok(d.result); } };
  const send = (method, params = {}) => new Promise((ok, bad) => { waiting.set(++id, [ok, bad]); ws.send(JSON.stringify({ id, method, params })); });
  const js = async (expression) => {
    const r = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
    return r.result.value;
  };
  return { send, js, close: () => ws.close() };
}

// in-page helpers: what a person could see and press
const PAGE = `(() => {
  const vis = (e) => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e); return r.width > 1 && r.height > 1 && s.visibility !== "hidden" && s.display !== "none" && r.bottom > 0 && r.top < innerHeight + 4000; };
  const txt = (e) => (e.tagName === "INPUT" || e.tagName === "TEXTAREA" ? (e.placeholder || e.value || "") : e.tagName === "SELECT" ? (e.selectedOptions[0]?.textContent || "") : (e.innerText || e.getAttribute("aria-label") || e.title || "")).replace(/\\s+/g, " ").trim();
  const controls = (root) => [...(root || document).querySelectorAll("button, a[href], select, input, textarea, [role=button], summary")].filter(vis);
  // covered: in the window with something else drawn over its middle (a sheet over the page); off-screen is not covered
  const top = (e) => { const r = e.getBoundingClientRect(); const x = r.left + r.width / 2, y = r.top + r.height / 2;
    if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) return true;
    const at = document.elementFromPoint(x, y); return !!at && (at === e || e.contains(at) || at.contains(e)); };
  return { vis, txt, controls, top };
})()`;

async function main() {
  const cmd = argv.shift();
  if (cmd === "start") {
    const size = (flag("size", has("phone") ? "400x860" : "1280x900")).replace("x", ",");
    const dir = mkdtempSync(join(tmpdir(), "ta-browser-"));
    const child = spawn(CHROME, ["--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${dir}`, `--window-size=${size}`,
      "--hide-scrollbars", "--no-first-run", "--no-default-browser-check", "--disable-gpu", "about:blank"], { detached: true, stdio: "ignore" });
    child.unref();
    for (let i = 0; i < 40; i++) { await sleep(250); try { await target(); console.log(`browser up on port ${PORT} (${size.replace(",", "x")})`); return; } catch { /* not yet */ } }
    throw new Error("the browser did not start");
  }
  if (cmd === "stop") {
    try { const v = await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json(); const ws = new WebSocket(v.webSocketDebuggerUrl);
      await new Promise((ok) => { ws.onopen = () => { ws.send(JSON.stringify({ id: 1, method: "Browser.close" })); setTimeout(ok, 300); }; ws.onerror = ok; }); } catch { /* already gone */ }
    console.log("stopped");
    return;
  }
  const c = await cdp();
  try {
    if (cmd === "goto") {
      await c.send("Page.enable");
      await c.send("Page.navigate", { url: argv[0] });
      for (let i = 0; i < 80; i++) { await sleep(250); if (await c.js("document.readyState") === "complete") break; }
      await sleep(600);
      // keep what goes wrong where a later call can read it
      await c.js(`(() => { if (window.__ta) return; window.__ta = { errors: [] };
        const push = (s) => window.__ta.errors.push(String(s).slice(0, 400));
        addEventListener("error", (e) => push("error: " + e.message)); addEventListener("unhandledrejection", (e) => push("rejection: " + (e.reason?.message || e.reason)));
        const ce = console.error; console.error = (...a) => { push("console.error: " + a.map(String).join(" ")); ce(...a); };
        const f = window.fetch; window.fetch = (...a) => f(...a).then((r) => { if (!r.ok) push("http " + r.status + " " + (a[0]?.url || a[0])); return r; }, (e) => { push("fetch failed: " + (a[0]?.url || a[0]) + " " + e); throw e; });
      })()`);
      console.log(await c.js("document.title + ' | ' + location.href"));
    } else if (cmd === "text") {
      const sel = argv[0];
      const out = await c.js(`(() => { const e = ${sel ? `document.querySelector(${JSON.stringify(sel)})` : "document.body"}; return e ? e.innerText : "(nothing matches)"; })()`);
      console.log(String(out).replace(/\n{3,}/g, "\n\n").slice(0, 6000));
    } else if (cmd === "buttons") {
      const out = await c.js(`(() => { const h = ${PAGE}; return h.controls().map((e) => (e.tagName.toLowerCase() + (e.disabled ? " (off)" : "") + (h.top(e) ? "" : " (covered)") + ": " + h.txt(e).slice(0, 70))); })()`);
      console.log(out.join("\n"));
    } else if (cmd === "click") {
      const nth = Number(flag("nth", 1)), within = flag("in");
      const want = argv[0];
      const pt = await c.js(`(() => { const h = ${PAGE}; const want = ${JSON.stringify(want)}.toLowerCase();
        const root = ${within ? `document.querySelector(${JSON.stringify(within)})` : "document"};
        if (!root) return { err: "nothing matches --in" };
        let all = h.controls(root).filter((e) => !e.disabled && h.txt(e).toLowerCase().includes(want));
        const exact = all.filter((e) => h.txt(e).toLowerCase() === want); if (exact.length) all = exact;
        const upper = all.filter(h.top); if (upper.length) all = upper;
        const e = all[${nth - 1}]; if (!e) return { err: "no visible control with that text (" + all.length + " found)" };
        e.scrollIntoView({ block: "center" }); const r = e.getBoundingClientRect();
        return { x: r.left + r.width / 2, y: r.top + r.height / 2, text: h.txt(e).slice(0, 60), n: all.length }; })()`);
      if (pt.err) throw new Error(pt.err);
      for (const type of ["mousePressed", "mouseReleased"]) await c.send("Input.dispatchMouseEvent", { type, x: pt.x, y: pt.y, button: "left", clickCount: 1 });
      await sleep(350);
      console.log(`clicked "${pt.text}"` + (pt.n > 1 ? ` (${pt.n} matched; --nth picks another)` : ""));
    } else if (cmd === "clickxy") {
      const [x, y] = argv.map(Number);
      await c.send("Input.dispatchMouseEvent", { type: "mouseMoved", x, y });
      for (const type of ["mousePressed", "mouseReleased"]) await c.send("Input.dispatchMouseEvent", { type, x, y, button: "left", clickCount: 1 });
      await sleep(350);
      console.log(`clicked at ${x}, ${y}`);
    } else if (cmd === "select") {
      const out = await c.js(`(() => { const h = ${PAGE}; const want = ${JSON.stringify(argv[0])}.toLowerCase(), opt = ${JSON.stringify(argv[1])}.toLowerCase();
        const sels = [...document.querySelectorAll("select")].filter(h.vis);
        const lab = (s) => ((s.labels && s.labels[0]?.innerText) || s.previousElementSibling?.innerText || s.parentElement?.innerText || "").toLowerCase();
        const s = sels.find((x) => lab(x).includes(want) || h.txt(x).toLowerCase().includes(want)); if (!s) return "no select like that (" + sels.length + " on the page)";
        const o = [...s.options].find((x) => x.textContent.toLowerCase().includes(opt)); if (!o) return "no such option; it has: " + [...s.options].map((x) => x.textContent).join(" | ");
        const set = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set; set.call(s, o.value); s.dispatchEvent(new Event("change", { bubbles: true })); return "selected " + o.textContent; })()`);
      console.log(out);
    } else if (cmd === "fill") {
      const ok = await c.js(`(() => { const h = ${PAGE}; const want = ${JSON.stringify(argv[0])};
        let e = null; try { e = document.querySelector(want); } catch { /* not a selector */ }
        if (!e) { const all = [...document.querySelectorAll("input, textarea")].filter(h.vis); const w = want.toLowerCase();
          e = all.find((x) => (x.placeholder || "").toLowerCase().includes(w) || ((x.labels && x.labels[0]?.innerText) || x.closest("label, .setup-field")?.innerText || "").toLowerCase().includes(w)); }
        if (!e) return false; e.scrollIntoView({ block: "center" }); e.focus(); e.select && e.select(); return true; })()`);
      if (!ok) throw new Error("no input like that");
      await c.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Backspace", code: "Backspace", windowsVirtualKeyCode: 8 });
      await c.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Backspace", code: "Backspace", windowsVirtualKeyCode: 8 });
      await c.send("Input.insertText", { text: argv[1] });
      await sleep(150);
      console.log("filled");
    } else if (cmd === "press") {
      const key = argv[0], code = { Enter: 13, Escape: 27, Tab: 9 }[key] || 0;
      await c.send("Input.dispatchKeyEvent", { type: "keyDown", key, code: key, windowsVirtualKeyCode: code, text: key === "Enter" ? "\r" : undefined });
      await c.send("Input.dispatchKeyEvent", { type: "keyUp", key, code: key, windowsVirtualKeyCode: code });
      await sleep(300);
      console.log(`pressed ${key}`);
    } else if (cmd === "wait") {
      const gone = has("gone");
      const want = argv[0], secs = Number(argv[1] || 120);
      const t0 = Date.now();
      for (;;) {
        const shown = await c.js(`document.body.innerText.includes(${JSON.stringify(want)})`);
        if (shown !== gone) { console.log(`${gone ? "gone" : "shown"} after ${((Date.now() - t0) / 1000).toFixed(1)} s`); break; }
        if (Date.now() - t0 > secs * 1000) throw new Error(`still ${gone ? "there" : "not there"} after ${secs} s`);
        await sleep(500);
      }
    } else if (cmd === "shot") {
      const r = await c.send("Page.captureScreenshot", { format: "png" });
      writeFileSync(argv[0], Buffer.from(r.data, "base64"));
      console.log(`wrote ${argv[0]}`);
    } else if (cmd === "eval") {
      console.log(JSON.stringify(await c.js(argv[0]), null, 1));
    } else if (cmd === "errors") {
      const e = await c.js("(window.__ta && window.__ta.errors) || []");
      console.log(e.length ? e.join("\n") : "none");
    } else {
      throw new Error("commands: start goto text buttons click clickxy select fill press wait shot eval errors stop");
    }
  } finally {
    c.close();
  }
}

main().then(() => process.exit(0), (e) => { console.error(String(e.message || e)); process.exit(1); });
