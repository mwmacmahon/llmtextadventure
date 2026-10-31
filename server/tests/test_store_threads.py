"""The store's one connection is shared by request threads: two games created at once must not collide."""
from concurrent.futures import ThreadPoolExecutor

from engine.store import Store


def test_concurrent_writes(tmp_path):
    st = Store(tmp_path / "t.sqlite3")
    state = {"blob": "x" * 20000}

    def make(i):
        iid = st.create_instance("g", "1", f"t{i}", {}, "prefix", state)
        for turn in range(1, 4):
            st.save_snapshot(iid, turn, state)
            st.append_transcript(iid, turn, "narrator", "words " * 200)
        return iid

    with ThreadPoolExecutor(8) as ex:
        iids = list(ex.map(make, range(16)))
    assert all(st.latest_turn(i) == 3 for i in iids)
