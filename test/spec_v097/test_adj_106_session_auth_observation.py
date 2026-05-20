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
r"""ADJ-106 rubric row — Logging Hub / Dashboard are session auth, not EIP-712.

Coverage target: ≥80%.

These tests assert that read-only adjudication GET routes do NOT require
EIP-712 signatures.  They must NOT depend on a populated ``agent_registry``;
they verify status-code surface only.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from oasis.adjudication import endpoints as adj_ep
from oasis.adjudication.schema import create_adjudication_tables
from oasis.api import app
from oasis.execution.schema import create_execution_tables


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    r"""TestClient with fresh adjudication tables but no seeded data."""
    db_path = tmp_path / "adj_106.db"
    create_execution_tables(db_path)
    create_adjudication_tables(db_path)
    adj_ep.init_adjudication_db(str(db_path))
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# T3 — treasury route no EIP-712
# ---------------------------------------------------------------------------


def test_t3_treasury_route_no_eip712(client: TestClient):
    r"""T3: GET /api/adjudication/treasury does not require EIP-712 (status != 401)."""
    resp = client.get("/api/adjudication/treasury")
    assert resp.status_code != 401, (
        f"Treasury GET unexpectedly returned 401: {resp.text}"
    )


# ---------------------------------------------------------------------------
# T4 — decisions route no EIP-712
# ---------------------------------------------------------------------------


def test_t4_decisions_route_no_eip712(client: TestClient):
    r"""T4: GET /api/adjudication/decisions does not require EIP-712 (status != 401)."""
    resp = client.get("/api/adjudication/decisions")
    assert resp.status_code != 401, (
        f"Decisions GET unexpectedly returned 401: {resp.text}"
    )


# ---------------------------------------------------------------------------
# T5 — alerts route no EIP-712
# ---------------------------------------------------------------------------


def test_t5_alerts_route_no_eip712(client: TestClient):
    r"""T5: GET /api/adjudication/alerts does not require EIP-712 (status != 401)."""
    resp = client.get("/api/adjudication/alerts")
    assert resp.status_code != 401, f"Alerts GET unexpectedly returned 401: {resp.text}"


# ---------------------------------------------------------------------------
# T7 — eth_account_signer determinism
# ---------------------------------------------------------------------------


def test_t7_eth_account_signer_determinism(request):
    r"""T7: Fixture seeded from b'eth-' + test_name produces same address across runs.

    Verified by recomputing the expected account from the same seed algorithm
    and asserting address equality with the fixture output.
    """
    from eth_account import Account

    seed = hashlib.sha256(b"eth-" + request.node.name.encode()).digest()
    expected_acct = Account.from_key(seed)

    acct = request.getfixturevalue("eth_account_signer")
    assert acct.address.lower() == expected_acct.address.lower(), (
        "eth_account_signer address not deterministic"
    )
