# Bundle 3 — Hybrid Security Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the spec's hybrid on-chain/off-chain security model — periodic Merkle-root anchoring of event-log batches into an `on_chain_anchor` table, plus Mission-boundary reconciliation that compares off-chain vs on-chain records and suspends Missions on divergence. Lands `mitosis-oasis` at version **0.6.0**. Unblocks SP-1h–SP-4h hybrid-invariant experiments and `τ_anchor`-parameterised damage-bound studies.

**Architecture:** Pure-Python Merkle tree at `oasis/crypto/merkle.py` (~40 LoC). New `oasis/adjudication/anchor_publisher.py` background task commits one Merkle root per `τ_anchor` interval. New `oasis/adjudication/reconciliation.py` runs at Mission boundary. One new table (`on_chain_anchor`). One new column (`event_log.anchor_id`).

**Tech Stack:** Python 3.10-3.11, FastAPI, SQLite, pytest, apscheduler (already pulled in by Bundle 2).

**Depends on:** Bundle 1 merged (v0.4.0). Specifically `oasis.crypto.*` package exists. Can ship in parallel with Bundle 2.

**Merkle implementation:** Pure-Python, standard balanced-binary, SHA-256 over `json.dumps(event, sort_keys=True).encode()` leaves. ~40 LoC + 6 unit tests. No external Merkle library.

**Source spec:** [2026-05-18-agentcity-v097-parity-design.md](../specs/2026-05-18-agentcity-v097-parity-design.md) sections 2 (Bundle 3), 3 (crypto/merkle), 4 (Flow 4 + Flow 5).

---

## File Map

**New files (5):**

- `oasis/crypto/merkle.py` — `build_root`, `proof`, `verify_proof`
- `oasis/adjudication/anchor_publisher.py` — background task; `publish_anchor()`
- `oasis/adjudication/reconciliation.py` — `reconcile_mission()`
- `test/crypto/test_merkle.py` — unit
- `test/spec_v097/test_exe_088_tau_anchor.py`
- `test/spec_v097/test_exe_089_merkle_off_on_chain.py`
- `test/spec_v097/test_exe_091_reconciliation.py`
- `test/spec_v097/test_inv_140_sp_hybrid_invariants.py`

**Modified files (4):**

- `oasis/observatory/schema.py` — add `on_chain_anchor` table; add `anchor_id` column to `event_log`
- `oasis/adjudication/scheduler.py` — register anchor_publisher + reconciliation jobs
- `oasis/api.py` — pass `event_log` db_path to scheduler
- `oasis/config.py` — add `tau_anchor_small_seconds`, `tau_anchor_large_seconds`, `anchor_batch_max_size` knobs
- `oasis/governance/schema.py` — add `tau_anchor_small_seconds=10`, `tau_anchor_large_seconds=60`, `anchor_batch_max_size=1000` constitution params
- `pyproject.toml` — version 0.5.0 → 0.6.0

**Extended:**

- `test/e2e/test_full_protocol_smoke.py` — Bundle-3 waypoint (events anchored within τ_anchor, reconciliation PASS)

---

## Task 1: `oasis/crypto/merkle.py` (TDD)

**Files:**

- Create: `oasis/crypto/merkle.py`
- Create: `test/crypto/test_merkle.py`

- [ ] **Step 1.1: Write failing tests**

Create `test/crypto/test_merkle.py`:

```python
"""Pure-Python balanced-binary Merkle tree, SHA-256."""
from __future__ import annotations

import hashlib

import pytest

from oasis.crypto import merkle


def test_empty_root_is_zero32():
    assert merkle.build_root([]) == b"\x00" * 32


def test_single_leaf_root_equals_leaf():
    leaf = b"hello"
    expected = hashlib.sha256(leaf).digest()
    assert merkle.build_root([leaf]) == expected


def test_two_leaf_root():
    a = hashlib.sha256(b"a").digest()
    b = hashlib.sha256(b"b").digest()
    expected = hashlib.sha256(a + b).digest()
    assert merkle.build_root([b"a", b"b"]) == expected


def test_odd_leaf_count_duplicates_last():
    """Standard convention: with an odd leaf count, the last is duplicated."""
    a = hashlib.sha256(b"a").digest()
    b = hashlib.sha256(b"b").digest()
    c = hashlib.sha256(b"c").digest()
    ab = hashlib.sha256(a + b).digest()
    cc = hashlib.sha256(c + c).digest()
    expected = hashlib.sha256(ab + cc).digest()
    assert merkle.build_root([b"a", b"b", b"c"]) == expected


def test_proof_and_verify_roundtrip():
    leaves = [f"leaf-{i}".encode() for i in range(8)]
    root = merkle.build_root(leaves)
    for i, leaf in enumerate(leaves):
        proof = merkle.proof(leaves, i)
        assert merkle.verify_proof(root, leaf, i, proof) is True


def test_verify_rejects_tampered_leaf():
    leaves = [f"leaf-{i}".encode() for i in range(8)]
    root = merkle.build_root(leaves)
    proof = merkle.proof(leaves, 0)
    assert merkle.verify_proof(root, b"TAMPERED", 0, proof) is False
```

Run: `pytest test/crypto/test_merkle.py -v`
Expected: ImportError on the module.

- [ ] **Step 1.2: Implement `oasis/crypto/merkle.py`**

```python
"""Pure-Python Merkle tree, SHA-256, balanced-binary with last-leaf
duplication on odd counts. Used by Bundle 3 for off-chain → on-chain
event-log anchoring.

Stateless, no I/O.
"""
from __future__ import annotations

import hashlib
from typing import Sequence


def _h(b: bytes) -> bytes:
    return hashlib.sha256(b).digest()


def _hash_leaf(leaf: bytes) -> bytes:
    return _h(leaf)


def _hash_pair(left: bytes, right: bytes) -> bytes:
    return _h(left + right)


def build_root(leaves: Sequence[bytes]) -> bytes:
    """Return the 32-byte Merkle root over `leaves`.

    Empty input → all-zero 32-byte sentinel. Single leaf → SHA-256 of
    that leaf. Odd intermediate level → last node duplicated.
    """
    if not leaves:
        return b"\x00" * 32
    level = [_hash_leaf(b) for b in leaves]
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level), 2):
            left = level[i]
            right = level[i + 1] if i + 1 < len(level) else level[i]
            nxt.append(_hash_pair(left, right))
        level = nxt
    return level[0]


def proof(leaves: Sequence[bytes], target_index: int) -> list[bytes]:
    """Return the Merkle proof (list of sibling hashes) for `target_index`."""
    if target_index < 0 or target_index >= len(leaves):
        raise IndexError(f"target_index {target_index} out of range")
    level = [_hash_leaf(b) for b in leaves]
    idx = target_index
    out: list[bytes] = []
    while len(level) > 1:
        if idx % 2 == 0:
            sibling_idx = idx + 1 if idx + 1 < len(level) else idx
        else:
            sibling_idx = idx - 1
        out.append(level[sibling_idx])
        nxt = []
        for i in range(0, len(level), 2):
            left = level[i]
            right = level[i + 1] if i + 1 < len(level) else level[i]
            nxt.append(_hash_pair(left, right))
        level = nxt
        idx //= 2
    return out


def verify_proof(root: bytes, leaf: bytes, target_index: int,
                  proof_path: Sequence[bytes]) -> bool:
    """Verify a Merkle proof."""
    current = _hash_leaf(leaf)
    idx = target_index
    for sibling in proof_path:
        if idx % 2 == 0:
            current = _hash_pair(current, sibling)
        else:
            current = _hash_pair(sibling, current)
        idx //= 2
    return current == root
```

- [ ] **Step 1.3: Run + commit**

Run: `pytest test/crypto/test_merkle.py -v`
Expected: 6 passed.

```bash
git add oasis/crypto/merkle.py test/crypto/test_merkle.py
git commit -m "feat(crypto/merkle): pure-Python balanced-binary Merkle tree"
```

---

## Task 2: Schema — `on_chain_anchor` table + `event_log.anchor_id`

**Files:**

- Modify: `oasis/observatory/schema.py`
- Modify: `oasis/governance/schema.py` (add constitution params)

- [ ] **Step 2.1: Schema additions**

In `oasis/observatory/schema.py`, append to the DDL:

```sql
-- on_chain_anchor (Bundle 3, spec exec §7)
CREATE TABLE IF NOT EXISTS on_chain_anchor (
    anchor_id          TEXT PRIMARY KEY,
    merkle_root_hex    TEXT NOT NULL,
    batch_start_seq    INTEGER NOT NULL,
    batch_end_seq      INTEGER NOT NULL,
    event_count        INTEGER NOT NULL,
    committed_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    mission_id         TEXT
);

CREATE INDEX IF NOT EXISTS idx_anchor_mission ON on_chain_anchor(mission_id);
CREATE INDEX IF NOT EXISTS idx_anchor_committed_at ON on_chain_anchor(committed_at);
```

And in the idempotent ALTER block:

```python
        "ALTER TABLE event_log ADD COLUMN anchor_id TEXT REFERENCES on_chain_anchor(anchor_id)",
```

- [ ] **Step 2.2: Constitution params**

In `oasis/governance/schema.py` `_DEFAULT_CONSTITUTION`:

```python
    ("tau_anchor_small_seconds",   10.0,  "integer", "Checkpoint interval for small DAGs (spec exec §7)"),
    ("tau_anchor_large_seconds",   60.0,  "integer", "Checkpoint interval for large DAGs (spec exec §7)"),
    ("anchor_batch_max_size",      1000.0, "integer", "Max events per anchor batch"),
    ("anchor_large_dag_threshold", 100.0, "integer", "Node count above which tau_anchor_large applies"),
```

- [ ] **Step 2.3: Schema test + commit**

Add to `test/observatory/test_schema_bundle3.py`:

```python
"""Bundle 3 schema additions."""
import sqlite3
from pathlib import Path

import pytest

from oasis.observatory.schema import create_observatory_tables


def test_on_chain_anchor_table_present(tmp_path):
    p = tmp_path / "obs.db"
    create_observatory_tables(str(p))
    conn = sqlite3.connect(str(p))
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    assert "on_chain_anchor" in tables


def test_event_log_has_anchor_id_column(tmp_path):
    p = tmp_path / "obs.db"
    create_observatory_tables(str(p))
    conn = sqlite3.connect(str(p))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(event_log)")}
    assert "anchor_id" in cols
```

Run: `pytest test/observatory/test_schema_bundle3.py -v`
Expected: 2 passed.

```bash
git add oasis/observatory/schema.py oasis/governance/schema.py test/observatory/test_schema_bundle3.py
git commit -m "feat(observatory): on_chain_anchor table + event_log.anchor_id (Bundle 3 schema)"
```

---

## Task 3: `oasis/adjudication/anchor_publisher.py` (TDD)

**Files:**

- Create: `oasis/adjudication/anchor_publisher.py`
- Create: `test/adjudication/test_anchor_publisher.py`
- Create: `test/spec_v097/test_exe_088_tau_anchor.py`
- Create: `test/spec_v097/test_exe_089_merkle_off_on_chain.py`

- [ ] **Step 3.1: Write failing tests**

Create `test/adjudication/test_anchor_publisher.py`:

```python
"""anchor_publisher commits one Merkle root per τ_anchor interval over
un-anchored event_log rows."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from oasis.adjudication.anchor_publisher import publish_anchor
from oasis.observatory.schema import create_observatory_tables


@pytest.fixture
def obs_db(tmp_path):
    p = tmp_path / "obs.db"
    create_observatory_tables(str(p))
    return str(p)


def _seed_events(db: str, n: int, anchored: bool = False):
    conn = sqlite3.connect(db)
    for i in range(n):
        anchor_id = f"anchor-old-{i}" if anchored else None
        conn.execute(
            "INSERT INTO event_log "
            "(event_id, event_type, timestamp, payload, sequence_number, anchor_id) "
            "VALUES (?, 'TEST', ?, ?, ?, ?)",
            (f"e{i}", float(i), json.dumps({"i": i}), i + 1, anchor_id),
        )
    conn.commit()
    conn.close()


def test_publish_anchor_with_no_pending_events_is_noop(obs_db):
    result = publish_anchor(db_path=obs_db, batch_max_size=1000)
    assert result is None  # nothing to anchor


def test_publish_anchor_creates_one_row(obs_db):
    _seed_events(obs_db, n=50)
    anchor = publish_anchor(db_path=obs_db, batch_max_size=1000)
    assert anchor is not None
    assert anchor["event_count"] == 50
    assert anchor["batch_start_seq"] == 1
    assert anchor["batch_end_seq"] == 50

    conn = sqlite3.connect(obs_db)
    rows = conn.execute("SELECT * FROM on_chain_anchor").fetchall()
    assert len(rows) == 1


def test_publish_anchor_marks_event_rows(obs_db):
    _seed_events(obs_db, n=50)
    anchor = publish_anchor(db_path=obs_db, batch_max_size=1000)
    conn = sqlite3.connect(obs_db)
    cnt = conn.execute(
        "SELECT COUNT(*) FROM event_log WHERE anchor_id = ?",
        (anchor["anchor_id"],),
    ).fetchone()[0]
    assert cnt == 50


def test_publish_anchor_respects_batch_max_size(obs_db):
    _seed_events(obs_db, n=2500)
    anchor = publish_anchor(db_path=obs_db, batch_max_size=1000)
    assert anchor["event_count"] == 1000
    assert anchor["batch_end_seq"] == 1000
    # Second call picks up the remaining
    anchor2 = publish_anchor(db_path=obs_db, batch_max_size=1000)
    assert anchor2["event_count"] == 1000
    assert anchor2["batch_start_seq"] == 1001
    anchor3 = publish_anchor(db_path=obs_db, batch_max_size=1000)
    assert anchor3["event_count"] == 500
    assert anchor3["batch_start_seq"] == 2001
    assert anchor3["batch_end_seq"] == 2500
```

Create `test/spec_v097/test_exe_088_tau_anchor.py`:

```python
"""Spec exec §7: τ_anchor default 10s (small DAGs) / 60s (large DAGs).
Constitutional parameter."""
import sqlite3
from pathlib import Path

import pytest

from oasis.governance.schema import create_governance_tables, seed_constitution


def test_tau_anchor_small_seeded_to_10(tmp_path):
    p = tmp_path / "g.db"
    create_governance_tables(str(p))
    seed_constitution(str(p))
    conn = sqlite3.connect(str(p))
    row = conn.execute(
        "SELECT param_value FROM constitution "
        "WHERE param_name = 'tau_anchor_small_seconds'"
    ).fetchone()
    assert row[0] == 10.0


def test_tau_anchor_large_seeded_to_60(tmp_path):
    p = tmp_path / "g.db"
    create_governance_tables(str(p))
    seed_constitution(str(p))
    conn = sqlite3.connect(str(p))
    row = conn.execute(
        "SELECT param_value FROM constitution "
        "WHERE param_name = 'tau_anchor_large_seconds'"
    ).fetchone()
    assert row[0] == 60.0
```

Create `test/spec_v097/test_exe_089_merkle_off_on_chain.py`:

```python
"""Spec exec §7, §9: off-chain logs anchored to on-chain Merkle roots
at checkpoint boundaries. Anchor must cover sequence ranges
contiguously with no gaps."""
import json
import sqlite3
from pathlib import Path

import pytest

from oasis.adjudication.anchor_publisher import publish_anchor
from oasis.crypto import merkle
from oasis.observatory.schema import create_observatory_tables


@pytest.fixture
def obs_db(tmp_path):
    p = tmp_path / "obs.db"
    create_observatory_tables(str(p))
    return str(p)


def test_anchor_merkle_root_matches_recomputation(obs_db):
    """The persisted root MUST equal SHA-256 Merkle over the anchored events
    in sequence order."""
    conn = sqlite3.connect(obs_db)
    events = []
    for i in range(8):
        payload = json.dumps({"i": i}, sort_keys=True)
        conn.execute(
            "INSERT INTO event_log "
            "(event_id, event_type, timestamp, payload, sequence_number) "
            "VALUES (?, 'TEST', ?, ?, ?)",
            (f"e{i}", float(i), payload, i + 1),
        )
        events.append(payload)
    conn.commit()
    conn.close()

    anchor = publish_anchor(db_path=obs_db, batch_max_size=1000)
    leaves = [e.encode() for e in events]
    expected_root = merkle.build_root(leaves)
    assert anchor["merkle_root_hex"] == expected_root.hex()


def test_consecutive_anchors_have_no_seq_gap(obs_db):
    conn = sqlite3.connect(obs_db)
    for i in range(2500):
        conn.execute(
            "INSERT INTO event_log "
            "(event_id, event_type, timestamp, payload, sequence_number) "
            "VALUES (?, 'TEST', ?, ?, ?)",
            (f"e{i}", float(i), '{}', i + 1),
        )
    conn.commit()
    conn.close()

    a1 = publish_anchor(db_path=obs_db, batch_max_size=1000)
    a2 = publish_anchor(db_path=obs_db, batch_max_size=1000)
    a3 = publish_anchor(db_path=obs_db, batch_max_size=1000)
    assert a1["batch_end_seq"] + 1 == a2["batch_start_seq"]
    assert a2["batch_end_seq"] + 1 == a3["batch_start_seq"]
```

- [ ] **Step 3.2: Implement `oasis/adjudication/anchor_publisher.py`**

```python
"""Anchor publisher: commits one Merkle root per τ_anchor interval over
un-anchored event_log rows. Spec exec §7 (hybrid security)."""
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from pathlib import Path

from oasis.crypto import merkle


log = logging.getLogger(__name__)


def publish_anchor(
    *,
    db_path: str | Path,
    batch_max_size: int = 1000,
    mission_id: str | None = None,
) -> dict | None:
    """Anchor the next batch of un-anchored events. Returns the anchor
    row as a dict, or None if there were no pending events."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT event_id, payload, sequence_number FROM event_log "
            "WHERE anchor_id IS NULL "
            "ORDER BY sequence_number ASC LIMIT ?",
            (batch_max_size,),
        ).fetchall()
        if not rows:
            return None

        # Canonical payload: JSON-stringify each event's payload, normalised
        # by sort_keys. Empty payload → '{}'.
        leaves: list[bytes] = []
        for r in rows:
            p = r["payload"] or "{}"
            try:
                obj = json.loads(p)
            except (TypeError, ValueError):
                obj = {}
            canonical = json.dumps(obj, sort_keys=True)
            leaves.append(canonical.encode())

        root = merkle.build_root(leaves)
        anchor_id = f"anchor-{uuid.uuid4().hex[:16]}"
        batch_start = rows[0]["sequence_number"]
        batch_end = rows[-1]["sequence_number"]

        conn.execute(
            "INSERT INTO on_chain_anchor "
            "(anchor_id, merkle_root_hex, batch_start_seq, batch_end_seq, "
            "event_count, mission_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (anchor_id, root.hex(), batch_start, batch_end, len(rows), mission_id),
        )
        event_ids = [r["event_id"] for r in rows]
        placeholders = ",".join("?" for _ in event_ids)
        conn.execute(
            f"UPDATE event_log SET anchor_id = ? "
            f"WHERE event_id IN ({placeholders})",
            (anchor_id, *event_ids),
        )
        conn.commit()
        log.info("anchored %d events as %s (root=%s)",
                  len(rows), anchor_id, root.hex()[:16])
        return {
            "anchor_id": anchor_id,
            "merkle_root_hex": root.hex(),
            "batch_start_seq": batch_start,
            "batch_end_seq": batch_end,
            "event_count": len(rows),
            "mission_id": mission_id,
        }
    finally:
        conn.close()
```

- [ ] **Step 3.3: Run + commit**

Run: `pytest test/adjudication/test_anchor_publisher.py test/spec_v097/test_exe_088_tau_anchor.py test/spec_v097/test_exe_089_merkle_off_on_chain.py -v`
Expected: 8 passed.

```bash
git add oasis/adjudication/anchor_publisher.py test/adjudication/test_anchor_publisher.py test/spec_v097/test_exe_088_tau_anchor.py test/spec_v097/test_exe_089_merkle_off_on_chain.py
git commit -m "feat(adjudication/anchor_publisher): Merkle-root anchoring of event_log (spec §7)"
```

---

## Task 4: `oasis/adjudication/reconciliation.py` (TDD)

**Files:**

- Create: `oasis/adjudication/reconciliation.py`
- Create: `test/adjudication/test_reconciliation.py`
- Create: `test/spec_v097/test_exe_091_reconciliation.py`

- [ ] **Step 4.1: Write failing tests**

Create `test/spec_v097/test_exe_091_reconciliation.py`:

```python
"""Spec exec §7.9: at Mission boundary, verify off-chain event_log vs
on-chain anchor rows. Divergence suspends the mission."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from oasis.adjudication.anchor_publisher import publish_anchor
from oasis.adjudication.reconciliation import reconcile_mission
from oasis.observatory.schema import create_observatory_tables


@pytest.fixture
def obs_db(tmp_path):
    p = tmp_path / "obs.db"
    create_observatory_tables(str(p))
    return str(p)


def _seed_mission_events(db: str, mission_id: str, n: int, start_seq: int = 1):
    conn = sqlite3.connect(db)
    for i in range(n):
        conn.execute(
            "INSERT INTO event_log "
            "(event_id, event_type, timestamp, payload, sequence_number, "
            "mission_id) "
            "VALUES (?, 'TEST', ?, ?, ?, ?)",
            (f"e-{mission_id}-{i}", float(i),
             json.dumps({"mission": mission_id, "i": i}, sort_keys=True),
             start_seq + i, mission_id),
        )
    conn.commit()
    conn.close()


def test_clean_mission_reconciles(obs_db):
    """Setup: insert event_log + mission_id col; create anchor; reconcile."""
    # event_log needs a mission_id column for this test; assume schema migration ran.
    _seed_mission_events(obs_db, "mission-A", n=10)
    publish_anchor(db_path=obs_db, batch_max_size=100, mission_id="mission-A")

    result = reconcile_mission(mission_id="mission-A", db_path=obs_db)
    assert result.status == "PASS"
    assert result.divergence_count == 0


def test_mission_with_unanchored_events_diverges(obs_db):
    _seed_mission_events(obs_db, "mission-B", n=10)
    publish_anchor(db_path=obs_db, batch_max_size=5, mission_id="mission-B")
    # Now 5 anchored + 5 unanchored

    result = reconcile_mission(mission_id="mission-B", db_path=obs_db)
    assert result.status == "DIVERGED"
    assert result.divergence_count == 5


def test_mission_with_tampered_payload_diverges(obs_db):
    _seed_mission_events(obs_db, "mission-C", n=5)
    anchor = publish_anchor(db_path=obs_db, batch_max_size=100,
                             mission_id="mission-C")

    # Tamper with one event payload AFTER anchoring
    conn = sqlite3.connect(obs_db)
    conn.execute(
        "UPDATE event_log SET payload = ? WHERE event_id = 'e-mission-C-2'",
        ('{"tampered": true}',),
    )
    conn.commit()
    conn.close()

    result = reconcile_mission(mission_id="mission-C", db_path=obs_db)
    assert result.status == "DIVERGED"
    assert "merkle" in result.reason.lower() or "hash" in result.reason.lower()
```

- [ ] **Step 4.2: Add `mission_id` to event_log schema**

In `oasis/observatory/schema.py` (idempotent ALTER block):

```python
        "ALTER TABLE event_log ADD COLUMN mission_id TEXT",
```

- [ ] **Step 4.3: Implement `oasis/adjudication/reconciliation.py`**

```python
"""Mission-boundary reconciliation (spec exec §7.9).

At Mission completion, compare event_log entries vs the persisted
on_chain_anchor rows. Recompute each anchor's Merkle root and verify it
matches the stored root.

Failure modes:
    1. Events with this mission_id that have no anchor_id → DIVERGED.
    2. Recomputed Merkle root for an anchor's events ≠ stored root → DIVERGED.
    3. Anchor row exists but referenced events are missing → DIVERGED.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from oasis.crypto import merkle


@dataclass
class ReconciliationResult:
    status: str               # "PASS" | "DIVERGED"
    mission_id: str
    divergence_count: int
    reason: str = ""


def reconcile_mission(
    *,
    mission_id: str,
    db_path: str | Path,
) -> ReconciliationResult:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        # 1. Any unanchored events for this mission?
        unanchored = conn.execute(
            "SELECT COUNT(*) FROM event_log "
            "WHERE mission_id = ? AND anchor_id IS NULL",
            (mission_id,),
        ).fetchone()[0]
        if unanchored:
            return ReconciliationResult(
                status="DIVERGED",
                mission_id=mission_id,
                divergence_count=unanchored,
                reason=f"{unanchored} unanchored events for mission {mission_id}",
            )

        # 2. For each anchor row referencing this mission, recompute Merkle.
        anchors = conn.execute(
            "SELECT anchor_id, merkle_root_hex, batch_start_seq, "
            "batch_end_seq FROM on_chain_anchor "
            "WHERE mission_id = ?",
            (mission_id,),
        ).fetchall()
        total_divergence = 0
        last_reason = ""
        for anchor in anchors:
            events = conn.execute(
                "SELECT payload FROM event_log "
                "WHERE anchor_id = ? "
                "ORDER BY sequence_number ASC",
                (anchor["anchor_id"],),
            ).fetchall()
            leaves = []
            for e in events:
                p = e["payload"] or "{}"
                try:
                    obj = json.loads(p)
                except (TypeError, ValueError):
                    obj = {}
                leaves.append(json.dumps(obj, sort_keys=True).encode())
            computed = merkle.build_root(leaves).hex()
            if computed != anchor["merkle_root_hex"]:
                total_divergence += 1
                last_reason = (
                    f"anchor {anchor['anchor_id']}: "
                    f"merkle mismatch (computed {computed[:16]}... vs "
                    f"stored {anchor['merkle_root_hex'][:16]}...)"
                )

        if total_divergence:
            return ReconciliationResult(
                status="DIVERGED",
                mission_id=mission_id,
                divergence_count=total_divergence,
                reason=last_reason,
            )

        return ReconciliationResult(
            status="PASS",
            mission_id=mission_id,
            divergence_count=0,
        )
    finally:
        conn.close()
```

- [ ] **Step 4.4: Run + commit**

Run: `pytest test/adjudication/test_reconciliation.py test/spec_v097/test_exe_091_reconciliation.py -v`
Expected: 3 passed.

```bash
git add oasis/adjudication/reconciliation.py oasis/observatory/schema.py test/adjudication/test_reconciliation.py test/spec_v097/test_exe_091_reconciliation.py
git commit -m "feat(adjudication/reconciliation): Mission-boundary off-chain vs on-chain (spec §7.9)"
```

---

## Task 5: Scheduler — wire anchor_publisher

**Files:**

- Modify: `oasis/adjudication/scheduler.py`

- [ ] **Step 5.1: Add anchor job**

Extend `start_scheduler()` in `oasis/adjudication/scheduler.py`:

```python
    # ... existing freeze + watchdog jobs ...

    from .anchor_publisher import publish_anchor
    tau_anchor_small = int(params.get("tau_anchor_small_seconds", 10))
    batch_max = int(params.get("anchor_batch_max_size", 1000))

    def _anchor_job():
        try:
            result = publish_anchor(
                db_path=obs_db_path,    # NEW: caller passes this
                batch_max_size=batch_max,
            )
            if result:
                log.info("anchor_publisher committed %d events as %s",
                          result["event_count"], result["anchor_id"])
        except Exception:
            log.exception("anchor_publisher job failed")

    _scheduler.add_job(
        _anchor_job, "interval", seconds=tau_anchor_small,
        id="anchor_publisher", replace_existing=True,
    )
```

Update `start_scheduler` signature to accept `obs_db_path`. Update `oasis/api.py` lifespan call to pass it.

- [ ] **Step 5.2: Commit**

```bash
git add oasis/adjudication/scheduler.py oasis/api.py
git commit -m "feat(scheduler): anchor_publisher job at tau_anchor interval"
```

---

## Task 6: SP-hybrid invariant test (spec_v097)

**Files:**

- Create: `test/spec_v097/test_inv_140_sp_hybrid_invariants.py`

- [ ] **Step 6.1: Write the test**

```python
"""Spec exec §9.2-9.3: SP-1h–SP-4h hybrid mode invariants. Damage bound
N_unaudited = r × τ_anchor (events per sec × checkpoint interval)."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest

from oasis.adjudication.anchor_publisher import publish_anchor
from oasis.observatory.schema import create_observatory_tables


@pytest.fixture
def obs_db(tmp_path):
    p = tmp_path / "obs.db"
    create_observatory_tables(str(p))
    return str(p)


def test_unanchored_window_bounded_by_tau_anchor(obs_db):
    """At rate r=100 ev/sec and τ_anchor=10s, the unaudited window
    must contain at most 1000 events."""
    conn = sqlite3.connect(obs_db)
    # Simulate 100 ev/sec for 10 seconds
    for i in range(1000):
        conn.execute(
            "INSERT INTO event_log "
            "(event_id, event_type, timestamp, payload, sequence_number) "
            "VALUES (?, 'TEST', ?, '{}', ?)",
            (f"e{i}", float(i) / 100.0, i + 1),
        )
    conn.commit()
    conn.close()

    # Anchor with max batch = 1000 (matches τ_anchor * r)
    anchor = publish_anchor(db_path=obs_db, batch_max_size=1000)
    assert anchor["event_count"] == 1000

    conn = sqlite3.connect(obs_db)
    remaining_unanchored = conn.execute(
        "SELECT COUNT(*) FROM event_log WHERE anchor_id IS NULL"
    ).fetchone()[0]
    assert remaining_unanchored == 0, (
        f"hybrid-mode damage bound violated: {remaining_unanchored} "
        f"events unanchored after τ_anchor interval"
    )
```

Run + commit:

```bash
pytest test/spec_v097/test_inv_140_sp_hybrid_invariants.py -v
git add test/spec_v097/test_inv_140_sp_hybrid_invariants.py
git commit -m "test(spec_v097): SP-hybrid invariant — N_unaudited bound"
```

---

## Task 7: E2E waypoint + version bump + CHANGELOG

- [ ] **Step 7.1: Append Bundle-3 E2E waypoint**

Append to `test/e2e/test_full_protocol_smoke.py`:

```python
def test_bundle3_anchoring_and_reconciliation(tmp_path):
    """End-to-end: emit 100 events into a mission, anchor them, run
    reconciliation. Then tamper one event and re-run; expect DIVERGED."""
    from oasis.adjudication.anchor_publisher import publish_anchor
    from oasis.adjudication.reconciliation import reconcile_mission
    from oasis.observatory.schema import create_observatory_tables
    import sqlite3, json

    obs_db = tmp_path / "obs.db"
    create_observatory_tables(str(obs_db))

    # Emit 100 mission events
    conn = sqlite3.connect(str(obs_db))
    for i in range(100):
        conn.execute(
            "INSERT INTO event_log "
            "(event_id, event_type, timestamp, payload, sequence_number, mission_id) "
            "VALUES (?, 'TASK', ?, ?, ?, 'mission-smoke')",
            (f"e{i}", float(i),
             json.dumps({"i": i}, sort_keys=True), i + 1),
        )
    conn.commit()
    conn.close()

    anchor = publish_anchor(db_path=str(obs_db), batch_max_size=1000,
                             mission_id="mission-smoke")
    assert anchor["event_count"] == 100

    result = reconcile_mission(mission_id="mission-smoke", db_path=str(obs_db))
    assert result.status == "PASS"

    # Tamper
    conn = sqlite3.connect(str(obs_db))
    conn.execute(
        "UPDATE event_log SET payload = '{\"tampered\": 1}' "
        "WHERE event_id = 'e42'"
    )
    conn.commit()
    conn.close()

    result2 = reconcile_mission(mission_id="mission-smoke", db_path=str(obs_db))
    assert result2.status == "DIVERGED"
```

- [ ] **Step 7.2: Version bump + CHANGELOG**

`pyproject.toml`: `0.5.0` → `0.6.0`. `typed_data.py` DOMAIN version → `0.6.0`.

Prepend to `CHANGELOG.md`:

```markdown
## [0.6.0] — TBD — Bundle 3 (Hybrid Security)

### Added

- **Merkle anchoring** (spec exec §7): pure-Python balanced-binary
  Merkle tree at `oasis/crypto/merkle.py`. Background apscheduler job
  every τ_anchor seconds (default 10s small DAGs / 60s large) commits
  one root + sequence range to `on_chain_anchor`.
- **Mission-boundary reconciliation** (spec exec §7.9):
  `reconcile_mission()` recomputes each anchor's Merkle root from the
  current event_log payloads and compares against the stored root.
  Divergence → DIVERGED status; caller suspends mission.
- New table: `on_chain_anchor`. New `event_log.anchor_id` and
  `event_log.mission_id` columns.
- New constitution params: `tau_anchor_small_seconds`,
  `tau_anchor_large_seconds`, `anchor_batch_max_size`,
  `anchor_large_dag_threshold`.
- New spec_v097 tests: EXE-088, EXE-089, EXE-091, INV-140 (SP-hybrid).
```

- [ ] **Step 7.3: Run full suite + commit**

```bash
pytest -q
git add pyproject.toml CHANGELOG.md oasis/crypto/typed_data.py test/e2e/test_full_protocol_smoke.py
git commit -m "chore(release): v0.6.0 — Bundle 3 (Hybrid Security)"
```

---

## Acceptance Gates

- [ ] All prior tests pass; ≥4 new spec_v097 tests pass; ≥6 Merkle unit tests pass.
- [ ] `on_chain_anchor` + `event_log.anchor_id` + `event_log.mission_id` migrations applied idempotently.
- [ ] apscheduler `anchor_publisher` job registered at τ_anchor_small interval.
- [ ] Codex outside-voice review on the bundle's diff returns no new findings beyond spec.

## Bundle 3 → Bundle 4 handoff

Bundle 4 depends on:

- `event_log.mission_id` column (Bundle 3 creates it).
- `on_chain_anchor` exists.
- The E2E test has Bundle-3 waypoint to extend.

Bundle 4 will emit task-level events into `event_log` with `mission_id` set; the existing anchor_publisher and reconciliation hooks will continue to work.
