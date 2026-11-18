"""The planner panels' contract (docs/PLANNER-CONTRACT.md): the web's made-up sample, which the client's panels are built
against, is valid for the engine's models and comes back from them unchanged, so the two sides agree on every shape."""
import json
from pathlib import Path

from engine.game import Cards, Chart, Profile, Roster, UISchema

SAMPLE = json.loads((Path(__file__).resolve().parents[2] / "web" / "fixtures" / "plan_sample.json").read_text())


def _same(sent: dict, back: dict) -> None:
    """Every key the sample sends comes back with the same value (the models may add defaults, never change a value)."""
    for k, v in sent.items():
        assert k in back, k
        if isinstance(v, dict):
            _same(v, back[k])
        elif isinstance(v, list) and v and isinstance(v[0], dict):
            assert len(v) == len(back[k]), k
            for a, b in zip(v, back[k]):
                _same(a, b)
        else:
            assert back[k] == v, (k, v, back[k])


def test_each_panel_round_trips():
    for key, model in (("chart", Chart), ("cards", Cards), ("roster", Roster), ("profile", Profile)):
        _same(SAMPLE[key], model.model_validate(SAMPLE[key]).model_dump(mode="json"))


def test_the_ui_schema_takes_them_and_keeps_their_type():
    ui = UISchema(panels=[SAMPLE[k] for k in ("chart", "cards", "roster", "profile")])
    assert [type(p).__name__ for p in ui.panels] == ["Chart", "Cards", "Roster", "Profile"]
    dumped = ui.model_dump(mode="json")["panels"]
    assert [p["type"] for p in dumped] == ["chart", "cards", "roster", "profile"]


def test_the_chart_sample_is_whole():
    c = SAMPLE["chart"]
    assert len(c["cells"]) == len(c["rows"]) * len(c["columns"])
    ids = {x["id"] for x in c["choices"]}
    assert all(cell["v"] is None or cell["v"] in ids for cell in c["cells"])
    for ch in c["choices"]:   # availability names real, open cells
        for i in ch.get("where") or []:
            assert 0 <= i < len(c["cells"]) and c["rows"][i // len(c["columns"])]["paintable"]
