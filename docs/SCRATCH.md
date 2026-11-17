# The scratch pad

A dev page for sending text straight to whatever model the GPU box has loaded, with no game around it: like Oobabooga's
Notebook tab. Nothing in it is tied to one model: the box is asked what it holds (see "When the model is swapped").
Built 2026-11-17 (D326). Code: `server/engine/scratch.py`, the routes `/api/scratch` and `/api/scratch/template` in
`server/app.py`, the page `web/src/components/ScratchPage.tsx`.

## Where it is

- **Scratch** in the bar, on a server whose roles play on the box (today :8013 and :8018), with dev mode on in Settings
  (and its pin, where one is set).
- Nowhere else. Without dev mode, or on a hosted server (:8014 Sonnet), the routes answer 404 and the bar shows no link.
  Lilith's :8016 runs with dev mode off (`TA_DEV_MODE=off`), so she never has it.

## The page

Three modes, in this order; Conversation is the default.

| Part | What it does |
|---|---|
| **Conversation** | A system text, then the messages so far, each in its own editable box, the model's replies too; then a box for your next message. **Send** (Ctrl+Enter) adds your message and streams the reply into a new box. Everything is sent as it stands in the boxes, so a reply you rewrite is what the model sees it said. Each box: **user / model** switches whose message it is, **delete** takes it out. **Regenerate** asks again for the last reply. Sending with the next-message box empty sends the conversation as it stands (it must end on a user message). |
| **Chat** | An optional system text and the box as one user message (`/v1/chat/completions`), as the game's roles call the model. The reply shows in an editable box under it. **Continue as conversation** carries both on into Conversation. |
| **Raw** | The box's text is the whole prompt (`/completion`, no chat template); the model continues it, into the same box. |
| **Preset** | Each box role's sampling as it plays now (the config with the box's profile laid over): narrator, assistant, referee, summarizer. Fills the fields below; editing any field makes it "custom". |
| **Sampler fields** | The samplers the game itself sends (temperature, top_p, top_k, min_p, the penalties, DRY, XTC, top-nσ, dynamic temperature). Empty is the server's own default. |
| **max tokens** | The longest reply (at most 8,192). |
| **thinking** | Conversation and Chat: the template's thinking switch (the thinking shows folded under the boxes). Raw: whether **Wrap** opens the model's thinking. |
| **Wrap in template** | Raw only. Puts the box (and the system text, if any) in the loaded model's own chat template, ending where the model's reply begins (llama-server's `/apply-template`). Then **Generate** continues it as the model's answer. |
| **Stop** | Ends the call; the box stops writing at once (the request is closed). What came so far stays. |
| **Undo** | Raw only: the text as it was before the last generation or wrap. |
| **Export** | The system text and the messages as one text (the format below), to the clipboard. Raw: the text as it is. |
| **Import** | Text from the clipboard into the boxes: with headers (or a JSON message list) it becomes the system text and the messages, in Conversation; without, it goes in the box you are on (Conversation: the next message). |
| **Clear** | Empties everything. |
| **Unload model** | At the top, beside whether the model is loaded now: frees the GPU at once instead of after the box's 10 idle minutes; the next call loads it again (about 10 s). Refused while the box is answering a request. Needs the game's llama.cpp patch: [LLAMA-SLEEP-PATCH.md](LLAMA-SLEEP-PATCH.md) (the same button is on Settings' profile card). |
| The line under the boxes | Prompt tokens (how many were cached), tokens written, speed, time, and how it ended (`stop`, `eos`, `limit`, `cancelled`). |

### The export format

```
### system
You are a pirate.

### user
What is your name?

### assistant
Arr, Captain Bluebottle.
```

A header is a line of its own: `###`, then `system`, `user` or `assistant` (`model` is read as `assistant`, any case).
The blank lines round a message are not part of it; its own lines and spaces are kept. Import also takes a JSON list of
`{"role", "content"}` (or `{"messages": [...]}`), the shape chat APIs log. A message that itself holds a line like
`### user` would split there on import. The format lives in `web/src/scratchText.ts`; its round-trip check is
`node --experimental-strip-types web/checks/scratchText.check.ts`.

Over plain `http://` (a port address such as `http://dadmini.local:8013`) the browser does not let a page use the
clipboard: Export then shows the text selected, to copy by hand, and Import opens a box to paste into. Over the
`https://` names both go straight to the clipboard.

## Raw mode: wrap first for an instruction-tuned model

An instruction-tuned model (every model the game has played on) is trained on its chat template. Given bare text with
sampling on, it can fall into loops. Measured on Gemma 4 31B, 2026-11-17, at the narrator's settings: "the the the" within
about 25 tokens, with or without `<bos>`; greedy (temperature 0) held. Inside its template it wrote as in chat (120 and 290
clean tokens on the same settings). Not yet measured on Qwen. So for prose in raw mode: type the request, **Wrap in
template**, then **Generate**. The wrap asks the box for the loaded model's own template, so it is right for whatever is
loaded. After a wrap the box holds the raw template, which you can edit: put words after the model's turn marker to start
its reply for it.

## When the model is swapped

A profile switch (Settings, or `tools/llm.py use`) can load another model while the page is open. The page asks the box
what it has loaded (its `/props`) on opening, whenever you come back to the tab, and before every Generate:
- the heading names the model file loaded now, the profile, one slot's context and the prompt cap;
- if the model or profile changed, the page says so and does not send that Generate (press it again once you have looked);
- a preset you have not edited takes the new profile's settings; custom settings are kept as they are;
- the prompt cap follows the new model's slot (below).

## Slot and limits

- Every call runs on the **side slot** (slot 3 of four, counted from 0: the narrator is 0, the assistant 1, the referee 2; `side_slot`, B405), the slot the game's odd calls already share. The
  narrator, assistant and referee keep their caches; a game running at the same time loses nothing but a share of the GPU.
  The page says when the box is busy with a turn as it opens.
- The prompt is capped at **24,000 tokens, or the loaded model's slot less the reply's length if that is smaller**
  (counted by the box's own tokenizer, the slot read from the box before each call). The Gemma profile's slots share one
  pool of 122,880 tokens, so there it is 24,000; a profile with small slots gets a smaller cap.

## Nothing kept

- The text lives in the page's memory only: Clear or a reload, and it is gone. No browser storage.
- The server stores nothing: no save, no ledger row, no recorded exchange (the game's provider is not used).
- The log gets one count-only line per call (`scratch.call`: mode, preset, thinking, prompt tokens, cached, tokens
  written, how it ended, ms), never the text. The servers on the mini reach the box directly (:8280), not through any
  caching proxy.
