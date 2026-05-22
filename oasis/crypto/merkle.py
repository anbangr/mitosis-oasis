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


def verify_proof(
    root: bytes,
    leaf: bytes,
    target_index: int,
    proof_path: Sequence[bytes],
) -> bool:
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
