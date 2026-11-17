# The llama.cpp sleep patch (D327)

**Every time llama.cpp is upgraded on the GPU box (gumbo), this patch must be applied again**, or the game's
**Unload model** button stops working. Nothing else in the game depends on it: turns, profiles and the idle sleep all work
without it. This page is the whole procedure; read it before any llama.cpp upgrade.

Applied to: **llama.cpp b12032** at `~/llms/llama.cpp-b12032` on gumbo, 2026-11-17 (the build the service runs:
`LLAMA_BIN` in `~/.config/systemd/user/textadventure-llm.service`).

## Why it exists

The game's llama-server unloads the model by itself after 10 idle minutes (`--sleep-idle-seconds 600` in
`llama-game.sh`, the `IDLE` knob): it drops the model from VRAM, keeps the port open, and the next request loads it
again. The owner wanted to free the GPU now, without waiting the 10 minutes (11-17: "we really need an unload model
button so we don't always have to wait 10 min").

llama.cpp has no way to start that sleep on demand. Checked on b12032: the sleep is entered only from the task queue's
idle check (`server_queue::start_loop`, `tools/server/server-queue.cpp`), against a timer fixed at start; there is no
route for it, and `POST /props` changes nothing. Restarting llama-server would reload the model at once. (llama.cpp's
router mode has `/models/unload`, but the game does not run the router.)

Alternatives weighed (the owner chose the patch, 11-17):
- **Park through the helper** (no llama.cpp change): the helper stops llama-server and holds it stopped; the game wakes
  it before its next call and waits out the load. More moving parts in the game's provider, and a call that arrives
  while it is parked fails. Not taken.
- **A shorter idle timer**: the timer is the same for every gap, so the model would also unload between turns. Not taken.

## What the patch does

It adds one route, **`POST /sleep`**, that starts the very same sleep the idle timer starts, at the queue's next idle
moment (within a second when idle):
- The model leaves VRAM (measured: the 5090 from 31.8 GB to 2.7 GB; the rest is the desktop). `GET /props` reports
  `is_sleeping: true` and still names the model, its slots and context.
- The next request of any kind that needs the model wakes it, exactly as after the idle sleep (measured: 8 seconds for
  Gemma 4 31B). The roles' prompts are paid again once, as after any sleep.
- **It never interrupts work, and it is not queued behind it.** Work that resets the idle timer clears the request (the
  queue's own `post()` path). Measured 2026-11-17: `/sleep` sent 4 seconds into a 600-token generation answered
  `was_sleeping: false`, the generation ran to all 600 tokens, and the model was still loaded after it. So a sleep asked
  for during work is simply dropped: ask again once the box is idle. The game refuses to send it while any slot is busy
  (below), so from the button this only happens in a race of a second or so.
- Asleep already: answers `{"success": true, "was_sleeping": true}` and does nothing.
- Idle sleep off (`--sleep-idle-seconds` negative): answers 501, "idle sleep is off".
- Answer when it starts: `{"success": true, "was_sleeping": false}`.

The change, 40 added lines in five files of `tools/server/` (every one marked `TEXTADVENTURE-SLEEP-PATCH`):

| File | Change |
|---|---|
| `server-queue.h` | a flag `req_sleep_now`; a method `request_sleep()` |
| `server-queue.cpp` | `request_sleep()` sets the flag and wakes the queue; the idle check (`should_sleep`) is true while it is set; entering the sleep clears it; the two `post()` paths that reset the idle timer clear it too (work came first); the queue's wait also wakes on the flag |
| `server-context.h` | a handler `post_sleep` |
| `server-context.cpp` | the handler: built with `create_response(true)` (bypasses the sleep, so asking never wakes the model), refuses when idle sleep is off, calls `request_sleep()` unless already asleep |
| `server.cpp` | the route: `ctx_http.post("/sleep", ...)` beside `/props` |

In the repo, `server/tools/gumbo/`:
- `apply_sleep_patch.py`: applies it. Every edit is anchored on code that must appear exactly once; if any anchor is
  missing or repeated (the code moved in a new llama.cpp), **nothing is written** and it says which anchor failed.
  Running it twice is a no-op ("already patched").
- `llama-sleep-b12032.patch`: the same change as a plain unified diff against b12032, for reading or for
  `patch -p1` from the llama.cpp root when the script's anchors fail but the code is close.
- `llama-game.sh`: at every start, looks for the patch's own error text in the server library and logs
  `WARNING: ... has no /sleep route` when it is missing (in `journalctl --user -u textadventure-llm`).

## Upgrading llama.cpp: the checklist

1. Build the new llama.cpp **beside** the old one (as b12032 was beside b8580), e.g. `~/llms/llama.cpp-bNNNNN`.
2. Apply the patch before the first build, or after and rebuild:
   ```
   scp server/tools/gumbo/apply_sleep_patch.py gumbo:~/textadventure/      # if the box's copy is older
   ssh gumbo
   cd ~/llms/llama.cpp-bNNNNN/tools/server
   mkdir -p ../../.orig-before-sleep-patch && cp server-queue.h server-queue.cpp server-context.h server-context.cpp server.cpp ../../.orig-before-sleep-patch/
   python3 ~/textadventure/apply_sleep_patch.py
   cd ../../build && cmake --build . --target llama-server -j 16           # about a minute when only the server changed
   ```
3. **If the script says "NOT patched"**: llama.cpp moved the code. Read the failed anchors, find the same places in the
   new files (the idle check in `server_queue::start_loop`, the `post()` timer resets, the `post_props` handler and its
   route), make the same change by hand, update the anchors in `apply_sleep_patch.py`, regenerate the diff (step 7) and
   note the new build here. If llama.cpp has since grown its own way to sleep on demand, use that instead: change
   `profiles.box_sleep` (`server/engine/profiles.py`) and retire the patch.
4. Point the service at the new build (`LLAMA_BIN` in `textadventure-llm.service`, repo copy and the box's
   `~/.config/systemd/user/` copy), `systemctl --user daemon-reload`, restart **only when no turn is in flight**
   (`curl -s localhost:8280/slots`: no `"is_processing": true`).
5. Check the start log has **no** `WARNING ... no /sleep route`:
   `journalctl --user -u textadventure-llm -n 20 --no-pager`.
6. Check the route on the box:
   ```
   curl -s -X POST localhost:8280/sleep                    # {"success":true,"was_sleeping":false}
   sleep 2; curl -s localhost:8280/props | grep -o '"is_sleeping":[a-z]*'      # true
   nvidia-smi --query-gpu=index,memory.used --format=csv   # the 5090 back near 2.7 GB
   curl -s localhost:8280/completion -d '{"prompt":"Hi","n_predict":3,"id_slot":3}'   # wakes it (seconds), answers
   ```
   Then the game's button: Settings → the profile card → **Unload model**, or the scratch pad's.
7. Keep the diff current: from the llama.cpp root,
   `for f in server-queue.h server-queue.cpp server-context.h server-context.cpp server.cpp; do diff -u --label a/tools/server/$f --label b/tools/server/$f .orig-before-sleep-patch/$f tools/server/$f; done > llama-sleep-bNNNNN.patch`,
   commit it in `server/tools/gumbo/`, and update "Applied to" at the top of this page.

## Rolling back

The original sources are in `~/llms/llama.cpp-b12032/.orig-before-sleep-patch/`. Copy them back into `tools/server/`,
rebuild (`cmake --build . --target llama-server`), restart the service when idle. The binary
`build/bin/llama-server.before-sleep-patch` is a copy of the old executable, but the route lives in
`build/bin/libllama-server-impl.so`, which was rebuilt in place and has no copy: restore by rebuilding, not by copying
files. Without the patch everything but the button works; the button then says the patch is missing.

## The game's side

- `profiles.box_sleep` (`server/engine/profiles.py`): `POST /sleep`; a 404 is read as "this build has no patch" and the
  message names this page and the script.
- `POST /api/box/unload` (`server/app.py`): dev mode on a server whose roles play on the box only (404 otherwise);
  refused with 409 while any slot is processing (`/slots`), since the box is shared by :8013, :8018 and any probe; one
  log line `box.unload outcome=...`.
- The button (`web/src/components/UnloadButton.tsx`): in Settings on the profile card's "The box" line (dev mode), and
  at the top of the scratch pad, which also shows whether the model is loaded or unloaded.

Decision: D327 in `notes/DECISIONS.md`. The box and its scripts: `docs/LOCAL_LLM.md`.
