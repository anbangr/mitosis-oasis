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

import pytest
from eth_account import Account

from oasis.crypto.secp256k1 import recover_signer, sign_hash


# ---------------------------------------------------------------------------
# T1 — sign-then-recover round-trip
# ---------------------------------------------------------------------------


def test_t1_sign_then_recover_roundtrip():
    r"""sign_hash produces 65-byte sig; recover_signer returns the original address."""
    acct = Account.create()
    msg_hash = b"\x00" * 32
    sig = sign_hash(acct.key, msg_hash)
    assert len(sig) == 65, f"signature length {len(sig)} != 65"
    addr = recover_signer(msg_hash, sig)
    assert addr.lower() == acct.address.lower()


# ---------------------------------------------------------------------------
# T2 — recover rejects wrong hash
# ---------------------------------------------------------------------------


def test_t2_recover_rejects_wrong_hash():
    r"""recover_signer with a different hash returns a different address."""
    acct = Account.create()
    original_hash = b"\x00" * 32
    sig = sign_hash(acct.key, original_hash)
    wrong_hash = b"\x01" * 32
    recovered = recover_signer(wrong_hash, sig)
    assert recovered.lower() != acct.address.lower()


# ---------------------------------------------------------------------------
# T3 — sign rejects bad hash length
# ---------------------------------------------------------------------------


def test_t3_sign_rejects_bad_hash_length():
    r"""sign_hash raises ValueError when msg_hash is not 32 bytes."""
    acct = Account.create()
    with pytest.raises(ValueError):
        sign_hash(acct.key, b"\x00" * 31)


# ---------------------------------------------------------------------------
# T4 — recover rejects bad sig length
# ---------------------------------------------------------------------------


def test_t4_recover_rejects_bad_sig_length():
    r"""recover_signer raises ValueError when sig is not 65 bytes."""
    msg_hash = b"\x00" * 32
    with pytest.raises(ValueError):
        recover_signer(msg_hash, b"\x00" * 64)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_edge_output_address_is_checksum_cased():
    r"""recover_signer returns an EIP-55 checksum address (0x[a-fA-F0-9]{40})."""
    acct = Account.create()
    msg_hash = b"\xab" * 32
    sig = sign_hash(acct.key, msg_hash)
    addr = recover_signer(msg_hash, sig)
    assert re.fullmatch(r"0x[a-fA-F0-9]{40}", addr), f"not a checksum address: {addr}"
    # Verify it matches eth_account's own checksum
    assert addr == acct.address


def test_edge_v_normalization_v27():
    r"""v >= 27 is normalized internally; recovery still succeeds."""
    acct = Account.create()
    msg_hash = b"\x11" * 32
    sig = sign_hash(acct.key, msg_hash)
    # Manually set v to 27 + original v (simulate caller passing canonical v)
    v = sig[64]
    if v < 27:
        canonical_sig = sig[:64] + bytes([v + 27])
    else:
        canonical_sig = sig
    # If implementation exposes a recovery path that accepts v=27/28, test it
    addr = recover_signer(msg_hash, canonical_sig)
    assert addr.lower() == acct.address.lower()


def test_edge_sign_rejects_bad_hash_too_long():
    r"""sign_hash raises ValueError when msg_hash is longer than 32 bytes."""
    acct = Account.create()
    with pytest.raises(ValueError):
        sign_hash(acct.key, b"\x00" * 33)


def test_edge_sign_rejects_empty_hash():
    r"""sign_hash raises ValueError when msg_hash is empty."""
    acct = Account.create()
    with pytest.raises(ValueError):
        sign_hash(acct.key, b"")


def test_edge_recover_rejects_empty_sig():
    r"""recover_signer raises ValueError when sig is empty."""
    with pytest.raises(ValueError):
        recover_signer(b"\x00" * 32, b"")


def test_edge_recover_rejects_short_sig():
    r"""recover_signer raises ValueError when sig is shorter than 65 bytes."""
    with pytest.raises(ValueError):
        recover_signer(b"\x00" * 32, b"\x00" * 32)


def test_edge_sign_multiple_accounts_produce_different_sigs():
    r"""Different private keys sign the same hash to different (addr, sig) pairs."""
    msg_hash = b"\xcc" * 32
    acct_a = Account.create()
    acct_b = Account.create()
    sig_a = sign_hash(acct_a.key, msg_hash)
    sig_b = sign_hash(acct_b.key, msg_hash)
    addr_a = recover_signer(msg_hash, sig_a)
    addr_b = recover_signer(msg_hash, sig_b)
    assert addr_a.lower() == acct_a.address.lower()
    assert addr_b.lower() == acct_b.address.lower()
    assert addr_a.lower() != addr_b.lower()


def test_edge_sig_bytes_type():
    r"""sign_hash returns bytes, not bytearray or memoryview."""
    acct = Account.create()
    sig = sign_hash(acct.key, b"\x00" * 32)
    assert isinstance(sig, bytes)


def test_edge_recover_signer_returns_str():
    r"""recover_signer returns a str, not bytes."""
    acct = Account.create()
    msg_hash = b"\x00" * 32
    sig = sign_hash(acct.key, msg_hash)
    addr = recover_signer(msg_hash, sig)
    assert isinstance(addr, str)
