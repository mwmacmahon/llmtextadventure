#!/usr/bin/env bash
# The game's own llama-server on the GPU box: one model, three slots (one per role), on its own
# port, started outside bruba's llm-manager so nothing of bruba's is touched. The GPU is shared
# both ways: before loading it asks ComfyUI (if running) to release its VRAM through ComfyUI's own
# /free endpoint (the ComfyUI process stays up and reloads on its next prompt), and after IDLE
# seconds without a request the server sleeps, dropping the model from VRAM while keeping the
# port, so ComfyUI or anything else gets the GPU back; the next game request reloads the model
# (and re-pays the roles' prompts once). Nothing else on the box is touched.
#
#   ~/textadventure/llama-game.sh            run in the foreground (Ctrl-C stops both processes)
#   systemctl --user start textadventure-llm  the same, as a service (see textadventure-llm.service)
#
# The model and its sizes come from a profile: profiles/<name>.env (MODEL=, CTX=, CKPT=, KV=, THINK_BUDGET=, TENSOR_SPLIT=),
# the active one named in profiles/ACTIVE. The profiles are written here by the helper (gpu-yield.py) from
# the repo's server/profiles/<name>.yml when the game's machine swaps (server/tools/llm.py use <name>): it
# writes the .env and ACTIVE and stops llama-server, and this script starts it again on the new profile.
# Edit profiles in the repo, not here. Values in the environment (the unit's Environment= lines) are the
# defaults a profile overrides. A new copy of THIS script needs a service restart: a swap re-runs the loop
# of the copy already running.
# A profile that never comes up (out of VRAM at load, 2026-11-01: the A3B at Q6) falls back to the last profile that did
# (profiles/LAST_GOOD) and is named in profiles/FAILED, instead of exiting into systemd's restart and failing again forever.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PROFILES="${PROFILES:-$HERE/profiles}"
LLAMA_BIN="${LLAMA_BIN:-$HOME/llms/llama.cpp/build/bin/llama-server}"
HOST="${HOST:-0.0.0.0}"          # LAN-reachable: the game runs on another machine (the MacBook now, the Mac mini later)
PORT="${PORT:-8280}"             # bruba uses 8080/8081/8082/8090/8092; ComfyUI 8188; ollama 11434
PARALLEL="${PARALLEL:-3}"        # one slot per role: narrator 0, adjudicator 1, referee 2
COMFY_URL="${COMFY_URL:-http://127.0.0.1:8188}"
IDLE="${IDLE:-600}"              # seconds idle before the server sleeps: drops the model from VRAM, keeps the port, reloads on the next request
YIELD_PORT="${YIELD_PORT:-8281}" # gpu-yield.py beside the server: POST /free-comfy, GET /models, POST /use
BASE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"   # CUDA device 0 = the RTX 5090 on this box (CUDA's order; nvidia-smi lists the 3060 first)
DEFAULT_TENSOR_SPLIT="${TENSOR_SPLIT:-}"     # "27,4": the model across the 5090 and the 3060 in that proportion; empty = the 5090 alone.
                                             # The 3060's memory is about 5x slower, so keep its share small (docs/LOCAL_LLM.md)
DEFAULT_MODEL="${MODEL:-$HOME/llms/text-generation-webui/user_data/models/Qwen3.5-35B-A3B-UD-Q4_K_XL.gguf}"
DEFAULT_CTX="${CTX:-98304}"      # total; llama-server splits it evenly across slots (32k each)
FIT_TARGET="${FIT_TARGET:-1536}" # CTX=auto: MiB llama.cpp leaves free on the GPU when it sizes the context to fit
FIT_CTX="${FIT_CTX:-49152}"      # CTX=auto: the smallest total context it may settle on (16k a slot at 3 slots)
DEFAULT_THINK_BUDGET="${THINK_BUDGET:--1}"   # llama.cpp --reasoning-budget: tokens of thinking a request with thinking on may spend before the server
                                  # closes the think block itself (-1 unlimited). Server-wide; roles with thinking off are untouched.
DEFAULT_KV="${KV:-q8_0}"        # KV cache type for the attention layers (q8_0 halves it; f16 is the full cache: ~68 KB a token on the 27B)
DEFAULT_EXTRA="${EXTRA:-}"       # extra llama-server flags, verbatim, from the profile's `extra` (D70: "--spec-type draft-mtp
                                  # --spec-draft-n-max 3" turns on the model's own MTP draft head; the helper allows flags and plain values only)
DEFAULT_CKPT="${CKPT:-512}"      # recurrent-state checkpoint every N prompt tokens (default 8192): a hybrid model can only rewind its
                                  # state to a checkpoint, so this decides how much of a shared prefix a slot can reuse.
                                  # Builds since spring 2026 call it --checkpoint-min-step (checkpoints at user-message starts and the
                                  # prompt's end, at least N apart); the flag is picked from the binary's --help below.

load_profile() {                 # the defaults, then the active profile over them
  MODEL="$DEFAULT_MODEL"; CTX="$DEFAULT_CTX"; CKPT="$DEFAULT_CKPT"; KV="$DEFAULT_KV"; THINK_BUDGET="$DEFAULT_THINK_BUDGET"
  TENSOR_SPLIT="$DEFAULT_TENSOR_SPLIT"; EXTRA="$DEFAULT_EXTRA"
  ACTIVE="$(tr -d '[:space:]' 2>/dev/null < "$PROFILES/ACTIVE" || true)"
  if [ -n "$ACTIVE" ] && [ -f "$PROFILES/$ACTIVE.env" ]; then
    set -a; . "$PROFILES/$ACTIVE.env"; set +a
  else
    ACTIVE="(defaults)"
  fi
}

[ -x "$LLAMA_BIN" ] || { echo "no llama-server at $LLAMA_BIN" >&2; exit 1; }
if "$LLAMA_BIN" --help 2>&1 | grep -q -- "--checkpoint-every-n-tokens"; then CKPT_FLAG=--checkpoint-every-n-tokens
else CKPT_FLAG=--checkpoint-min-step; fi

# Wait for the GPU. At a cold boot (2026-11-02 21:37, ISSUES L6) the service started before CUDA was ready; llama-server
# said "no CUDA-capable device is detected", ignored --n-gpu-layers and served the model from the CPU at 1.7 tok/s while
# /health said ok. So no CUDA device, no server: wait up to GPU_WAIT seconds, then fail and let systemd try again.
GPU_WAIT="${GPU_WAIT:-300}"
waited=0
until CUDA_VISIBLE_DEVICES="$BASE_DEVICES" "$LLAMA_BIN" --list-devices 2>/dev/null | grep -q "CUDA0"; do
  if [ "$waited" -ge "$GPU_WAIT" ]; then echo "no CUDA device after ${GPU_WAIT}s; not starting on the CPU" >&2; exit 1; fi
  [ "$waited" -eq 0 ] && echo "waiting for the GPU (CUDA device $BASE_DEVICES)"
  sleep 5; waited=$((waited + 5))
done

# Ask ComfyUI for its VRAM. Best effort: a ComfyUI that is not running answers nothing and we go on.
free_comfy() {
  if curl -s -m 3 -o /dev/null "$COMFY_URL/system_stats"; then
    echo "asking ComfyUI at $COMFY_URL to free its models"
    curl -s -m 10 -X POST "$COMFY_URL/free" -H 'content-type: application/json' \
         -d '{"unload_models": true, "free_memory": true}' >/dev/null || true
    sleep 3
  fi
}

# The helper, so the game can ask ComfyUI for the GPU before a sleeping server reloads, and anyone on the
# LAN can list the profiles and swap the model.
python3 "$HERE/gpu-yield.py" --port "$YIELD_PORT" --comfy "$COMFY_URL" --profiles "$PROFILES" &
YIELD_PID=$!
LLAMA_PID=""
trap 'kill $LLAMA_PID $YIELD_PID 2>/dev/null; rm -f "$PROFILES/.llama.pid"' EXIT INT TERM

while true; do
  load_profile
  [ -f "$MODEL" ] || { echo "profile $ACTIVE: no model at $MODEL" >&2; exit 1; }
  free_comfy
  rm -f "$PROFILES/.switching" "$PROFILES/.loaded"
  if [ "$CTX" = "auto" ]; then              # llama.cpp's --fit sizes the context to the free VRAM, less FIT_TARGET MiB
    CTX_ARGS=(--fit on --fit-target "$FIT_TARGET" --fit-ctx "$FIT_CTX")
  else
    CTX_ARGS=(--ctx-size "$CTX")
  fi
  if [ -n "$TENSOR_SPLIT" ]; then           # both cards, the 5090 first
    export CUDA_VISIBLE_DEVICES="0,1"; SPLIT_ARGS=(--split-mode layer --tensor-split "$TENSOR_SPLIT")
  else
    export CUDA_VISIBLE_DEVICES="$BASE_DEVICES"; SPLIT_ARGS=()
  fi
  read -ra EXTRA_ARGS <<< "$EXTRA"            # word-split on purpose: the profile's flags, as written
  echo "llama-server :$PORT, profile $ACTIVE, $PARALLEL slots, ctx $CTX, ckpt $CKPT, kv $KV, think budget $THINK_BUDGET, cards ${TENSOR_SPLIT:-5090 only}, idle sleep ${IDLE}s, extra '${EXTRA}', model $(basename "$MODEL")"
  "$LLAMA_BIN" \
    -m "$MODEL" \
    --host "$HOST" --port "$PORT" \
    --n-gpu-layers 999 \
    "${CTX_ARGS[@]}" \
    ${SPLIT_ARGS[@]+"${SPLIT_ARGS[@]}"} \
    --batch-size 1024 \
    --parallel "$PARALLEL" \
    --jinja \
    --chat-template-kwargs '{"enable_thinking": false}' \
    --reasoning-format deepseek \
    --cache-type-k "$KV" --cache-type-v "$KV" \
    --reasoning-budget "$THINK_BUDGET" --reasoning-budget-message "Time is short. I will answer now, from what I have." \
    --flash-attn on \
    --no-context-shift \
    --sleep-idle-seconds "$IDLE" \
    "$CKPT_FLAG" "$CKPT" \
    ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"} \
    --temp 0.7 --top-p 0.8 --top-k 20 --min-p 0.0 &
  LLAMA_PID=$!
  echo "$LLAMA_PID" > "$PROFILES/.llama.pid"
  (                                         # once it answers /health the profile is good: remember it as the fallback
    while kill -0 "$LLAMA_PID" 2>/dev/null; do
      if curl -s -m 2 -o /dev/null -f "http://127.0.0.1:$PORT/health"; then
        touch "$PROFILES/.loaded"; echo "$ACTIVE" > "$PROFILES/LAST_GOOD"; rm -f "$PROFILES/FAILED"; exit 0
      fi
      sleep 2
    done
  ) &
  WATCH_PID=$!
  set +e; wait "$LLAMA_PID"; CODE=$?; set -e
  kill "$WATCH_PID" 2>/dev/null || true
  if [ -f "$PROFILES/.switching" ]; then     # the helper stopped it to swap the model: start again on the new profile
    echo "swapping to profile $(tr -d '[:space:]' < "$PROFILES/ACTIVE")"
    sleep 2
    continue
  fi
  GOOD="$(tr -d '[:space:]' 2>/dev/null < "$PROFILES/LAST_GOOD" || true)"
  if [ ! -f "$PROFILES/.loaded" ] && [ -n "$GOOD" ] && [ "$GOOD" != "$ACTIVE" ] && [ -f "$PROFILES/$GOOD.env" ]; then
    echo "profile $ACTIVE never came up (exit $CODE); back to $GOOD" >&2
    echo "$ACTIVE" > "$PROFILES/FAILED"
    echo "$GOOD" > "$PROFILES/ACTIVE"
    sleep 2
    continue
  fi
  exit "$CODE"
done
