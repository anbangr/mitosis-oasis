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

import pytest

from oasis.crypto.ed25519 import generate_keypair, keypair_from_seed, sign, verify


# ---------------------------------------------------------------------------
# T1 — keypair shape
# ---------------------------------------------------------------------------


def test_t1_keypair_shape():
    r"""generate_keypair returns (bytes, bytes) both of length 32."""
    priv, pub = generate_keypair()
    assert isinstance(priv, bytes), "private key must be bytes"
    assert isinstance(pub, bytes), "public key must be bytes"
    assert len(priv) == 32, f"private key length {len(priv)} != 32"
    assert len(pub) == 32, f"public key length {len(pub)} != 32"


# ---------------------------------------------------------------------------
# T2 — sign + verify roundtrip
# ---------------------------------------------------------------------------


def test_t2_sign_verify_roundtrip():
    r"""sign produces a 64-byte sig; verify returns True for matching key/msg."""
    priv, pub = generate_keypair()
    msg = b"hello agentcity"
    sig = sign(priv, msg)
    assert len(sig) == 64, f"signature length {len(sig)} != 64"
    assert verify(pub, msg, sig) is True


# ---------------------------------------------------------------------------
# T3 — verify rejects tampered message
# ---------------------------------------------------------------------------


def test_t3_verify_rejects_tampered_message():
    r"""verify returns False when the message does not match the signature."""
    priv, pub = generate_keypair()
    sig = sign(priv, b"original")
    assert verify(pub, b"tampered", sig) is False


# ---------------------------------------------------------------------------
# T4 — verify rejects wrong pubkey
# ---------------------------------------------------------------------------


def test_t4_verify_rejects_wrong_pubkey():
    r"""verify returns False when the public key does not match the signer."""
    priv_a, _ = generate_keypair()
    _, pub_b = generate_keypair()
    msg = b"hello agentcity"
    sig = sign(priv_a, msg)
    assert verify(pub_b, msg, sig) is False


# ---------------------------------------------------------------------------
# T5 — deterministic seed
# ---------------------------------------------------------------------------


def test_t5_deterministic_seed():
    r"""keypair_from_seed is deterministic: two calls with same seed are identical."""
    seed = b"\x00" * 32
    priv1, pub1 = keypair_from_seed(seed)
    priv2, pub2 = keypair_from_seed(seed)
    assert priv1 == priv2, "private keys must be identical for same seed"
    assert pub1 == pub2, "public keys must be identical for same seed"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_edge_keypair_from_seed_rejects_short_seed():
    r"""keypair_from_seed raises ValueError for a seed shorter than 32 bytes."""
    with pytest.raises(ValueError):
        keypair_from_seed(b"\x00" * 16)


def test_edge_keypair_from_seed_rejects_long_seed():
    r"""keypair_from_seed raises ValueError for a seed longer than 32 bytes."""
    with pytest.raises(ValueError):
        keypair_from_seed(b"\x00" * 64)


def test_edge_sign_rejects_non_32_byte_private_key():
    r"""sign raises ValueError when private key is not exactly 32 bytes."""
    with pytest.raises(ValueError):
        sign(b"\x00" * 16, b"msg")


def test_edge_verify_returns_false_for_wrong_length_pubkey():
    r"""verify returns False (never raises) when pubkey has wrong length."""
    priv, _ = generate_keypair()
    msg = b"msg"
    sig = sign(priv, msg)
    result = verify(b"\x00" * 16, msg, sig)
    assert result is False


def test_edge_verify_returns_false_for_wrong_length_signature():
    r"""verify returns False (never raises) when signature has wrong length."""
    _, pub = generate_keypair()
    result = verify(pub, b"msg", b"\x00" * 16)
    assert result is False


def test_edge_verify_never_raises_on_garbage_inputs():
    r"""verify must swallow BadSignatureError and return False, never raise."""
    _, pub = generate_keypair()
    assert verify(pub, b"garbage", b"\xff" * 64) is False


def test_edge_sign_verify_empty_message():
    r"""sign and verify work correctly with an empty byte string message."""
    priv, pub = generate_keypair()
    sig = sign(priv, b"")
    assert len(sig) == 64
    assert verify(pub, b"", sig) is True


def test_edge_deterministic_seed_produces_valid_signing_pair():
    r"""A seeded keypair can sign and verify successfully."""
    seed = b"\xab" * 32
    priv, pub = keypair_from_seed(seed)
    msg = b"seeded message"
    sig = sign(priv, msg)
    assert verify(pub, msg, sig) is True
