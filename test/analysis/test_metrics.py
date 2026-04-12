# Copyright 2024 CAMEL-AI.org. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Tests for analysis/metrics.py — the 6 §5.6 governance metrics."""
import sqlite3
from pathlib import Path

import pytest

from analysis.metrics import ObservatoryMetrics
from oasis.governance.schema import create_governance_tables
from oasis.adjudication.schema import create_adjudication_tables


@pytest.fixture
def gov_db(tmp_path: Path) -> str:
    path = str(tmp_path / "gov.db")
    create_governance_tables(path)
    create_adjudication_tables(path)  # Same file for simplicity
    return path


def _insert_agent(db: str, did: str, tier: str, rep: float = 0.5) -> None:
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO agent_registry "
            "(agent_did, agent_type, capability_tier, display_name, reputation_score) "
            "VALUES (?, 'producer', ?, ?, ?)",
            (did, tier, did, rep),
        )
        conn.commit()


class TestGini:
    def test_all_equal_returns_zero(self):
        assert ObservatoryMetrics._gini([0.5, 0.5, 0.5, 0.5]) == 0.0

    def test_max_inequality_approaches_one(self):
        result = ObservatoryMetrics._gini([0.0] * 99 + [100.0])
        assert result > 0.98

    def test_empty_returns_zero(self):
        assert ObservatoryMetrics._gini([]) == 0.0

    def test_zero_sum_returns_zero(self):
        assert ObservatoryMetrics._gini([0.0, 0.0]) == 0.0


class TestGovernanceConvergenceRate:
    def test_all_converged(self, gov_db):
        with sqlite3.connect(gov_db) as conn:
            conn.execute(
                "INSERT INTO legislative_session (session_id, state) VALUES (?, ?)",
                ("s1", "DEPLOYED"),
            )
            conn.execute(
                "INSERT INTO legislative_session (session_id, state) VALUES (?, ?)",
                ("s2", "VOTING"),
            )
            conn.commit()
        m = ObservatoryMetrics(gov_db)
        assert m.get_governance_convergence_rate() == 1.0

    def test_half_converged(self, gov_db):
        with sqlite3.connect(gov_db) as conn:
            conn.execute(
                "INSERT INTO legislative_session (session_id, state) VALUES (?, ?)",
                ("s1", "DEPLOYED"),
            )
            conn.execute(
                "INSERT INTO legislative_session (session_id, state) VALUES (?, ?)",
                ("s2", "PROPOSAL_OPEN"),
            )
            conn.commit()
        m = ObservatoryMetrics(gov_db)
        assert m.get_governance_convergence_rate() == 0.5

    def test_empty_returns_zero(self, gov_db):
        m = ObservatoryMetrics(gov_db)
        assert m.get_governance_convergence_rate() == 0.0


class TestParticipationDepthByTier:
    def test_counts_actions_per_tier(self, gov_db):
        _insert_agent(gov_db, "did:t1:a", "t1")
        _insert_agent(gov_db, "did:t3:b", "t3")
        _insert_agent(gov_db, "did:t5:c", "t5")
        # Tier t5 proposes twice, t3 once, t1 never
        with sqlite3.connect(gov_db) as conn:
            # Need a session first (foreign key)
            conn.execute(
                "INSERT INTO legislative_session (session_id, state) VALUES (?, ?)",
                ("s1", "PROPOSAL_OPEN"),
            )
            conn.execute(
                "INSERT INTO proposal "
                "(proposal_id, session_id, proposer_did, dag_spec, "
                "token_budget_total, deadline_ms) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("p1", "s1", "did:t5:c", "{}", 100.0, 0),
            )
            conn.execute(
                "INSERT INTO proposal "
                "(proposal_id, session_id, proposer_did, dag_spec, "
                "token_budget_total, deadline_ms) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("p2", "s1", "did:t5:c", "{}", 100.0, 0),
            )
            conn.execute(
                "INSERT INTO proposal "
                "(proposal_id, session_id, proposer_did, dag_spec, "
                "token_budget_total, deadline_ms) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("p3", "s1", "did:t3:b", "{}", 100.0, 0),
            )
            conn.commit()

        m = ObservatoryMetrics(gov_db)
        result = m.get_participation_depth_by_tier()
        assert result.get("t5") == 2.0
        assert result.get("t3") == 1.0
        assert result.get("t1") == 0.0


class TestComputeAllMetrics:
    def test_returns_all_six_keys(self, gov_db):
        m = ObservatoryMetrics(gov_db)
        result = m.compute_all_metrics()
        expected = {
            "governance_convergence_rate",
            "reputation_gini",
            "hhi_task_allocation",
            "treasury_trajectory",
            "participation_depth_by_tier",
            "proposal_acceptance_by_tier",
        }
        assert set(result.keys()) == expected
