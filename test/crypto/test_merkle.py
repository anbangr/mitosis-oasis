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
"""Tests for oasis.crypto.merkle — balanced-binary Merkle tree, SHA-256."""
from __future__ import annotations

import hashlib

import pytest

from oasis.crypto import merkle


# ---------------------------------------------------------------------------
# T1 — Empty root
# ---------------------------------------------------------------------------


def test_t1_empty_root_is_zero32():
    r"""Empty leaf list returns 32 zero bytes."""
    assert merkle.build_root([]) == b"\x00" * 32


# ---------------------------------------------------------------------------
# T2 — Single leaf
# ---------------------------------------------------------------------------


def test_t2_single_leaf_root_equals_leaf():
    r"""Single leaf root equals SHA-256 of that leaf."""
    leaf = b"hello"
    expected = hashlib.sha256(leaf).digest()
    assert merkle.build_root([leaf]) == expected


# ---------------------------------------------------------------------------
# T3 — Two leaves
# ---------------------------------------------------------------------------


def test_t3_two_leaf_root():
    r"""Two leaves: root is SHA-256 of concatenated leaf hashes."""
    a = hashlib.sha256(b"a").digest()
    b = hashlib.sha256(b"b").digest()
    expected = hashlib.sha256(a + b).digest()
    assert merkle.build_root([b"a", b"b"]) == expected


# ---------------------------------------------------------------------------
# T4 — Odd leaf duplication
# ---------------------------------------------------------------------------


def test_t4_odd_leaf_count_duplicates_last():
    r"""Standard convention: with an odd leaf count, the last is duplicated."""
    a = hashlib.sha256(b"a").digest()
    b = hashlib.sha256(b"b").digest()
    c = hashlib.sha256(b"c").digest()
    ab = hashlib.sha256(a + b).digest()
    cc = hashlib.sha256(c + c).digest()
    expected = hashlib.sha256(ab + cc).digest()
    assert merkle.build_root([b"a", b"b", b"c"]) == expected


# ---------------------------------------------------------------------------
# T5 — Proof roundtrip
# ---------------------------------------------------------------------------


def test_t5_proof_and_verify_roundtrip():
    r"""proof() and verify_proof() round-trip for every leaf in an 8-leaf tree."""
    leaves = [f"leaf-{i}".encode() for i in range(8)]
    root = merkle.build_root(leaves)
    for i, leaf in enumerate(leaves):
        proof = merkle.proof(leaves, i)
        assert merkle.verify_proof(root, leaf, i, proof) is True


# ---------------------------------------------------------------------------
# T6 — Tampered leaf rejection
# ---------------------------------------------------------------------------


def test_t6_verify_rejects_tampered_leaf():
    r"""verify_proof returns False when the leaf payload is tampered."""
    leaves = [f"leaf-{i}".encode() for i in range(8)]
    root = merkle.build_root(leaves)
    proof = merkle.proof(leaves, 0)
    assert merkle.verify_proof(root, b"TAMPERED", 0, proof) is False


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_edge_single_leaf_proof_roundtrip():
    r"""A single-leaf tree has an empty proof that still verifies."""
    leaves = [b"solo"]
    root = merkle.build_root(leaves)
    proof = merkle.proof(leaves, 0)
    assert merkle.verify_proof(root, b"solo", 0, proof) is True


def test_edge_proof_rejects_tampered_index():
    r"""verify_proof returns False when the claimed index is wrong."""
    leaves = [f"leaf-{i}".encode() for i in range(8)]
    root = merkle.build_root(leaves)
    proof = merkle.proof(leaves, 0)
    # Pass correct leaf but wrong index
    assert merkle.verify_proof(root, leaves[0], 1, proof) is False


def test_edge_verify_rejects_tampered_proof():
    r"""verify_proof returns False when a sibling hash in the proof is tampered."""
    leaves = [f"leaf-{i}".encode() for i in range(8)]
    root = merkle.build_root(leaves)
    proof = merkle.proof(leaves, 0)
    tampered_proof = [b"\xff" * 32 if i == 0 else h for i, h in enumerate(proof)]
    assert merkle.verify_proof(root, leaves[0], 0, tampered_proof) is False


def test_edge_proof_odd_leaf_count():
    r"""proof/verify works when odd leaf count forces last-node duplication."""
    leaves = [b"a", b"b", b"c"]
    root = merkle.build_root(leaves)
    for i, leaf in enumerate(leaves):
        p = merkle.proof(leaves, i)
        assert merkle.verify_proof(root, leaf, i, p) is True


def test_edge_proof_raises_on_negative_index():
    r"""proof raises IndexError for negative target_index."""
    leaves = [b"a", b"b"]
    with pytest.raises(IndexError):
        merkle.proof(leaves, -1)


def test_edge_proof_raises_on_out_of_range_index():
    r"""proof raises IndexError when target_index >= len(leaves)."""
    leaves = [b"a", b"b"]
    with pytest.raises(IndexError):
        merkle.proof(leaves, 2)


def test_edge_proof_raises_on_empty_leaves():
    r"""proof raises IndexError for empty leaf list."""
    with pytest.raises(IndexError):
        merkle.proof([], 0)


def test_edge_two_leaves_proof_roundtrip():
    r"""Two-leaf tree proof/verify round-trip for both indices."""
    leaves = [b"left", b"right"]
    root = merkle.build_root(leaves)
    for i, leaf in enumerate(leaves):
        p = merkle.proof(leaves, i)
        assert merkle.verify_proof(root, leaf, i, p) is True


def test_edge_verify_rejects_wrong_root():
    r"""verify_proof returns False when root does not match."""
    leaves = [f"leaf-{i}".encode() for i in range(8)]
    root = merkle.build_root(leaves)
    proof = merkle.proof(leaves, 0)
    wrong_root = b"\xab" * 32
    assert merkle.verify_proof(wrong_root, leaves[0], 0, proof) is False
