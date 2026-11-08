"""A job turned down (the owner, 11-08 evening): the referee marks it; the bulletin stops listing it as in motion and tells the
narrator its giver goes back to their own business; the deck does not count it; going where it happens takes it up again."""
from __future__ import annotations

import pytest

from engine.roles import Change as C
from games.fantasy import deck as dk
from test_fantasy import CONTENT, SHEET, apply, engine, game, info, new  # noqa: F401

pytestmark = pytest.mark.skipif(not (CONTENT / "scenarios" / "marrowgate.yml").exists(), reason="the fantasy content is not on this machine")


def _live(game, st, hid="cellar_rats"):
    h = st.hook(hid)
    h.status, h.giver, h.thread = "live", "Maud Tallow", f"hook-{hid}"
    return st


def test_a_refused_job_leaves_the_quests_in_motion_and_maud_goes_back_to_her_bar(game):
    st = _live(game, new(game))
    assert "- Rats in the Cellar (from Maud Tallow)" in game.render_bulletin(st, "")
    s1, rep, _ = apply(game, st, C(kind="set", target="hook-cellar_rats", field="declined", value="true"))
    assert s1.hook("cellar_rats").declined and s1.hook("cellar_rats").standing == "turned down"
    b = game.render_bulletin(s1, "")
    assert "Quests in motion" not in b or "- Rats in the Cellar (from" not in b
    assert "Jobs Wren turned down. Whoever offered one treats Wren as before" in b and "- Rats in the Cellar (offered by Maud Tallow)" in b
    assert dk.in_motion(s1) == dk.in_motion(st) - 1                       # the deck may deal another
    s2, _, _ = apply(game, s1, C(kind="set", target="hook-cellar_rats", field="declined", value="false"))
    assert not s2.hook("cellar_rats").declined and s2.hook("cellar_rats").standing == "taken up"


def test_going_where_the_job_happens_takes_it_up_again(game):
    st = _live(game, new(game))
    st.hook("cellar_rats").declined = True
    st.player.location = "The Old Channel"
    s1 = game.after_turn(st, info())
    assert not s1.hook("cellar_rats").declined
    st.player.location = "The Drowned Lantern"                          # where it was offered: still turned down
    st.hook("cellar_rats").declined = True
    assert game.after_turn(st, info()).hook("cellar_rats").declined
