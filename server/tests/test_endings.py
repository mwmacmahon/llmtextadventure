"""END1 (D123): the saved ending reads the state, not a flag only the referee could set."""
from engine.config import load_config
from engine.events import evaluate
from engine.registry import load_games


def _game():
    cfg = load_config()
    return load_games(cfg.resolve(cfg.server.content_root))["noir"]


def _saved(game, st):
    doc = st.model_dump(mode="json")
    e = next(e for e in st.hidden.events if e.id == "ending_saved")
    return evaluate(e.trigger, doc, st.hidden.events, 1)


def test_june_found_and_somewhere_safe_ends_the_round():
    g = _game()
    _, st = g.new_instance({})
    june = next(p for p in st.people if p.id == "june")
    assert not _saved(g, st)
    st.flags["june_found"] = True
    june.location = "Under the docks"
    assert not _saved(g, st)                      # found is not saved
    june.location = "Kessler house"
    assert _saved(g, st)
    june.status = "dead"
    assert not _saved(g, st)


def test_the_flag_alone_still_ends_it_and_the_ending_sets_it():
    g = _game()
    _, st = g.new_instance({})
    st.flags["june_rescued"] = True
    assert _saved(g, st)
    e = next(e for e in st.hidden.events if e.id == "ending_saved")
    assert any(fx.get("flag") == ["june_rescued", True] for fx in e.effects)
