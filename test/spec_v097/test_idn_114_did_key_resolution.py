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
r"""IDN-114 rubric row — agents use W3C-compatible DID format.

Coverage target: ≥80%.
"""

from __future__ import annotations

import hashlib

import pytest

from oasis.crypto import ed25519
from oasis.crypto.did import did_from_pubkey, resolve


# ---------------------------------------------------------------------------
# T1 — did_format is did:key:z
# ---------------------------------------------------------------------------


def test_t1_did_format_is_did_key_z(ed25519_keypair):
    r"""T1: did_from_pubkey(pub).startswith("did:key:z") is True."""
    _priv, pub = ed25519_keypair
    did = did_from_pubkey(pub)
    assert did.startswith("did:key:z"), (
        f"Expected did:key:z prefix, got {did!r}"
    )


# ---------------------------------------------------------------------------
# T2 — did resolves back to pubkey
# ---------------------------------------------------------------------------


def test_t2_did_resolves_back_to_pubkey(ed25519_keypair):
    r"""T2: resolve(did_from_pubkey(pub)) equals pub."""
    _priv, pub = ed25519_keypair
    did = did_from_pubkey(pub)
    recovered = resolve(did)
    assert recovered == pub, "resolve(did) did not return original pubkey"


# ---------------------------------------------------------------------------
# T6 — ed25519_keypair determinism
# ---------------------------------------------------------------------------


def test_t6_ed25519_keypair_determinism(request):
    r"""T6: Fixture seeded from sha256(request.node.name) produces identical keys.

    Verified by recomputing the expected keypair from the same seed algorithm
    and asserting equality with the fixture output.
    """
    seed = hashlib.sha256(request.node.name.encode()).digest()
    expected_priv, expected_pub = ed25519.keypair_from_seed(seed)

    priv, pub = request.getfixturevalue("ed25519_keypair")
    assert priv == expected_priv, "ed25519_keypair private key not deterministic"
    assert pub == expected_pub, "ed25519_keypair public key not deterministic"
