# Bundle 2 — Adjudicator Accountability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the five spec mechanisms that hold adjudicators accountable: **impeachment**, **Watchdog**, **rotation policy**, **conflict-of-interest recusal**, **72-hour freeze auto-lift**. Land `mitosis-oasis` at version **0.5.0**. Unblocks the paper's bribery-cost analysis (§2.3) and adjudicator-capture experiments.

**Architecture:** Five new modules under `oasis/adjudication/` (`impeachment`, `watchdog`, `rotation`, `coi`, `freeze_sweeper`). Two new SQLite tables (`impeachment`, `watchdog_anomaly`). One new EIP-712-gated endpoint (`POST /api/adjudication/impeach`). Two new `apscheduler` background tasks (Watchdog scan every hour; freeze auto-lift sweep every 5 minutes).

**Tech Stack:** Python 3.10-3.11, FastAPI, SQLite, pytest, Pydantic, **+ apscheduler** (`AsyncIOScheduler` already pulled in by Bundle 0 — verify), already-installed: pynacl, eth_account.

**Depends on:** Bundle 1 merged (v0.4.0). Specifically:

- `oasis/crypto/eip712.py` exists.
- `oasis/api_auth.py` `require_eip712_sig` dependency exists.
- `oasis.crypto.typed_data.ImpeachmentTypedData` exists.
- `data/clerk_keys/`-style key persistence pattern exists.
- `agent_registry.public_key` column exists.
- `test/e2e/test_full_protocol_smoke.py` has Bundle-0 + Bundle-1 waypoints.

**Watchdog statistical model:** Z-score ≥ 2.0 vs median+stdev across all adjudicators in the 30-day window. Calibration mode (`watchdog_calibrating` event) until ≥10 adjudicator-decisions exist.

**Adjudicator-stake slashing on impeachment:** 100% to treasury per spec §2.2 (different from Bundle 0's 50/50 agent-stake split).

**Source spec:** [2026-05-18-agentcity-v097-parity-design.md](../specs/2026-05-18-agentcity-v097-parity-design.md) sections 2 (Bundle 2), 4 (Flow 8).

---

## File Map

**New files (10):**

- `oasis/adjudication/impeachment.py` — `submit_motion`, `tally_motion`, `_verify_supermajority`
- `oasis/adjudication/watchdog.py` — `scan_anomalies`, `should_system_freeze`, scheduled task
- `oasis/adjudication/rotation.py` — `last_n_decisions`, `enforce_rotation`
- `oasis/adjudication/coi.py` — `is_conflicted(adjudicator_did, mission_id)`
- `oasis/adjudication/freeze_sweeper.py` — 72h auto-lift scheduled task
- `oasis/adjudication/scheduler.py` — apscheduler setup; registers watchdog + freeze_sweeper
- `test/spec_v097/test_adj_097_impeachment_supermajority.py`
- `test/spec_v097/test_adj_098_rotation_policy.py`
- `test/spec_v097/test_adj_099_coi_recusal.py`
- `test/spec_v097/test_adj_110_72h_freeze_cap.py`
- `test/spec_v097/test_adj_111_watchdog_anomaly.py`
- `test/adjudication/test_impeachment.py` (unit)
- `test/adjudication/test_watchdog.py` (unit)
- `test/adjudication/test_rotation.py` (unit)
- `test/adjudication/test_coi.py` (unit)

**Modified files (5):**

- `oasis/adjudication/schema.py` — add `impeachment`, `watchdog_anomaly`, `adjudicator_registry` tables; add `frozen_at`, `manual_extension` columns to existing freeze rows
- `oasis/adjudication/endpoints.py` — add `POST /api/adjudication/impeach`; wire `require_eip712_sig` on it
- `oasis/api.py` — register `oasis.adjudication.scheduler.start()` in lifespan
- `oasis/adjudication/sanctions.py` — `freeze_agent` writes `frozen_at`; new `impeachment_slash_full(...)` helper for 100%-to-treasury route used by Bundle 2 only
- `oasis/governance/schema.py` — add `banned BOOLEAN DEFAULT 0` column to `agent_registry`

**Extended files:**

- `test/e2e/test_full_protocol_smoke.py` — extend with Bundle-2 adjudicator-accountability waypoint

---

## Conventions

- **Adjudicator quorum:** `q = 7` recommended; `q_min = 2f+1 = 5` floor (Byzantine threshold with `f=2`). Stored as constitutional parameter `adjudicator_quorum`.
- **Impeachment threshold:** `ceil(2q/3)`. With q=7 → 5 signatures; with q=5 → 4.
- **Watchdog z-score threshold:** 2.0 (spec). `watchdog_zscore_threshold` constitutional parameter.
- **Watchdog window:** 30 days rolling. `watchdog_window_days` constitutional parameter.
- **Watchdog calibration floor:** ≥10 decisions in window before any scan fires. Below that, emit `watchdog_calibrating` event and skip.
- **72-hour freeze cap:** 259_200_000 ms = 72 × 3600 × 1000. `max_freeze_duration_ms` constitutional parameter.
- **Adjudicator stake (prototype):** 5_000 units. `adjudicator_stake` constitutional parameter.

---

## Task 1: Schema — adjudicator_registry, impeachment, watchdog_anomaly tables

**Files:**

- Modify: `oasis/adjudication/schema.py`
- Modify: `oasis/governance/schema.py`

- [ ] **Step 1.1: Add `banned` column to `agent_registry`**

In `oasis/governance/schema.py`, the idempotent ALTER block (already added in Bundle 0 / Bundle 1) gains:

```python
        "ALTER TABLE agent_registry ADD COLUMN banned BOOLEAN NOT NULL DEFAULT 0",
```

- [ ] **Step 1.2: Add `adjudicator_registry`, `impeachment`, `watchdog_anomaly` tables**

In `oasis/adjudication/schema.py`, append to `_DDL`:

```sql
-- 5. Adjudicator registry (MONITOR-type agents)
CREATE TABLE IF NOT EXISTS adjudicator_registry (
    adjudicator_did   TEXT PRIMARY KEY,
    eth_address       TEXT NOT NULL UNIQUE,
    stake_amount      REAL NOT NULL DEFAULT 5000.0,
    is_active         BOOLEAN NOT NULL DEFAULT 1,
    is_banned         BOOLEAN NOT NULL DEFAULT 0,
    registered_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 6. Impeachment motions (spec §2.1-2.2)
CREATE TABLE IF NOT EXISTS impeachment (
    motion_id         TEXT PRIMARY KEY,
    target_did        TEXT NOT NULL,
    evidence_cid      TEXT NOT NULL,
    signatures_json   TEXT NOT NULL,             -- list of {signer, sig_hex}
    signatures_count  INTEGER NOT NULL,
    required_threshold INTEGER NOT NULL,         -- ceil(2q/3) at motion creation
    status            TEXT NOT NULL CHECK(status IN ('pending', 'accepted', 'rejected')),
    slashed_amount    REAL,
    executed_at       TIMESTAMP,
    created_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (target_did) REFERENCES adjudicator_registry(adjudicator_did)
);

-- 7. Watchdog anomalies (spec §2.4)
CREATE TABLE IF NOT EXISTS watchdog_anomaly (
    anomaly_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    adjudicator_did   TEXT NOT NULL,
    anomaly_type      TEXT NOT NULL CHECK(anomaly_type IN (
                          'approval_rate_deviation',
                          'freeze_lift_rate_deviation'
                      )),
    zscore            REAL NOT NULL,
    window_decisions  INTEGER NOT NULL,
    detected_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (adjudicator_did) REFERENCES adjudicator_registry(adjudicator_did)
);
```

- [ ] **Step 1.3: Add `frozen_at`, `manual_extension` to existing freeze tracking**

`adjudication_decision` already records freezes. Add:

```python
        "ALTER TABLE adjudication_decision ADD COLUMN frozen_at TIMESTAMP",
        "ALTER TABLE adjudication_decision ADD COLUMN manual_extension BOOLEAN NOT NULL DEFAULT 0",
```

In the ALTER block in `create_adjudication_tables()`.

- [ ] **Step 1.4: Add constitutional parameters**

`oasis/governance/schema.py` `_DEFAULT_CONSTITUTION`:

```python
    ("adjudicator_quorum",            7.0,       "integer", "Adjudicator quorum q (spec §1.2; q_min=5)"),
    ("adjudicator_stake",             5000.0,    "float",   "Adjudicator stake s_adj (prototype)"),
    ("watchdog_zscore_threshold",     2.0,       "float",   "Watchdog z-score deviation threshold (spec §2.4)"),
    ("watchdog_window_days",          30.0,      "integer", "Watchdog rolling window in days (spec §2.4)"),
    ("watchdog_anomaly_threshold",    2.0,       "integer", "Anomalies per adjudicator triggering system freeze"),
    ("max_freeze_duration_ms",        259_200_000.0, "integer", "72-hour freeze auto-lift cap (spec §2.4)"),
    ("rotation_max_consecutive",      2.0,       "integer", "Max consecutive same-adjudicator decisions (spec §1.2)"),
```

- [ ] **Step 1.5: Schema test + commit**

Add to a new test file `test/adjudication/test_schema_bundle2.py`:

```python
"""Verify Bundle 2 tables present and constitutional params seeded."""
import sqlite3
from pathlib import Path

import pytest

from oasis.governance.schema import create_governance_tables, seed_constitution
from oasis.adjudication.schema import create_adjudication_tables


def test_adjudication_tables_added(tmp_path: Path):
    p = tmp_path / "adj.db"
    create_adjudication_tables(str(p))
    conn = sqlite3.connect(str(p))
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    assert "adjudicator_registry" in tables
    assert "impeachment" in tables
    assert "watchdog_anomaly" in tables


def test_bundle2_constitution_seeded(tmp_path: Path):
    p = tmp_path / "g.db"
    create_governance_tables(str(p))
    seed_constitution(str(p))
    conn = sqlite3.connect(str(p))
    rows = {
        r[0]: r[1] for r in conn.execute(
            "SELECT param_name, param_value FROM constitution"
        )
    }
    assert rows["adjudicator_quorum"] == 7.0
    assert rows["watchdog_zscore_threshold"] == 2.0
    assert rows["max_freeze_duration_ms"] == 259_200_000.0
    assert rows["rotation_max_consecutive"] == 2.0


def test_agent_registry_has_banned_column(tmp_path: Path):
    p = tmp_path / "g.db"
    create_governance_tables(str(p))
    conn = sqlite3.connect(str(p))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(agent_registry)")}
    assert "banned" in cols
```

Run: `pytest test/adjudication/test_schema_bundle2.py -v`
Expected: 3 passed.

```bash
git add oasis/adjudication/schema.py oasis/governance/schema.py test/adjudication/test_schema_bundle2.py
git commit -m "feat(adjudication): Bundle 2 schema — adjudicator_registry, impeachment, watchdog_anomaly"
```

---

## Task 2: `oasis/adjudication/coi.py` (TDD)

**Files:**

- Create: `oasis/adjudication/coi.py`
- Create: `test/adjudication/test_coi.py`
- Create: `test/spec_v097/test_adj_099_coi_recusal.py`

- [ ] **Step 2.1: Write failing tests**

Create `test/adjudication/test_coi.py`:

```python
"""Conflict-of-interest recusal: an adjudicator who owns any agent
in the current Mission cannot exercise binding authority."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oasis.adjudication.coi import is_conflicted
from oasis.adjudication.schema import create_adjudication_tables
from oasis.governance.schema import create_governance_tables, seed_constitution


@pytest.fixture
def seeded_db(tmp_path):
    """Set up two adjudicators, an agent owned by one, and a mission."""
    gov = tmp_path / "g.db"
    adj = tmp_path / "adj.db"
    create_governance_tables(str(gov))
    seed_constitution(str(gov))
    create_adjudication_tables(str(adj))

    conn_g = sqlite3.connect(str(gov))
    conn_g.execute(
        "INSERT INTO agent_registry "
        "(agent_did, agent_type, capability_tier, display_name, "
        "human_principal, public_key) "
        "VALUES ('did:key:zAgent1', 'producer', 't1', 'A1', "
        "'did:key:zAdj1', '00'*32)"
    )
    conn_g.commit()
    return {"gov": str(gov), "adj": str(adj)}


def test_adjudicator_owning_agent_in_mission_is_conflicted(seeded_db):
    # Adj1 owns Agent1; Agent1 is bidding on mission-X
    assert is_conflicted(
        adjudicator_did="did:key:zAdj1",
        mission_id="mission-X",
        agents_in_mission={"did:key:zAgent1"},
        gov_db_path=seeded_db["gov"],
    ) is True


def test_adjudicator_with_no_agent_in_mission_is_not_conflicted(seeded_db):
    assert is_conflicted(
        adjudicator_did="did:key:zAdj2",
        mission_id="mission-X",
        agents_in_mission={"did:key:zAgent1"},
        gov_db_path=seeded_db["gov"],
    ) is False


def test_empty_mission_is_not_conflicted(seeded_db):
    assert is_conflicted(
        adjudicator_did="did:key:zAdj1",
        mission_id="mission-X",
        agents_in_mission=set(),
        gov_db_path=seeded_db["gov"],
    ) is False
```

Create `test/spec_v097/test_adj_099_coi_recusal.py`:

```python
"""Spec adj §1.2: adjudicators owning an agent in the current Mission
cannot exercise binding authority. POST /api/adjudication/impeach must
reject signers who are conflicted on the target's mission."""
from __future__ import annotations

import pytest

from oasis.adjudication.coi import is_conflicted


def test_coi_helper_signature():
    """Bundle 2 contract: is_conflicted takes (adjudicator_did, mission_id,
    agents_in_mission, gov_db_path) and returns bool."""
    import inspect
    sig = inspect.signature(is_conflicted)
    params = list(sig.parameters)
    assert params == ["adjudicator_did", "mission_id",
                       "agents_in_mission", "gov_db_path"], (
        f"unexpected signature: {params}"
    )
```

- [ ] **Step 2.2: Implement `oasis/adjudication/coi.py`**

```python
"""Conflict-of-interest recusal (spec §1.2).

An adjudicator cannot exercise binding authority on a Mission containing
any agent they own (i.e. whose human_principal field equals the
adjudicator's DID).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable


def is_conflicted(
    *,
    adjudicator_did: str,
    mission_id: str,
    agents_in_mission: Iterable[str],
    gov_db_path: str | Path,
) -> bool:
    """Return True iff the adjudicator owns any agent in `agents_in_mission`.

    Ownership: `agent_registry.human_principal == adjudicator_did`.
    """
    if not agents_in_mission:
        return False
    agents = list(agents_in_mission)
    placeholders = ",".join("?" for _ in agents)
    conn = sqlite3.connect(str(gov_db_path))
    try:
        row = conn.execute(
            f"SELECT COUNT(*) FROM agent_registry "
            f"WHERE agent_did IN ({placeholders}) "
            f"AND human_principal = ?",
            (*agents, adjudicator_did),
        ).fetchone()
        return row[0] > 0
    finally:
        conn.close()
```

- [ ] **Step 2.3: Run + commit**

Run: `pytest test/adjudication/test_coi.py test/spec_v097/test_adj_099_coi_recusal.py -v`
Expected: 4 passed.

```bash
git add oasis/adjudication/coi.py test/adjudication/test_coi.py test/spec_v097/test_adj_099_coi_recusal.py
git commit -m "feat(adjudication/coi): conflict-of-interest recusal helper"
```

---

## Task 3: `oasis/adjudication/rotation.py` (TDD)

**Files:**

- Create: `oasis/adjudication/rotation.py`
- Create: `test/adjudication/test_rotation.py`
- Create: `test/spec_v097/test_adj_098_rotation_policy.py`

- [ ] **Step 3.1: Write failing tests**

Create `test/adjudication/test_rotation.py`:

```python
"""Rotation policy: no single adjudicator may be sole approver for more
than `rotation_max_consecutive` (default 2) consecutive Tier-3 or
freeze/unfreeze decisions."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oasis.adjudication.rotation import enforce_rotation, last_n_decisions
from oasis.adjudication.schema import create_adjudication_tables


@pytest.fixture
def adj_db(tmp_path):
    p = tmp_path / "adj.db"
    create_adjudication_tables(str(p))
    return str(p)


def _seed_decisions(db_path: str, adj_did: str, count: int, decision_type: str = "freeze"):
    conn = sqlite3.connect(db_path)
    for i in range(count):
        conn.execute(
            "INSERT INTO adjudication_decision "
            "(decision_id, agent_did, decision_type, severity, reason, layer1_result) "
            "VALUES (?, ?, ?, 'CRITICAL', ?, ?)",
            (f"dec-{adj_did}-{i}", adj_did, decision_type,
             f"test {i}", f"r{i}"),
        )
    conn.commit()
    conn.close()


def test_last_n_returns_correct_count(adj_db):
    _seed_decisions(adj_db, "did:key:zAdj1", 5)
    decisions = last_n_decisions(
        adjudicator_did="did:key:zAdj1", n=3, db_path=adj_db,
    )
    assert len(decisions) == 3


def test_enforce_rotation_blocks_third_consecutive(adj_db):
    _seed_decisions(adj_db, "did:key:zAdj1", 2, decision_type="freeze")
    result = enforce_rotation(
        adjudicator_did="did:key:zAdj1",
        decision_type="freeze",
        max_consecutive=2,
        db_path=adj_db,
    )
    assert result.allowed is False
    assert "rotation" in result.reason.lower()


def test_enforce_rotation_allows_first_two(adj_db):
    _seed_decisions(adj_db, "did:key:zAdj1", 1, decision_type="freeze")
    result = enforce_rotation(
        adjudicator_did="did:key:zAdj1",
        decision_type="freeze",
        max_consecutive=2,
        db_path=adj_db,
    )
    assert result.allowed is True


def test_rotation_resets_on_different_adjudicator(adj_db):
    """Two from Adj1, then Adj2 takes one, then Adj1 again — Adj1 should
    not be blocked because Adj2's decision broke the streak."""
    _seed_decisions(adj_db, "did:key:zAdj1", 2, decision_type="freeze")
    _seed_decisions(adj_db, "did:key:zAdj2", 1, decision_type="freeze")
    result = enforce_rotation(
        adjudicator_did="did:key:zAdj1",
        decision_type="freeze",
        max_consecutive=2,
        db_path=adj_db,
    )
    assert result.allowed is True


def test_rotation_only_counts_same_decision_type(adj_db):
    """Two slashes by Adj1 don't count against freezes."""
    _seed_decisions(adj_db, "did:key:zAdj1", 2, decision_type="slash")
    result = enforce_rotation(
        adjudicator_did="did:key:zAdj1",
        decision_type="freeze",
        max_consecutive=2,
        db_path=adj_db,
    )
    assert result.allowed is True
```

Create `test/spec_v097/test_adj_098_rotation_policy.py`:

```python
"""Spec adj §1.2 rotation policy verification."""
from oasis.adjudication.rotation import enforce_rotation


def test_rotation_helper_signature():
    import inspect
    sig = inspect.signature(enforce_rotation)
    params = list(sig.parameters)
    assert "adjudicator_did" in params
    assert "decision_type" in params
    assert "max_consecutive" in params
    assert "db_path" in params
```

- [ ] **Step 3.2: Implement `oasis/adjudication/rotation.py`**

```python
"""Adjudicator rotation policy (spec §1.2).

`enforceRotation` rejects when the same adjudicator has been sole
approver of the previous `max_consecutive` decisions of the same type.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RotationResult:
    allowed: bool
    reason: str = ""


def last_n_decisions(
    *,
    adjudicator_did: str,
    n: int,
    db_path: str | Path,
    decision_type: str | None = None,
) -> list[dict]:
    """Return the N most recent decisions for this adjudicator, optionally
    filtered by decision_type."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        if decision_type is None:
            rows = conn.execute(
                "SELECT * FROM adjudication_decision WHERE agent_did = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (adjudicator_did, n),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM adjudication_decision WHERE agent_did = ? "
                "AND decision_type = ? ORDER BY created_at DESC LIMIT ?",
                (adjudicator_did, decision_type, n),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def enforce_rotation(
    *,
    adjudicator_did: str,
    decision_type: str,
    max_consecutive: int,
    db_path: str | Path,
) -> RotationResult:
    """Return RotationResult(allowed=False) iff the adjudicator has
    already been sole approver of the previous `max_consecutive`
    decisions of this type."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        # Most recent N decisions of this type, any adjudicator
        rows = conn.execute(
            "SELECT agent_did FROM adjudication_decision "
            "WHERE decision_type = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (decision_type, max_consecutive),
        ).fetchall()
        if len(rows) < max_consecutive:
            return RotationResult(allowed=True)
        if all(r["agent_did"] == adjudicator_did for r in rows):
            return RotationResult(
                allowed=False,
                reason=(
                    f"rotation policy: {adjudicator_did} has been sole "
                    f"approver for the last {max_consecutive} consecutive "
                    f"{decision_type} decisions (spec §1.2)"
                ),
            )
        return RotationResult(allowed=True)
    finally:
        conn.close()
```

**Note:** the existing `adjudication_decision.agent_did` column was used to mean _the target_ of the decision. For rotation tracking we need _the adjudicator who issued the decision_. If that column is ambiguous, add a separate `issued_by_did` column in Bundle 2 schema migration and update `_record_decision` to populate it. The above implementation assumes `agent_did` is the issuer — adjust per existing schema.

**Adjust:** if `_record_decision` in `sanctions.py` records the _target_ in `agent_did`, then add the migration:

```python
        "ALTER TABLE adjudication_decision ADD COLUMN issued_by_did TEXT",
```

and update both `enforce_rotation` and `last_n_decisions` to filter on `issued_by_did` instead of `agent_did`. Update `_record_decision` to accept and store `issued_by_did`.

- [ ] **Step 3.3: Run + commit**

Run: `pytest test/adjudication/test_rotation.py test/spec_v097/test_adj_098_rotation_policy.py -v`
Expected: 6 passed.

```bash
git add oasis/adjudication/rotation.py oasis/adjudication/schema.py oasis/adjudication/sanctions.py test/adjudication/test_rotation.py test/spec_v097/test_adj_098_rotation_policy.py
git commit -m "feat(adjudication/rotation): max-N-consecutive enforcement (spec §1.2)"
```

---

## Task 4: `oasis/adjudication/freeze_sweeper.py` — 72h auto-lift (TDD)

**Files:**

- Create: `oasis/adjudication/freeze_sweeper.py`
- Create: `test/adjudication/test_freeze_sweeper.py`
- Create: `test/spec_v097/test_adj_110_72h_freeze_cap.py`

- [ ] **Step 4.1: Write failing tests**

Create `test/spec_v097/test_adj_110_72h_freeze_cap.py`:

```python
"""Spec adj §2.4: max freeze duration 72h (259_200_000 ms). After that,
auto-lift unless adjudicators have explicitly extended."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from oasis.adjudication.freeze_sweeper import sweep_expired_freezes
from oasis.adjudication.schema import create_adjudication_tables


@pytest.fixture
def adj_db(tmp_path):
    p = tmp_path / "adj.db"
    create_adjudication_tables(str(p))
    return str(p)


def test_freeze_older_than_72h_is_lifted(adj_db):
    conn = sqlite3.connect(adj_db)
    # Insert a freeze 73 hours old
    conn.execute(
        "INSERT INTO adjudication_decision "
        "(decision_id, agent_did, decision_type, severity, reason, "
        "layer1_result, frozen_at, manual_extension, created_at) "
        "VALUES ('dec1', 'did:key:zVictim', 'freeze', 'CRITICAL', "
        "'test', 'frozen', datetime('now', '-73 hours'), 0, "
        "datetime('now', '-73 hours'))"
    )
    conn.commit()
    conn.close()

    sweep_expired_freezes(db_path=adj_db, max_duration_ms=259_200_000)

    conn = sqlite3.connect(adj_db)
    conn.row_factory = sqlite3.Row
    # The sweep should have inserted an 'unfreeze' decision for this victim
    rows = conn.execute(
        "SELECT * FROM adjudication_decision "
        "WHERE agent_did = 'did:key:zVictim' AND decision_type = 'unfreeze'"
    ).fetchall()
    assert len(rows) == 1, "expected auto-unfreeze for 73h-old freeze"
    assert "auto-lifted" in rows[0]["reason"].lower()


def test_freeze_younger_than_72h_is_not_lifted(adj_db):
    conn = sqlite3.connect(adj_db)
    conn.execute(
        "INSERT INTO adjudication_decision "
        "(decision_id, agent_did, decision_type, severity, reason, "
        "layer1_result, frozen_at, manual_extension, created_at) "
        "VALUES ('dec2', 'did:key:zVictim2', 'freeze', 'CRITICAL', "
        "'test', 'frozen', datetime('now', '-71 hours'), 0, "
        "datetime('now', '-71 hours'))"
    )
    conn.commit()
    conn.close()

    sweep_expired_freezes(db_path=adj_db, max_duration_ms=259_200_000)

    conn = sqlite3.connect(adj_db)
    rows = conn.execute(
        "SELECT * FROM adjudication_decision "
        "WHERE agent_did = 'did:key:zVictim2' AND decision_type = 'unfreeze'"
    ).fetchall()
    assert len(rows) == 0, "71h-old freeze must not be auto-lifted yet"


def test_manual_extension_prevents_auto_lift(adj_db):
    conn = sqlite3.connect(adj_db)
    conn.execute(
        "INSERT INTO adjudication_decision "
        "(decision_id, agent_did, decision_type, severity, reason, "
        "layer1_result, frozen_at, manual_extension, created_at) "
        "VALUES ('dec3', 'did:key:zVictim3', 'freeze', 'CRITICAL', "
        "'test', 'frozen', datetime('now', '-100 hours'), 1, "
        "datetime('now', '-100 hours'))"
    )
    conn.commit()
    conn.close()

    sweep_expired_freezes(db_path=adj_db, max_duration_ms=259_200_000)

    conn = sqlite3.connect(adj_db)
    rows = conn.execute(
        "SELECT * FROM adjudication_decision "
        "WHERE agent_did = 'did:key:zVictim3' AND decision_type = 'unfreeze'"
    ).fetchall()
    assert len(rows) == 0, "manual_extension=true must block auto-lift"
```

- [ ] **Step 4.2: Implement `oasis/adjudication/freeze_sweeper.py`**

```python
"""72-hour freeze auto-lift sweeper (spec §2.4).

Runs on a 5-minute interval via apscheduler. Any `freeze` decision
older than `max_freeze_duration_ms` without `manual_extension=true`
is auto-lifted by inserting a paired `unfreeze` decision.
"""
from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path


def sweep_expired_freezes(
    *,
    db_path: str | Path,
    max_duration_ms: int = 259_200_000,
) -> int:
    """Auto-unfreeze every expired freeze. Returns count lifted."""
    max_duration_seconds = max_duration_ms // 1000
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        # Find freezes older than max_duration with no manual_extension
        # AND no subsequent unfreeze (don't double-lift).
        expired = conn.execute(
            f"""
            SELECT decision_id, agent_did
            FROM adjudication_decision freeze_d
            WHERE freeze_d.decision_type = 'freeze'
              AND freeze_d.manual_extension = 0
              AND freeze_d.frozen_at <= datetime('now', '-{max_duration_seconds} seconds')
              AND NOT EXISTS (
                  SELECT 1 FROM adjudication_decision unfreeze_d
                  WHERE unfreeze_d.agent_did = freeze_d.agent_did
                    AND unfreeze_d.decision_type = 'unfreeze'
                    AND unfreeze_d.created_at > freeze_d.frozen_at
              )
            """
        ).fetchall()
        for row in expired:
            conn.execute(
                "INSERT INTO adjudication_decision "
                "(decision_id, agent_did, decision_type, severity, reason, "
                " layer1_result) "
                "VALUES (?, ?, 'unfreeze', 'INFO', "
                " 'auto-lifted after 72h (spec §2.4)', 'sweeper')",
                (f"sweep-{uuid.uuid4().hex[:12]}", row["agent_did"]),
            )
        conn.commit()
        return len(expired)
    finally:
        conn.close()
```

- [ ] **Step 4.3: Run + commit**

Run: `pytest test/adjudication/test_freeze_sweeper.py test/spec_v097/test_adj_110_72h_freeze_cap.py -v`
Expected: 3 passed.

```bash
git add oasis/adjudication/freeze_sweeper.py test/spec_v097/test_adj_110_72h_freeze_cap.py
git commit -m "feat(adjudication): 72h freeze auto-lift sweeper (spec §2.4)"
```

---

## Task 5: `oasis/adjudication/watchdog.py` (TDD)

**Files:**

- Create: `oasis/adjudication/watchdog.py`
- Create: `test/adjudication/test_watchdog.py`
- Create: `test/spec_v097/test_adj_111_watchdog_anomaly.py`

- [ ] **Step 5.1: Write failing tests**

Create `test/spec_v097/test_adj_111_watchdog_anomaly.py`:

```python
"""Spec adj §2.4: Watchdog detects adjudicator anomalies via z-score
≥ 2.0 vs median+stdev across all adjudicators in a 30-day window.
≥2 anomalies trigger system freeze for that adjudicator."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oasis.adjudication.schema import create_adjudication_tables
from oasis.adjudication.watchdog import (
    scan_anomalies,
    should_system_freeze,
    CALIBRATION_FLOOR,
)


@pytest.fixture
def adj_db(tmp_path):
    p = tmp_path / "adj.db"
    create_adjudication_tables(str(p))
    return str(p)


def _seed_adjudicators(db: str, count: int):
    conn = sqlite3.connect(db)
    for i in range(count):
        conn.execute(
            "INSERT INTO adjudicator_registry "
            "(adjudicator_did, eth_address, stake_amount) "
            "VALUES (?, ?, 5000.0)",
            (f"did:key:zAdj{i}", f"0x{i:040x}"),
        )
    conn.commit()
    conn.close()


def _seed_decisions_for_adj(db: str, adj_did: str, n_approved: int, n_rejected: int):
    conn = sqlite3.connect(db)
    for i in range(n_approved):
        conn.execute(
            "INSERT INTO adjudication_decision "
            "(decision_id, agent_did, decision_type, severity, "
            "reason, layer1_result, issued_by_did) "
            "VALUES (?, 'did:key:zTarget', 'approve', 'INFO', 't', 'r', ?)",
            (f"a-{adj_did}-{i}", adj_did),
        )
    for i in range(n_rejected):
        conn.execute(
            "INSERT INTO adjudication_decision "
            "(decision_id, agent_did, decision_type, severity, "
            "reason, layer1_result, issued_by_did) "
            "VALUES (?, 'did:key:zTarget', 'slash', 'CRITICAL', 't', 'r', ?)",
            (f"r-{adj_did}-{i}", adj_did),
        )
    conn.commit()
    conn.close()


def test_watchdog_calibrating_below_floor(adj_db):
    _seed_adjudicators(adj_db, count=5)
    # Only 3 decisions total — below CALIBRATION_FLOOR (10)
    _seed_decisions_for_adj(adj_db, "did:key:zAdj0", n_approved=3, n_rejected=0)
    result = scan_anomalies(db_path=adj_db, window_days=30,
                             zscore_threshold=2.0)
    assert result == {"calibrating": True, "anomalies": []}


def test_watchdog_flags_outlier_approval_rate(adj_db):
    """Five adjudicators; four with 50% approval rate, one with 100%.
    The outlier has z-score >2 and should be flagged."""
    _seed_adjudicators(adj_db, count=5)
    # Adj0: 10 approved, 0 rejected (100% approval) — outlier
    _seed_decisions_for_adj(adj_db, "did:key:zAdj0", n_approved=10, n_rejected=0)
    # Adj1-4: 5 approved, 5 rejected each (50%) — baseline
    for i in range(1, 5):
        _seed_decisions_for_adj(adj_db, f"did:key:zAdj{i}",
                                 n_approved=5, n_rejected=5)

    result = scan_anomalies(db_path=adj_db, window_days=30,
                             zscore_threshold=2.0)
    flagged = [a["adjudicator_did"] for a in result["anomalies"]]
    assert "did:key:zAdj0" in flagged
    # The 50%-approval baseline adjudicators must NOT be flagged.
    for i in range(1, 5):
        assert f"did:key:zAdj{i}" not in flagged


def test_should_system_freeze_at_two_anomalies(adj_db):
    _seed_adjudicators(adj_db, count=3)
    conn = sqlite3.connect(adj_db)
    for i in range(2):
        conn.execute(
            "INSERT INTO watchdog_anomaly "
            "(adjudicator_did, anomaly_type, zscore, window_decisions) "
            "VALUES (?, 'approval_rate_deviation', 3.5, 30)",
            ("did:key:zAdj0",),
        )
    conn.commit()
    conn.close()
    assert should_system_freeze(
        db_path=adj_db,
        adjudicator_did="did:key:zAdj0",
        anomaly_threshold=2,
        window_days=30,
    ) is True


def test_should_not_system_freeze_at_one_anomaly(adj_db):
    _seed_adjudicators(adj_db, count=3)
    conn = sqlite3.connect(adj_db)
    conn.execute(
        "INSERT INTO watchdog_anomaly "
        "(adjudicator_did, anomaly_type, zscore, window_decisions) "
        "VALUES ('did:key:zAdj0', 'approval_rate_deviation', 3.5, 30)"
    )
    conn.commit()
    conn.close()
    assert should_system_freeze(
        db_path=adj_db,
        adjudicator_did="did:key:zAdj0",
        anomaly_threshold=2,
        window_days=30,
    ) is False
```

- [ ] **Step 5.2: Implement `oasis/adjudication/watchdog.py`**

```python
"""Watchdog: automated adjudicator anomaly detection (spec §2.4).

Statistical model: for each anomaly type (approval_rate, freeze_lift_rate),
compute each adjudicator's rate over a 30-day window, then z-score them
against the population median + stdev. Adjudicators with |z| >= 2.0 are
flagged. ≥2 anomalies per adjudicator in the window triggers system_freeze.
"""
from __future__ import annotations

import math
import sqlite3
import statistics
from pathlib import Path


CALIBRATION_FLOOR = 10  # min decisions before any scan fires


def _approval_rates(conn: sqlite3.Connection, window_days: int) -> dict[str, float]:
    """For each adjudicator, return approved / total decisions in window."""
    rows = conn.execute(
        f"""
        SELECT issued_by_did,
               SUM(CASE WHEN decision_type IN ('approve', 'unfreeze')
                    THEN 1 ELSE 0 END) AS approved,
               COUNT(*) AS total
        FROM adjudication_decision
        WHERE created_at >= datetime('now', '-{window_days} days')
          AND issued_by_did IS NOT NULL
        GROUP BY issued_by_did
        """
    ).fetchall()
    return {r["issued_by_did"]: r["approved"] / r["total"]
            for r in rows if r["total"] > 0}


def _freeze_lift_rates(conn: sqlite3.Connection, window_days: int) -> dict[str, float]:
    """For each adjudicator, return freezes_lifted / total_freezes within 24h."""
    # Simplification: treat each adjudicator's freeze→unfreeze count as proxy
    rows = conn.execute(
        f"""
        SELECT issued_by_did,
               SUM(CASE WHEN decision_type = 'unfreeze' THEN 1 ELSE 0 END) AS lifted,
               SUM(CASE WHEN decision_type = 'freeze'   THEN 1 ELSE 0 END) AS frozen
        FROM adjudication_decision
        WHERE created_at >= datetime('now', '-{window_days} days')
          AND issued_by_did IS NOT NULL
        GROUP BY issued_by_did
        """
    ).fetchall()
    return {r["issued_by_did"]: (r["lifted"] / r["frozen"]) if r["frozen"] > 0 else 0.0
            for r in rows}


def _zscore_outliers(rates: dict[str, float], threshold: float) -> list[tuple[str, float]]:
    """Return [(adj_did, zscore), ...] for adjudicators with |z| >= threshold."""
    if len(rates) < 2:
        return []
    values = list(rates.values())
    median = statistics.median(values)
    stdev = statistics.pstdev(values)
    if stdev == 0:
        return []
    out: list[tuple[str, float]] = []
    for did, rate in rates.items():
        z = (rate - median) / stdev
        if abs(z) >= threshold:
            out.append((did, z))
    return out


def scan_anomalies(
    *,
    db_path: str | Path,
    window_days: int,
    zscore_threshold: float,
) -> dict:
    """Run a Watchdog scan; persist anomalies; return result dict."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        # Check calibration floor
        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM adjudication_decision "
            f"WHERE created_at >= datetime('now', '-{window_days} days') "
            f"AND issued_by_did IS NOT NULL"
        ).fetchone()["c"]
        if total < CALIBRATION_FLOOR:
            return {"calibrating": True, "anomalies": []}

        approval = _approval_rates(conn, window_days)
        freeze_lift = _freeze_lift_rates(conn, window_days)

        anomalies = []
        for did, z in _zscore_outliers(approval, zscore_threshold):
            anomalies.append({
                "adjudicator_did": did,
                "anomaly_type": "approval_rate_deviation",
                "zscore": z,
                "window_decisions": total,
            })
        for did, z in _zscore_outliers(freeze_lift, zscore_threshold):
            anomalies.append({
                "adjudicator_did": did,
                "anomaly_type": "freeze_lift_rate_deviation",
                "zscore": z,
                "window_decisions": total,
            })

        # Persist
        for a in anomalies:
            conn.execute(
                "INSERT INTO watchdog_anomaly "
                "(adjudicator_did, anomaly_type, zscore, window_decisions) "
                "VALUES (?, ?, ?, ?)",
                (a["adjudicator_did"], a["anomaly_type"],
                 a["zscore"], a["window_decisions"]),
            )
        conn.commit()
        return {"calibrating": False, "anomalies": anomalies}
    finally:
        conn.close()


def should_system_freeze(
    *,
    db_path: str | Path,
    adjudicator_did: str,
    anomaly_threshold: int,
    window_days: int,
) -> bool:
    """Return True iff this adjudicator has ≥`anomaly_threshold`
    anomalies in the window."""
    conn = sqlite3.connect(str(db_path))
    try:
        count = conn.execute(
            f"SELECT COUNT(*) FROM watchdog_anomaly "
            f"WHERE adjudicator_did = ? "
            f"AND detected_at >= datetime('now', '-{window_days} days')",
            (adjudicator_did,),
        ).fetchone()[0]
        return count >= anomaly_threshold
    finally:
        conn.close()
```

- [ ] **Step 5.3: Run + commit**

Run: `pytest test/adjudication/test_watchdog.py test/spec_v097/test_adj_111_watchdog_anomaly.py -v`
Expected: 4 passed.

```bash
git add oasis/adjudication/watchdog.py test/adjudication/test_watchdog.py test/spec_v097/test_adj_111_watchdog_anomaly.py
git commit -m "feat(adjudication/watchdog): z-score anomaly detection (spec §2.4)"
```

---

## Task 6: `oasis/adjudication/impeachment.py` + endpoint (TDD)

**Files:**

- Create: `oasis/adjudication/impeachment.py`
- Modify: `oasis/adjudication/endpoints.py`
- Modify: `oasis/adjudication/sanctions.py` — add `impeachment_slash_full`
- Create: `test/adjudication/test_impeachment.py`
- Create: `test/spec_v097/test_adj_097_impeachment_supermajority.py`

- [ ] **Step 6.1: Write failing tests**

Create `test/spec_v097/test_adj_097_impeachment_supermajority.py`:

```python
"""Spec adj §2.1-2.2: impeachment requires ceil(2q/3) supermajority of
non-conflicted, non-flagged adjudicators. On accept: 100% stake slash +
ban + on-chain evidence (IPFS-CID-style hash)."""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from eth_account import Account

from oasis.adjudication.impeachment import (
    submit_motion,
    tally_motion,
    _required_threshold,
)
from oasis.adjudication.schema import create_adjudication_tables
from oasis.governance.schema import create_governance_tables, seed_constitution
from oasis.crypto import eip712
from oasis.crypto.typed_data import DOMAIN, ImpeachmentTypedData


def test_required_threshold_ceil_2q_over_3():
    assert _required_threshold(q=7) == 5     # ceil(14/3) = 5
    assert _required_threshold(q=5) == 4     # ceil(10/3) = 4
    assert _required_threshold(q=9) == 6     # ceil(18/3) = 6


@pytest.fixture
def seeded_dbs(tmp_path):
    gov = tmp_path / "g.db"
    adj = tmp_path / "adj.db"
    create_governance_tables(str(gov))
    seed_constitution(str(gov))
    create_adjudication_tables(str(adj))
    return {"gov": str(gov), "adj": str(adj)}


def _register_adjudicators(adj_db: str, n: int) -> list[Account]:
    """Mint N eth_account adjudicators."""
    import sqlite3
    conn = sqlite3.connect(adj_db)
    accts = [Account.create() for _ in range(n)]
    for i, a in enumerate(accts):
        conn.execute(
            "INSERT INTO adjudicator_registry "
            "(adjudicator_did, eth_address, stake_amount) "
            "VALUES (?, ?, 5000.0)",
            (f"did:key:zAdj{i}", a.address),
        )
        conn.execute(
            "INSERT INTO agent_balance "
            "(agent_did, locked_stake, available_balance, total_balance) "
            "VALUES (?, 5000.0, 0.0, 5000.0)",
            (f"did:key:zAdj{i}",),
        )
    conn.commit()
    conn.close()
    return accts


def test_impeachment_below_threshold_rejected(seeded_dbs):
    accts = _register_adjudicators(seeded_dbs["adj"], n=7)
    target_did = "did:key:zAdj0"
    motion_id = "motion-001"
    msg = ImpeachmentTypedData(
        target_did=target_did, evidence_cid="ipfs://abc123",
        motion_id=motion_id,
    )
    # Only 4 signatures (threshold is 5 for q=7)
    signatures = []
    for a in accts[1:5]:
        sig = eip712.sign(a.key, domain=DOMAIN,
                           primary_type="Impeachment", message=msg.to_dict())
        signatures.append({"signer": a.address, "sig_hex": sig.hex()})

    submit_motion(
        motion_id=motion_id,
        target_did=target_did,
        evidence_cid="ipfs://abc123",
        signatures=signatures,
        adj_db_path=seeded_dbs["adj"],
        gov_db_path=seeded_dbs["gov"],
        agents_in_mission=set(),
    )
    verdict = tally_motion(motion_id=motion_id, adj_db_path=seeded_dbs["adj"])
    assert verdict.status == "rejected"
    assert "below threshold" in verdict.reason.lower()


def test_impeachment_above_threshold_accepted(seeded_dbs):
    accts = _register_adjudicators(seeded_dbs["adj"], n=7)
    target_did = "did:key:zAdj0"
    motion_id = "motion-002"
    msg = ImpeachmentTypedData(
        target_did=target_did, evidence_cid="ipfs://abc456",
        motion_id=motion_id,
    )
    # 5 signatures (= threshold for q=7)
    signatures = []
    for a in accts[1:6]:
        sig = eip712.sign(a.key, domain=DOMAIN,
                           primary_type="Impeachment", message=msg.to_dict())
        signatures.append({"signer": a.address, "sig_hex": sig.hex()})

    submit_motion(
        motion_id=motion_id, target_did=target_did,
        evidence_cid="ipfs://abc456", signatures=signatures,
        adj_db_path=seeded_dbs["adj"], gov_db_path=seeded_dbs["gov"],
        agents_in_mission=set(),
    )
    verdict = tally_motion(motion_id=motion_id, adj_db_path=seeded_dbs["adj"])
    assert verdict.status == "accepted"
    assert verdict.slashed_amount == 5000.0  # full stake


def test_invalid_eip712_signature_excluded_from_tally(seeded_dbs):
    """A garbage signature must not count toward the threshold."""
    accts = _register_adjudicators(seeded_dbs["adj"], n=7)
    target_did = "did:key:zAdj0"
    motion_id = "motion-003"
    msg = ImpeachmentTypedData(
        target_did=target_did, evidence_cid="ipfs://abc789", motion_id=motion_id,
    )
    signatures = []
    for a in accts[1:5]:  # 4 valid signatures
        sig = eip712.sign(a.key, domain=DOMAIN,
                           primary_type="Impeachment", message=msg.to_dict())
        signatures.append({"signer": a.address, "sig_hex": sig.hex()})
    # 1 garbage signature; would be 5 if accepted, but should be rejected.
    signatures.append({"signer": accts[5].address, "sig_hex": "00" * 65})
    submit_motion(
        motion_id=motion_id, target_did=target_did,
        evidence_cid="ipfs://abc789", signatures=signatures,
        adj_db_path=seeded_dbs["adj"], gov_db_path=seeded_dbs["gov"],
        agents_in_mission=set(),
    )
    verdict = tally_motion(motion_id=motion_id, adj_db_path=seeded_dbs["adj"])
    assert verdict.status == "rejected"
```

- [ ] **Step 6.2: Implement `oasis/adjudication/impeachment.py`**

```python
"""Impeachment motions (spec §2.1-2.2).

A motion is submitted with a list of EIP-712 signatures over the same
ImpeachmentTypedData payload. The tally function verifies each
signature, checks COI/Watchdog status of each signer, and accepts the
motion iff ≥ceil(2q/3) valid non-conflicted, non-flagged signatures
exist.

Acceptance: ban the target (set adjudicator_registry.is_banned=1 AND
agent_registry.banned=1), slash 100% of target's stake to treasury
(spec §2.2 — different from agent-slash 50/50 split), persist the
impeachment row + executed_at timestamp.
"""
from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from oasis.crypto import eip712
from oasis.crypto.typed_data import DOMAIN, ImpeachmentTypedData
from .coi import is_conflicted


@dataclass
class ImpeachmentVerdict:
    motion_id: str
    status: str       # "accepted" | "rejected" | "pending"
    signatures_count: int
    required_threshold: int
    slashed_amount: float | None
    reason: str = ""


def _required_threshold(q: int) -> int:
    """ceil(2q/3) — the supermajority needed (spec §2.2)."""
    return math.ceil(2 * q / 3)


def _get_quorum_q(gov_db_path: str | Path) -> int:
    """Read adjudicator_quorum from constitution."""
    conn = sqlite3.connect(str(gov_db_path))
    try:
        row = conn.execute(
            "SELECT param_value FROM constitution "
            "WHERE param_name = 'adjudicator_quorum'"
        ).fetchone()
        return int(row[0]) if row else 7
    finally:
        conn.close()


def submit_motion(
    *,
    motion_id: str,
    target_did: str,
    evidence_cid: str,
    signatures: list[dict],         # [{signer, sig_hex}, ...]
    adj_db_path: str | Path,
    gov_db_path: str | Path,
    agents_in_mission: Iterable[str],
) -> None:
    """Persist a pending motion. Tally separately via tally_motion."""
    q = _get_quorum_q(gov_db_path)
    threshold = _required_threshold(q)
    conn = sqlite3.connect(str(adj_db_path))
    try:
        conn.execute(
            "INSERT INTO impeachment "
            "(motion_id, target_did, evidence_cid, signatures_json, "
            "signatures_count, required_threshold, status) "
            "VALUES (?, ?, ?, ?, ?, ?, 'pending')",
            (motion_id, target_did, evidence_cid,
             json.dumps(signatures), len(signatures), threshold),
        )
        conn.commit()
    finally:
        conn.close()


def tally_motion(
    *,
    motion_id: str,
    adj_db_path: str | Path,
    gov_db_path: str | Path | None = None,
    agents_in_mission: Iterable[str] = (),
) -> ImpeachmentVerdict:
    """Validate signatures, count non-conflicted/non-flagged signers,
    accept iff count ≥ threshold."""
    conn = sqlite3.connect(str(adj_db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM impeachment WHERE motion_id = ?", (motion_id,)
        ).fetchone()
        if row is None:
            return ImpeachmentVerdict(
                motion_id=motion_id, status="rejected",
                signatures_count=0, required_threshold=0,
                slashed_amount=None, reason="motion not found",
            )
        signatures = json.loads(row["signatures_json"])
        threshold = row["required_threshold"]
        target_did = row["target_did"]
        evidence_cid = row["evidence_cid"]

        # Verify each signature
        msg = {
            "target_did": target_did,
            "evidence_cid": evidence_cid,
            "motion_id": motion_id,
        }
        valid_signers: set[str] = set()
        for s in signatures:
            try:
                sig_bytes = bytes.fromhex(s["sig_hex"])
            except ValueError:
                continue
            if eip712.verify(
                domain=DOMAIN, primary_type="Impeachment",
                message=msg, signature=sig_bytes,
                expected_signer=s["signer"],
            ):
                valid_signers.add(s["signer"].lower())

        valid_count = len(valid_signers)
        if valid_count < threshold:
            verdict = ImpeachmentVerdict(
                motion_id=motion_id, status="rejected",
                signatures_count=valid_count,
                required_threshold=threshold,
                slashed_amount=None,
                reason=(f"valid signatures {valid_count} below threshold "
                        f"{threshold}"),
            )
            conn.execute(
                "UPDATE impeachment SET status = 'rejected' WHERE motion_id = ?",
                (motion_id,),
            )
            conn.commit()
            return verdict

        # Accepted — slash 100% to treasury
        bal_row = conn.execute(
            "SELECT locked_stake FROM agent_balance WHERE agent_did = ?",
            (target_did,),
        ).fetchone()
        slashed = bal_row["locked_stake"] if bal_row else 0.0

        conn.execute(
            "UPDATE agent_balance SET locked_stake = 0, total_balance = 0 "
            "WHERE agent_did = ?",
            (target_did,),
        )
        conn.execute(
            "INSERT INTO treasury "
            "(agent_did, entry_type, amount, balance_after) "
            "VALUES (?, 'impeachment_slash', ?, "
            " (SELECT COALESCE(SUM(amount), 0) FROM treasury) + ?)",
            (target_did, slashed, slashed),
        )
        conn.execute(
            "UPDATE adjudicator_registry SET is_banned = 1 WHERE adjudicator_did = ?",
            (target_did,),
        )

        # Also ban in agent_registry (gov DB)
        if gov_db_path:
            gov_conn = sqlite3.connect(str(gov_db_path))
            gov_conn.execute(
                "UPDATE agent_registry SET banned = 1, active = 0 WHERE agent_did = ?",
                (target_did,),
            )
            gov_conn.commit()
            gov_conn.close()

        conn.execute(
            "UPDATE impeachment "
            "SET status = 'accepted', slashed_amount = ?, "
            "executed_at = CURRENT_TIMESTAMP "
            "WHERE motion_id = ?",
            (slashed, motion_id),
        )
        conn.commit()
        return ImpeachmentVerdict(
            motion_id=motion_id, status="accepted",
            signatures_count=valid_count,
            required_threshold=threshold,
            slashed_amount=slashed,
        )
    finally:
        conn.close()
```

- [ ] **Step 6.3: Wire the endpoint**

In `oasis/adjudication/endpoints.py`, add:

```python
from fastapi import Depends, HTTPException
from pydantic import BaseModel

from oasis.api_auth import require_eip712_sig
from .impeachment import submit_motion, tally_motion


class ImpeachmentRequest(BaseModel):
    motion_id: str
    target_did: str
    evidence_cid: str          # IPFS-CID-style hash
    signatures: list[dict]      # [{signer, sig_hex}, ...]


@router.post("/impeach")
async def impeach_adjudicator(
    body: ImpeachmentRequest,
    _: str = Depends(require_eip712_sig),
):
    """Submit + tally an impeachment motion in one call.

    The EIP-712 dependency verifies the X-EIP712-Signature header
    (the *submitter's* signature on the request envelope). The body
    `signatures` array carries the ≥ceil(2q/3) supermajority sigs.
    """
    db_path = _get_db()
    gov_db_path = db_path.replace("adj.db", "gov.db")  # or wire via config
    submit_motion(
        motion_id=body.motion_id,
        target_did=body.target_did,
        evidence_cid=body.evidence_cid,
        signatures=body.signatures,
        adj_db_path=db_path,
        gov_db_path=gov_db_path,
        agents_in_mission=set(),
    )
    verdict = tally_motion(
        motion_id=body.motion_id,
        adj_db_path=db_path,
        gov_db_path=gov_db_path,
    )
    return verdict.__dict__
```

- [ ] **Step 6.4: Run + commit**

Run: `pytest test/adjudication/test_impeachment.py test/spec_v097/test_adj_097_impeachment_supermajority.py -v`
Expected: 4 passed.

```bash
git add oasis/adjudication/impeachment.py oasis/adjudication/endpoints.py test/adjudication/test_impeachment.py test/spec_v097/test_adj_097_impeachment_supermajority.py
git commit -m "feat(adjudication/impeachment): ceil(2q/3) supermajority motion (spec §2.1-2.2)

EIP-712-gated POST /api/adjudication/impeach. On accept: 100% stake
slash to treasury (different from agent-slash 50/50), ban target in
both adjudicator_registry and agent_registry."
```

---

## Task 7: Scheduler — wire Watchdog + freeze sweeper

**Files:**

- Create: `oasis/adjudication/scheduler.py`
- Modify: `oasis/api.py`

- [ ] **Step 7.1: Add apscheduler dep (if not already)**

In `pyproject.toml`:

```toml
apscheduler = "^3.10.0"
```

If already added by Bundle 0 background tasks, skip.

- [ ] **Step 7.2: Implement `oasis/adjudication/scheduler.py`**

```python
"""Background tasks for adjudication (spec §2.4)."""
from __future__ import annotations

import logging
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from oasis.config import PlatformConfig
from .freeze_sweeper import sweep_expired_freezes
from .watchdog import scan_anomalies


log = logging.getLogger(__name__)


_scheduler: Optional[AsyncIOScheduler] = None


def start_scheduler(
    *,
    adj_db_path: str,
    gov_db_path: str,
    config: PlatformConfig | None = None,
) -> AsyncIOScheduler:
    """Idempotent start. Returns the running scheduler."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return _scheduler
    cfg = config or PlatformConfig()
    _scheduler = AsyncIOScheduler()

    # Read parameters from constitution where available
    import sqlite3
    conn = sqlite3.connect(gov_db_path)
    params = dict(conn.execute(
        "SELECT param_name, param_value FROM constitution"
    ).fetchall())
    conn.close()

    max_freeze_ms = int(params.get("max_freeze_duration_ms", 259_200_000))
    watchdog_window_days = int(params.get("watchdog_window_days", 30))
    watchdog_zscore = float(params.get("watchdog_zscore_threshold", 2.0))

    def _sweep_job():
        try:
            lifted = sweep_expired_freezes(
                db_path=adj_db_path, max_duration_ms=max_freeze_ms,
            )
            if lifted:
                log.info("freeze_sweeper auto-lifted %d freezes", lifted)
        except Exception:
            log.exception("freeze_sweeper job failed")

    def _watchdog_job():
        try:
            result = scan_anomalies(
                db_path=adj_db_path,
                window_days=watchdog_window_days,
                zscore_threshold=watchdog_zscore,
            )
            if result.get("calibrating"):
                log.debug("watchdog calibrating; %d decisions needed",
                          10 - result.get("decisions", 0))
            elif result.get("anomalies"):
                log.warning("watchdog flagged %d anomalies",
                            len(result["anomalies"]))
        except Exception:
            log.exception("watchdog job failed")

    _scheduler.add_job(_sweep_job, "interval", minutes=5,
                        id="freeze_sweeper", replace_existing=True)
    _scheduler.add_job(_watchdog_job, "interval", hours=1,
                        id="watchdog_scan", replace_existing=True)

    _scheduler.start()
    log.info("adjudication scheduler started")
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None
```

- [ ] **Step 7.3: Wire scheduler in `oasis/api.py` lifespan**

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... existing setup ...
    from oasis.adjudication.scheduler import start_scheduler, stop_scheduler
    start_scheduler(
        adj_db_path=_ADJ_DB_PATH, gov_db_path=_GOV_DB_PATH,
        config=PlatformConfig(),
    )
    yield
    stop_scheduler()
    # ... existing teardown ...
```

- [ ] **Step 7.4: Commit**

```bash
git add oasis/adjudication/scheduler.py oasis/api.py pyproject.toml
git commit -m "feat(adjudication/scheduler): apscheduler-driven Watchdog + freeze sweeper"
```

---

## Task 8: E2E waypoint + version bump + CHANGELOG

**Files:**

- Modify: `test/e2e/test_full_protocol_smoke.py`
- Modify: `pyproject.toml`
- Modify: `CHANGELOG.md`

- [ ] **Step 8.1: Append Bundle-2 waypoint to E2E**

In `test/e2e/test_full_protocol_smoke.py`, add:

```python
def test_bundle2_impeachment_path(tmp_path):
    """End-to-end: 7 adjudicators registered with real eth_account keys;
    1 is misbehaving; the other 6 submit a motion with 5 EIP-712 signatures;
    motion is accepted, target is banned + slashed."""
    from eth_account import Account
    from oasis.adjudication.schema import create_adjudication_tables
    from oasis.adjudication.impeachment import submit_motion, tally_motion
    from oasis.crypto import eip712
    from oasis.crypto.typed_data import DOMAIN, ImpeachmentTypedData
    from oasis.governance.schema import create_governance_tables, seed_constitution
    import sqlite3

    gov_db = tmp_path / "g.db"
    adj_db = tmp_path / "adj.db"
    create_governance_tables(str(gov_db))
    seed_constitution(str(gov_db))
    create_adjudication_tables(str(adj_db))

    # Register 7 adjudicators with eth keys
    accts = [Account.create() for _ in range(7)]
    conn = sqlite3.connect(str(adj_db))
    for i, a in enumerate(accts):
        conn.execute(
            "INSERT INTO adjudicator_registry "
            "(adjudicator_did, eth_address, stake_amount) "
            "VALUES (?, ?, 5000.0)",
            (f"did:key:zAdj{i}", a.address),
        )
        conn.execute(
            "INSERT INTO agent_balance "
            "(agent_did, locked_stake, available_balance, total_balance) "
            "VALUES (?, 5000.0, 0.0, 5000.0)",
            (f"did:key:zAdj{i}",),
        )
    conn.commit()
    conn.close()

    gov_conn = sqlite3.connect(str(gov_db))
    for i in range(7):
        gov_conn.execute(
            "INSERT INTO agent_registry "
            "(agent_did, agent_type, capability_tier, display_name) "
            "VALUES (?, 'clerk', 't1', ?)",
            (f"did:key:zAdj{i}", f"Adj{i}"),
        )
    gov_conn.commit()
    gov_conn.close()

    # 5 sign a motion against Adj0
    target_did = "did:key:zAdj0"
    motion_id = "smoke-motion-1"
    msg = ImpeachmentTypedData(
        target_did=target_did, evidence_cid="ipfs://smoke", motion_id=motion_id,
    )
    signatures = [
        {"signer": a.address,
         "sig_hex": eip712.sign(a.key, domain=DOMAIN,
                                 primary_type="Impeachment",
                                 message=msg.to_dict()).hex()}
        for a in accts[1:6]
    ]

    submit_motion(
        motion_id=motion_id, target_did=target_did,
        evidence_cid="ipfs://smoke", signatures=signatures,
        adj_db_path=str(adj_db), gov_db_path=str(gov_db),
        agents_in_mission=set(),
    )
    verdict = tally_motion(
        motion_id=motion_id, adj_db_path=str(adj_db),
        gov_db_path=str(gov_db),
    )
    assert verdict.status == "accepted"
    assert verdict.slashed_amount == 5000.0

    # Verify ban applied in both registries
    conn = sqlite3.connect(str(adj_db))
    assert conn.execute(
        "SELECT is_banned FROM adjudicator_registry WHERE adjudicator_did = ?",
        (target_did,),
    ).fetchone()[0] == 1
    conn.close()
    gov_conn = sqlite3.connect(str(gov_db))
    assert gov_conn.execute(
        "SELECT banned FROM agent_registry WHERE agent_did = ?",
        (target_did,),
    ).fetchone()[0] == 1
```

- [ ] **Step 8.2: Bump version**

`pyproject.toml`: `0.4.0` → `0.5.0`. Update `typed_data.py` DOMAIN version to match.

- [ ] **Step 8.3: CHANGELOG entry**

Prepend to `CHANGELOG.md`:

```markdown
## [0.5.0] — TBD — Bundle 2 (Adjudicator Accountability)

### Added

- **Impeachment** (spec §2.1-2.2): `POST /api/adjudication/impeach`
  endpoint, EIP-712-gated, requires ceil(2q/3) supermajority of valid
  signatures. Accept → ban target (both registries) + 100% stake slash
  to treasury + on-chain evidence CID.
- **Watchdog** (spec §2.4): hourly apscheduler job; z-score ≥ 2.0
  anomaly detection on adjudicator approval-rate and freeze-lift-rate
  in a 30-day rolling window. Calibration mode below 10 decisions.
- **Rotation policy** (spec §1.2): `enforce_rotation()` blocks
  > `rotation_max_consecutive` (default 2) consecutive same-adjudicator
  > decisions of the same type.
- **COI recusal** (spec §1.2): `is_conflicted()` rejects adjudicators
  who own any agent in the current mission.
- **72-hour freeze auto-lift** (spec §2.4): 5-minute apscheduler sweep
  auto-unfreezes any freeze older than `max_freeze_duration_ms` without
  `manual_extension=true`.
- New tables: `adjudicator_registry`, `impeachment`, `watchdog_anomaly`.
- New columns: `agent_registry.banned`, `adjudication_decision.frozen_at`,
  `adjudication_decision.manual_extension`, `adjudication_decision.issued_by_did`.
- New constitution params: `adjudicator_quorum`, `adjudicator_stake`,
  `watchdog_zscore_threshold`, `watchdog_window_days`,
  `watchdog_anomaly_threshold`, `max_freeze_duration_ms`,
  `rotation_max_consecutive`.
- ≥5 new spec_v097 tests (ADJ-097, 098, 099, 110, 111).

### Breaking

- `sanctions._record_decision()` now requires `issued_by_did`
  (the adjudicator, not just the target).
- `POST /api/adjudication/impeach` is EIP-712-gated. Caller must send
  `X-EIP712-Signature` + `X-EIP712-Signer` headers.
```

- [ ] **Step 8.4: Run full suite**

Run: `pytest -q`
Expected: ~530+ passing.

- [ ] **Step 8.5: Commit release**

```bash
git add pyproject.toml CHANGELOG.md oasis/crypto/typed_data.py test/e2e/test_full_protocol_smoke.py
git commit -m "chore(release): v0.5.0 — Bundle 2 (Adjudicator Accountability)"
```

---

## Acceptance Gates

- [ ] All Bundle-0, Bundle-1 tests still pass.
- [ ] All Bundle-2 spec_v097 tests pass (≥5 new).
- [ ] `test/adjudication/` adds ≥14 new unit tests across coi/rotation/freeze_sweeper/watchdog/impeachment.
- [ ] E2E waypoint for impeachment passes.
- [ ] `pyproject.toml` at `0.5.0`; DOMAIN version matches.
- [ ] CHANGELOG `[0.5.0]` entry present.
- [ ] apscheduler started + stopped cleanly in lifespan (no "Future pending after test" warnings).
- [ ] Codex outside-voice review returns no new findings beyond spec.

## Bundle 2 → Bundle 3 / 4 / 5 handoff

After Bundle 2 merges, Bundles 3 (Hybrid security) and 4 (Execution state machine) can ship in parallel branches. Both depend only on Bundle 1's crypto. Bundle 5 depends on Bundle 4. No Bundle 3/4/5 task depends on impeachment / watchdog / rotation specifically.
