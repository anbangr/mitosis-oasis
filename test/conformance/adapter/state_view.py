"""Per-contract state readers and snapshot/diff machinery."""

from __future__ import annotations

from typing import Protocol

from test.conformance.oracle.schema import StateDelta


SnapshotKey = tuple[str, str, str | None]   # (contract, name, key|None)
Snapshot = dict[SnapshotKey, str | None]


class StateReader(Protocol):
    """One reader per contract. Returns the full observable state of that contract."""

    def read_all(self) -> Snapshot:
        ...


class StateView:
    """Aggregates multiple per-contract readers; snapshots and diffs them."""

    def __init__(self, readers: list[tuple[str, StateReader]]) -> None:
        self._readers = readers

    def snapshot(self) -> Snapshot:
        out: Snapshot = {}
        for _name, reader in self._readers:
            out.update(reader.read_all())
        return out

    @staticmethod
    def diff(*, pre_snapshot: Snapshot, post_snapshot: Snapshot) -> list[StateDelta]:
        deltas: list[StateDelta] = []
        all_keys = set(pre_snapshot) | set(post_snapshot)
        for k in sorted(all_keys):
            pre = pre_snapshot.get(k)
            post = post_snapshot.get(k)
            if pre == post:
                continue
            contract, name, key = k
            if pre is None:
                kind = "mapping_set" if key is not None else "field_set"
                deltas.append(StateDelta(
                    kind=kind, contract=contract, name=name, key=key, value=post,
                ))
                continue
            if post is None:
                # treated as field cleared back to None (rare)
                deltas.append(StateDelta(
                    kind="field_set", contract=contract, name=name, key=key, value=None,
                ))
                continue
            # both not-None, both differ: counter inc/dec if numeric, else field_set
            try:
                pre_i = int(pre)
                post_i = int(post)
                d = post_i - pre_i
                if d > 0:
                    deltas.append(StateDelta(
                        kind="counter_inc", contract=contract, name=name, key=key,
                        delta=str(d),
                    ))
                elif d < 0:
                    deltas.append(StateDelta(
                        kind="counter_dec", contract=contract, name=name, key=key,
                        delta=str(-d),
                    ))
                continue
            except (TypeError, ValueError):
                pass
            deltas.append(StateDelta(
                kind="field_set", contract=contract, name=name, key=key, value=post,
            ))
        return deltas
