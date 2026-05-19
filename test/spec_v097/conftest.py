# =========== Copyright 2023 @ CAMEL-AI.org. All Rights Reserved. ===========
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# =========== Copyright 2023 @ CAMEL-AI.org. All Rights Reserved. ===========
r"""Spec-v097 test infrastructure — shared constants and database fixtures.

Every test in this directory asserts a behaviour required by the
AgentCity v0.97 deepdive specs.  Fixtures here expose spec-exact
constants that test files import; no test should hard-code a magic
number that the spec also names.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from oasis.adjudication.schema import create_adjudication_tables
from oasis.governance.schema import create_governance_tables, seed_constitution

# ---------------------------------------------------------------------------
# Spec-exact Constitutional Parameters cited verbatim from v0.97 deepdives
# ---------------------------------------------------------------------------

SPEC_QUORUM_THRESHOLD = 0.60  # leg §1.7, votingQuorum
SPEC_FAIRNESS_HHI_MIN = 600  # leg §1.6, fairnessMinimum (1000 scale)
SPEC_PROTOCOL_FEE_BPS = 200  # exec §8.1, f_p
SPEC_REPUTATION_INITIAL = 500  # exec §2.4, rho_0 (1000 scale)
SPEC_REPUTATION_ALPHA_DEFAULT = 0.5  # exec §2.6, multiplier slope
SPEC_REPUTATION_LAMBDA_DEFAULT = 0.5  # exec §2.2-2.3, EMA smoothing
SPEC_TIER3_TIMEOUT_FLOOR_MS = 300_000  # leg §1.5, 5-minute human floor
SPEC_GUARDIAN_DEVIATION_SIGMA = 2.0  # exec §0.3
SPEC_BID_WEIGHT_Q = 0.6  # exec §1.2
SPEC_BID_WEIGHT_P = 0.4  # exec §1.2
SPEC_SPONSORSHIP_MIN = 5  # leg §4
SPEC_PROPOSAL_TIMEOUT_MS = 600_000  # leg §0.8, 10 min
SPEC_BIDDING_WINDOW_MS = 900_000  # leg §0.8, 15 min
SPEC_APPROVAL_TIMEOUT_MS = 300_000  # leg §0.8, 5 min


# ---------------------------------------------------------------------------
# Shared database fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def governance_db(tmp_path: Path) -> sqlite3.Connection:
    r"""Fresh governance DB seeded with tables and default constitution.

    Yields an open ``sqlite3.Connection`` (row_factory set to
    ``sqlite3.Row``) and closes it on teardown.
    """
    db_path = tmp_path / "gov.db"
    create_governance_tables(str(db_path))
    seed_constitution(str(db_path))
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture
def adj_db(tmp_path: Path) -> sqlite3.Connection:
    r"""Fresh adjudication DB with schema provisioned but no rows.

    Yields an open ``sqlite3.Connection`` (row_factory set to
    ``sqlite3.Row``) and closes it on teardown.
    """
    db_path = tmp_path / "adj.db"
    create_adjudication_tables(str(db_path))
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()
