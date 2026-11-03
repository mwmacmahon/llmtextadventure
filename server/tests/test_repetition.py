"""engine/repetition.py: a telling that repeats an earlier one (P1, D77)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.repetition import overlap, ruling  # noqa: E402

A = ("You stand at the rail of the pier while the rain comes down in long grey ropes and the lake slaps the pilings "
     "underneath you, and somewhere out past the breakwater a bell buoy rings once and then is quiet, as if it "
     "had thought better of it, and you light a match that the wind takes before it reaches the cigarette.")
B = ("Brandt does not look up from the ledger. The pen moves, stops, moves again. Behind him the radiator knocks "
     "twice and gives up. You count the knocks because it is something to count, and when he finally speaks it "
     "is to the page and not to you, and what he says is that the desk wrote Pier Street and he signed it after.")


def test_continuing_prose_shares_little_and_a_retold_turn_shares_most():
    assert overlap(B, [A])[0] < 0.05
    frac, at = overlap(A, [B, A])
    assert at == 1 and frac == 1.0
    half = A + " " + B                      # half new words: about half the shingles are old
    frac, _ = overlap(half, [A])
    assert 0.4 < frac < 0.6


def test_short_text_is_never_judged_and_the_ruling_names_the_turn():
    assert overlap("The rain keeps on.", [A]) == (0.0, -1)
    assert ruling(B, [(1, A)]) is None
    r = ruling(A, [(3, B), (4, A)])
    assert r and r["rule"] == "repetition" and r["serious"] and r["of_turn"] == 4 and "turn 4" in r["what"] and "nothing happens twice" in r["fix"]
