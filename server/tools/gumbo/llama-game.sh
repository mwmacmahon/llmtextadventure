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
# The model and its sizes come from a profile: profiles/<name>.env (MODEL=, CTX=, CKPT=, any of the values
# below), the active one named in profiles/ACTIVE. Swap models from anywhere on the LAN through the helper
# (POST :8281/use {"profile": "qwen27b"}, or server/tools/llm.py on the game's machine): it writes ACTIVE
# and stops llama-server, and this script starts it again on the new profile. Values in the environment
# (the unit's Environment= lines) are the defaults a profile overrides.
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
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"   # CUDA device 0 = the RTX 5090 on this box
DEFAULT_MODEL="${MODEL:-$HOME/llms/text-generation-webui/user_data/models/Qwen3.5-35B-A3B-UD-Q4_K_XL.gguf}"
DEFAULT_CTX="${CTX:-98304}"      # total; llama-server splits it evenly across slots (32k each)
FIT_TARGET="${FIT_TARGET:-1536}" # CTX=auto: MiB llama.cpp leaves free on the GPU when it sizes the context to fit
FIT_CTX="${FIT_CTX:-49152}"      # CTX=auto: the smallest total context it may settle on (16k a slot at 3 slots)
DEFAULT_THINK_BUDGET="${THINK_BUDGET:--1}"   # llama.cpp --reasoning-budget: tokens of thinking a request with thinking on may spend before the server
                                  # closes the think block itself (-1 unlimited). Server-wide; roles with thinking off are untouched.
DEFAULT_KV="${KV:-q8_0}"        # KV cache type for the attention layers (q8_0 halves it; f16 is the full cache: ~68 KB a token on the 27B)
DEFAULT_CKPT="${CKPT:-512}"      # recurrent-state checkpoint every N prompt tokens (default 8192): a hybrid model can only rewind its
                                  # state to a checkpoint, so this decides how much of a shared prefix a slot can reuse

load_profile() {                 # the defaults, then the active profile over them
  MODEL="$DEFAULT_MODEL"; CTX="$DEFAULT_CTX"; CKPT="$DEFAULT_CKPT"; KV="$DEFAULT_KV"; THINK_BUDGET="$DEFAULT_THINK_BUDGET"
  ACTIVE="$(tr -d '[:space:]' 2>/dev/null < "$PROFILES/ACTIVE" || true)"
  if [ -n "$ACTIVE" ] && [ -f "$PROFILES/$ACTIVE.env" ]; then
    set -a; . "$PROFILES/$ACTIVE.env"; set +a
  else
    ACTIVE="(defaults)"
  fi
}

[ -x "$LLAMA_BIN" ] || { echo "no llama-server at $LLAMA_BIN" >&2; exit 1; }

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
  rm -f "$PROFILES/.switching"
  if [ "$CTX" = "auto" ]; then              # llama.cpp's --fit sizes the context to the free VRAM, less FIT_TARGET MiB
    CTX_ARGS=(--fit on --fit-target "$FIT_TARGET" --fit-ctx "$FIT_CTX")
  else
    CTX_ARGS=(--ctx-size "$CTX")
  fi
  echo "llama-server :$PORT, profile $ACTIVE, $PARALLEL slots, ctx $CTX, ckpt $CKPT, kv $KV, think budget $THINK_BUDGET, idle sleep ${IDLE}s, model $(basename "$MODEL")"
  "$LLAMA_BIN" \
    -m "$MODEL" \
    --host "$HOST" --port "$PORT" \
    --n-gpu-layers 999 \
    "${CTX_ARGS[@]}" \
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
    --checkpoint-every-n-tokens "$CKPT" \
    --rope-freq-base 1000000 \
    --temp 0.7 --top-p 0.8 --top-k 20 --min-p 0.0 &
  LLAMA_PID=$!
  echo "$LLAMA_PID" > "$PROFILES/.llama.pid"
  set +e; wait "$LLAMA_PID"; CODE=$?; set -e
  if [ -f "$PROFILES/.switching" ]; then     # the helper stopped it to swap the model: start again on the new profile
    echo "swapping to profile $(tr -d '[:space:]' < "$PROFILES/ACTIVE")"
    sleep 2
    continue
  fi
  exit "$CODE"
done
