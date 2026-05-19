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
from __future__ import annotations

import re

import base58
import pytest

from oasis.crypto import ed25519
from oasis.crypto.did import did_from_pubkey, resolve


# ---------------------------------------------------------------------------
# T1 — did_from_pubkey roundtrip
# ---------------------------------------------------------------------------


def test_t1_did_from_pubkey_roundtrip():
    r"""did_from_pubkey + resolve round-trips: resolve(did_from_pubkey(pub)) == pub."""
    _priv, pub = ed25519.generate_keypair()
    d = did_from_pubkey(pub)
    assert d.startswith("did:key:z"), f"DID does not start with 'did:key:z': {d!r}"
    recovered = resolve(d)
    assert recovered == pub, "resolve did not return the original public key"


# ---------------------------------------------------------------------------
# T2 — multicodec prefix shape
# ---------------------------------------------------------------------------


def test_t2_multicodec_prefix_shape():
    r"""did_from_pubkey encodes 0xed01 + pubkey; base58 body starts with bytes([0xed, 0x01])."""
    pub = b"\x01" * 32
    d = did_from_pubkey(pub)
    assert d.startswith("did:key:z"), f"DID does not start with 'did:key:z': {d!r}"
    # Strip the multibase 'z' prefix to get the raw base58 string
    fragment = d[len("did:key:z"):]
    decoded = base58.b58decode(fragment)
    assert decoded[:2] == bytes([0xED, 0x01]), (
        f"multicodec prefix is {decoded[:2].hex()!r}, expected 'ed01'"
    )
    assert decoded[2:] == pub, "payload after prefix does not equal original pubkey"


# ---------------------------------------------------------------------------
# T3 — resolve rejects non-did:key
# ---------------------------------------------------------------------------


def test_t3_resolve_rejects_non_did_key():
    r"""resolve raises ValueError containing 'did:key' for non-did:key DIDs."""
    with pytest.raises(ValueError, match=r"did:key"):
        resolve("did:web:example.com")


# ---------------------------------------------------------------------------
# T4 — resolve rejects malformed body
# ---------------------------------------------------------------------------


def test_t4_resolve_rejects_malformed_body():
    r"""resolve raises ValueError for a did:key DID with an invalid base58 body."""
    with pytest.raises(ValueError):
        resolve("did:key:NOT_VALID")


# ---------------------------------------------------------------------------
# T5 — pubkey length guard
# ---------------------------------------------------------------------------


def test_t5_pubkey_length_guard():
    r"""did_from_pubkey raises ValueError when pubkey is not exactly 32 bytes."""
    with pytest.raises(ValueError):
        did_from_pubkey(b"\x01" * 31)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_edge_base58_decode_failure_raises_value_error():
    r"""A base58 decode failure is wrapped in ValueError, not left as a bare Exception."""
    # Characters like '0', 'O', 'I', 'l' are invalid in base58btc
    bad_did = "did:key:z0OIl"
    with pytest.raises(ValueError):
        resolve(bad_did)


def test_edge_decoded_body_too_short_raises_value_error():
    r"""resolve raises ValueError when decoded body is shorter than 34 bytes (2 prefix + 32)."""
    # Encode a too-short payload (prefix + 15 bytes instead of 32)
    short_payload = bytes([0xED, 0x01]) + b"\x00" * 15
    encoded = base58.b58encode(short_payload).decode()
    bad_did = f"did:key:z{encoded}"
    with pytest.raises(ValueError):
        resolve(bad_did)


def test_edge_decoded_body_too_long_raises_value_error():
    r"""resolve raises ValueError when decoded body is longer than 34 bytes (2 prefix + 32)."""
    long_payload = bytes([0xED, 0x01]) + b"\x00" * 33
    encoded = base58.b58encode(long_payload).decode()
    bad_did = f"did:key:z{encoded}"
    with pytest.raises(ValueError):
        resolve(bad_did)


def test_edge_multicodec_prefix_mismatch_raises_value_error():
    r"""resolve raises ValueError when multicodec prefix is not 0xed01 (e.g. secp256k1 0xe701)."""
    secp256k1_payload = bytes([0xE7, 0x01]) + b"\x02" * 32
    encoded = base58.b58encode(secp256k1_payload).decode()
    bad_did = f"did:key:z{encoded}"
    with pytest.raises(ValueError):
        resolve(bad_did)


def test_edge_pubkey_too_long_raises_value_error():
    r"""did_from_pubkey raises ValueError when pubkey is longer than 32 bytes."""
    with pytest.raises(ValueError):
        did_from_pubkey(b"\x01" * 33)


def test_edge_pubkey_empty_raises_value_error():
    r"""did_from_pubkey raises ValueError for an empty pubkey."""
    with pytest.raises(ValueError):
        did_from_pubkey(b"")


def test_edge_resolve_returns_bytes():
    r"""resolve returns bytes, not str."""
    _priv, pub = ed25519.generate_keypair()
    d = did_from_pubkey(pub)
    recovered = resolve(d)
    assert isinstance(recovered, bytes), "resolve must return bytes"


def test_edge_did_is_a_string():
    r"""did_from_pubkey returns a str."""
    _priv, pub = ed25519.generate_keypair()
    d = did_from_pubkey(pub)
    assert isinstance(d, str), "did_from_pubkey must return str"


def test_edge_did_format_matches_pattern():
    r"""DID format matches did:key:z[1-9A-HJ-NP-Za-km-z]+ (base58btc alphabet only)."""
    _priv, pub = ed25519.generate_keypair()
    d = did_from_pubkey(pub)
    assert re.fullmatch(r"did:key:z[1-9A-HJ-NP-Za-km-z]+", d), (
        f"DID does not match expected pattern: {d!r}"
    )


def test_edge_deterministic_did_for_same_pubkey():
    r"""did_from_pubkey is deterministic: same pubkey always yields the same DID."""
    seed = b"\xab" * 32
    _priv, pub = ed25519.keypair_from_seed(seed)
    d1 = did_from_pubkey(pub)
    d2 = did_from_pubkey(pub)
    assert d1 == d2, "did_from_pubkey must be deterministic"


def test_edge_resolve_strips_correct_prefix():
    r"""resolve correctly strips the 0xed01 multicodec prefix before returning pubkey."""
    known_pub = b"\xab" * 32
    d = did_from_pubkey(known_pub)
    recovered = resolve(d)
    assert recovered == known_pub
    assert len(recovered) == 32
