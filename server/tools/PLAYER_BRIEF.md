# The player's brief (for a Claude Code subagent; D84)

Fill the four fields, hand the whole file to a subagent (the Agent tool, model opus), and it plays the round through
`tools/turn.py`. It sees only what a human player would: the opening, each turn's prose, the panels. It never reads the
server's logs, the store, the scenario files or the notes.

```
GAME:    noir | station
SERVER:  http://127.0.0.1:8013        (TA_URL; :8013 is the local model, :8012 the Sonnet roles: say which was agreed)
TAG:     r14L-plain                   (the transcript's name: notes/playtests/<date>-<game>-<tag>.md)
TITLE:   Local long round 1, plain
GOAL:    find June Kessler fast: take risks, force doors, lean hard on people, act first and ask later
TURNS:   50
```

You are playing a text adventure as the player. Your goal is the GOAL above. You play TURNS turns, one at a time,
through the command line, from the directory `server/` of the checkout, with `TA_URL` set to SERVER:

1. Start: `TA_URL=<SERVER> .venv/bin/python tools/turn.py new <GAME> --tag <TAG> --title "<TITLE>"`. Read the
   instance id, the opening and what you see.
2. Each turn: `TA_URL=<SERVER> .venv/bin/python tools/turn.py play <id> <what you do>`. Write only what you do next,
   as the player would type it: one to three sentences, first person, concrete, no commentary, no options. Quote it as
   one shell argument. Use the game's own levers when they fit (you may write things like "I seal the Lab hatches" or
   "I nudge Park's implant toward calm"). Vary your approach: talk to people through their assistants, read what they
   keep private, forge a line, apply pressure, watch. React to what just happened. Waiting is a last resort, never two
   turns running: if nothing is happening, make something happen. If an approach has failed twice, do something
   different, not the same thing worded differently.
3. If the output says `[ENDING]`, stop. If it says `[ERROR]`, try the same turn once more; if it errors again, stop and
   say so.
4. After the last turn: `TA_URL=<SERVER> .venv/bin/python tools/turn.py finish <id> --title "<TITLE>"`.

Your final message: the instance id, the number of turns played, the two paths `finish` printed, and three sentences on
how the round went from the player's chair (where you got to, what worked, what the game refused or repeated). Nothing
else; do not paste the prose.
