"""StateView snapshot + diff helpers."""

from test.conformance.adapter.state_view import StateView, StateReader
from test.conformance.oracle.schema import StateDelta


class FakeReader(StateReader):
    """In-memory reader for tests."""

    def __init__(self, store: dict[tuple[str, str, str | None], str]) -> None:
        self.store = store

    def read_all(self) -> dict[tuple[str, str, str | None], str]:
        return dict(self.store)


def test_diff_detects_new_field():
    pre = FakeReader({})
    post = FakeReader({("X", "q", None): "100"})
    deltas = StateView(readers=[("X", post)]).diff(
        pre_snapshot={("X", "q", None): None},
        post_snapshot={("X", "q", None): "100"},
    )
    assert deltas == [
        StateDelta(kind="field_set", contract="X", name="q", key=None, value="100",
                   delta=None)
    ]


def test_diff_detects_mapping_set():
    deltas = StateView(readers=[]).diff(
        pre_snapshot={("R", "ownerOf", "1"): None},
        post_snapshot={("R", "ownerOf", "1"): "0xabc"},
    )
    assert deltas == [
        StateDelta(kind="mapping_set", contract="R", name="ownerOf", key="1",
                   value="0xabc", delta=None)
    ]


def test_diff_detects_counter_increment():
    deltas = StateView(readers=[]).diff(
        pre_snapshot={("R", "totalSupply", None): "5"},
        post_snapshot={("R", "totalSupply", None): "7"},
    )
    assert deltas == [
        StateDelta(kind="counter_inc", contract="R", name="totalSupply",
                   key=None, value=None, delta="2")
    ]


def test_diff_detects_counter_decrement():
    deltas = StateView(readers=[]).diff(
        pre_snapshot={("R", "balance", "0xa"): "10"},
        post_snapshot={("R", "balance", "0xa"): "3"},
    )
    assert deltas == [
        StateDelta(kind="counter_dec", contract="R", name="balance", key="0xa",
                   value=None, delta="7")
    ]


def test_diff_no_changes_returns_empty():
    snap = {("X", "q", None): "100"}
    deltas = StateView(readers=[]).diff(pre_snapshot=snap, post_snapshot=snap)
    assert deltas == []


def test_snapshot_aggregates_multiple_readers():
    r1 = FakeReader({("A", "x", None): "1"})
    r2 = FakeReader({("B", "y", "k"): "2"})
    snap = StateView(readers=[("A", r1), ("B", r2)]).snapshot()
    assert snap == {("A", "x", None): "1", ("B", "y", "k"): "2"}
