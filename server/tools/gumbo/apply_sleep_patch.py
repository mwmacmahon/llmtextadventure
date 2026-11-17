#!/usr/bin/env python3
"""Adds POST /sleep to llama.cpp's server (the game's unload button, D327; docs/LLAMA-SLEEP-PATCH.md is the procedure).

    cd <llama.cpp>/tools/server && python3 ~/textadventure/apply_sleep_patch.py     (or: python3 apply_sleep_patch.py <that dir>)
    then rebuild: cd <llama.cpp>/build && cmake --build . --target llama-server -j 16

Written against llama.cpp b12032 (llama-sleep-b12032.patch beside this file is the same change as a plain diff).
Each edit is anchored on text that must appear exactly once; if any anchor is missing or repeated, nothing is written and the
script says which, so an upgrade that moved the code fails loudly instead of half-patching. Re-running on a patched tree is a
no-op (the marker is found)."""
import sys
from pathlib import Path

MARK = "TEXTADVENTURE-SLEEP-PATCH"
EDITS = [
    ("server-queue.h", "    bool req_stop_sleeping = false;\n",
     "    bool req_stop_sleeping = false;\n    bool req_sleep_now = false; // " + MARK + ": POST /sleep asked for the idle sleep now\n"),
    ("server-queue.h", "    bool is_sleeping() {\n",
     "    // " + MARK + ": enter the idle sleep at the next idle moment, as --sleep-idle-seconds would; a task that resets the\n"
     "    // idle timer before then cancels it (so it never lands in the middle of work). Ignored when idle sleep is off.\n"
     "    void request_sleep();\n\n    bool is_sleeping() {\n"),
    ("server-queue.cpp", "void server_queue::start_loop(int64_t idle_sleep_ms) {\n",
     "void server_queue::request_sleep() { // " + MARK + "\n    std::unique_lock<std::mutex> lock(mutex_tasks);\n"
     "    req_sleep_now = true;\n    condition_tasks.notify_all();\n}\n\nvoid server_queue::start_loop(int64_t idle_sleep_ms) {\n"),
    ("server-queue.cpp", "        int64_t now = ggml_time_ms();\n        return (now - time_last_task) >= idle_sleep_ms;\n",
     "        if (req_sleep_now) { // " + MARK + "\n            return true;\n        }\n"
     "        int64_t now = ggml_time_ms();\n        return (now - time_last_task) >= idle_sleep_ms;\n"),
    ("server-queue.cpp", "                QUE_INF(\"%s\", \"entering sleeping state\\n\");\n                sleeping = true;\n",
     "                QUE_INF(\"%s\", \"entering sleeping state\\n\");\n                req_sleep_now = false; // " + MARK + "\n                sleeping = true;\n"),
    ("server-queue.cpp", "                    return (!queue_tasks.empty() || !running);\n",
     "                    return (!queue_tasks.empty() || !running || req_sleep_now); // " + MARK + ": wake to sleep at once\n"),
    ("server-context.h", "    server_http_context::handler_t post_props;\n",
     "    server_http_context::handler_t post_props;\n    server_http_context::handler_t post_sleep; // " + MARK + "\n"),
    ("server-context.cpp", "    this->post_infill = [this](const server_http_req & req) {\n",
     "    // " + MARK + ": POST /sleep, the idle sleep now (drops the model from VRAM; the next request reloads it)\n"
     "    this->post_sleep = [this](const server_http_req &) {\n"
     "        auto res = create_response(true); // never wakes a sleeping server\n"
     "        if (params.sleep_idle_seconds < 0) {\n"
     "            res->error(format_error_response(\"idle sleep is off: start the server with --sleep-idle-seconds\", ERROR_TYPE_NOT_SUPPORTED));\n"
     "            return res;\n        }\n"
     "        const bool was = queue_tasks.is_sleeping();\n"
     "        if (!was) {\n            queue_tasks.request_sleep();\n        }\n"
     "        res->ok({{ \"success\", true }, { \"was_sleeping\", was }});\n        return res;\n    };\n\n"
     "    this->post_infill = [this](const server_http_req & req) {\n"),
    ("server.cpp", "    ctx_http.post(\"/props\",                    ex_wrapper(routes.post_props));\n",
     "    ctx_http.post(\"/props\",                    ex_wrapper(routes.post_props));\n"
     "    ctx_http.post(\"/sleep\",                    ex_wrapper(routes.post_sleep)); // " + MARK + "\n"),
]
# the post() paths that reset the idle timer also cancel a pending sleep request (a turn arrived first)
RESET = "    if (reset_timer) {\n        time_last_task = ggml_time_ms();\n    }\n"
RESET_NEW = "    if (reset_timer) {\n        time_last_task = ggml_time_ms();\n        req_sleep_now = false; // " + MARK + ": work came first\n    }\n"

def main() -> int:
    here = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    texts = {f: (here / f).read_text() for f in {e[0] for e in EDITS}}
    if any(MARK in t for t in texts.values()):
        if all(MARK in texts[f] for f in texts):
            print("already patched"); return 0
        print("PARTLY patched: restore the originals and run again"); return 1
    bad = []
    for f, old, new in EDITS:
        n = texts[f].count(old)
        if n != 1:
            bad.append(f"{f}: anchor found {n} times: {old.splitlines()[0].strip()!r}")
        else:
            texts[f] = texts[f].replace(old, new)
    n = texts["server-queue.cpp"].count(RESET)
    if n != 2:
        bad.append(f"server-queue.cpp: the post() timer reset found {n} times, expected 2")
    else:
        texts["server-queue.cpp"] = texts["server-queue.cpp"].replace(RESET, RESET_NEW)
    if bad:
        print("NOT patched, nothing written:\n  " + "\n  ".join(bad)); return 1
    for f, t in texts.items():
        (here / f).write_text(t)
    print("patched: " + ", ".join(sorted(texts))); return 0

if __name__ == "__main__":
    sys.exit(main())
