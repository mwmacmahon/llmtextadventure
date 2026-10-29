#!/usr/bin/env bash
# The game's own llama-server on the GPU box: one model, three slots (one per role), on its own
# port, started outside bruba's llm-manager so nothing of bruba's is touched. Before loading it
# asks ComfyUI (if running) to release its VRAM through ComfyUI's own /free endpoint; the ComfyUI
# process stays up and reloads its models on its next prompt. Nothing else on the box is touched.
#
#   ~/textadventure/llama-game.sh            run in the foreground (Ctrl-C stops it)
#   systemctl --user start textadventure-llm  the same, as a service (see textadventure-llm.service)
#
# Every value can be overridden in the environment, e.g. PORT=8281 CTX=65536 ./llama-game.sh
set -euo pipefail

LLAMA_BIN="${LLAMA_BIN:-$HOME/llms/llama.cpp/build/bin/llama-server}"
MODEL="${MODEL:-$HOME/llms/text-generation-webui/user_data/models/Qwen3.5-35B-A3B-UD-Q4_K_XL.gguf}"
HOST="${HOST:-0.0.0.0}"          # LAN-reachable: the game runs on another machine (the MacBook now, the Mac mini later)
PORT="${PORT:-8280}"             # bruba uses 8080/8081/8082/8090/8092; ComfyUI 8188; ollama 11434
PARALLEL="${PARALLEL:-3}"        # one slot per role: narrator 0, adjudicator 1, referee 2
CTX="${CTX:-98304}"              # total; llama-server splits it evenly across slots (32k each)
COMFY_URL="${COMFY_URL:-http://127.0.0.1:8188}"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"   # CUDA device 0 = the RTX 5090 on this box

[ -x "$LLAMA_BIN" ] || { echo "no llama-server at $LLAMA_BIN" >&2; exit 1; }
[ -f "$MODEL" ] || { echo "no model at $MODEL" >&2; exit 1; }

# Ask ComfyUI for its VRAM. Best effort: a ComfyUI that is not running answers nothing and we go on.
if curl -s -m 3 -o /dev/null "$COMFY_URL/system_stats"; then
  echo "asking ComfyUI at $COMFY_URL to free its models"
  curl -s -m 10 -X POST "$COMFY_URL/free" -H 'content-type: application/json' \
       -d '{"unload_models": true, "free_memory": true}' >/dev/null || true
  sleep 3
fi

echo "llama-server :$PORT, $PARALLEL slots, ctx $CTX, model $(basename "$MODEL")"
exec "$LLAMA_BIN" \
  -m "$MODEL" \
  --host "$HOST" --port "$PORT" \
  --n-gpu-layers 999 \
  --ctx-size "$CTX" \
  --batch-size 1024 \
  --parallel "$PARALLEL" \
  --jinja \
  --chat-template-kwargs '{"enable_thinking": false}' \
  --reasoning-format deepseek \
  --cache-type-k q8_0 --cache-type-v q8_0 \
  --flash-attn on \
  --no-context-shift \
  --rope-freq-base 1000000 \
  --temp 0.7 --top-p 0.8 --top-k 20 --min-p 0.0
