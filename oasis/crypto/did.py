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

import base58

_ED25519_PREFIX = bytes([0xED, 0x01])
_EXPECTED_LEN = 34  # 2 prefix + 32 pubkey


def did_from_pubkey(pub: bytes) -> str:
    r"""Encode a 32-byte Ed25519 public key as a ``did:key`` DID.

    Parameters
    ----------
    pub:
        Exactly 32 bytes.

    Returns
    -------
    str
        A DID string of the form ``did:key:z<base58btc(0xed01 + pub)>``.

    Raises
    ------
    ValueError
        If *pub* is not exactly 32 bytes.
    """
    if len(pub) != 32:
        raise ValueError(f"pubkey must be exactly 32 bytes, got {len(pub)}")
    payload = _ED25519_PREFIX + pub
    encoded = base58.b58encode(payload).decode("ascii")
    return f"did:key:z{encoded}"


def resolve(did: str) -> bytes:
    r"""Resolve a ``did:key`` DID to its raw Ed25519 public key.

    Parameters
    ----------
    did:
        A DID string starting with ``did:key:z``.

    Returns
    -------
    bytes
        The 32-byte public key payload.

    Raises
    ------
    ValueError
        If the DID is not a ``did:key`` DID, has an invalid base58 body,
        the decoded payload is not 34 bytes, or the multicodec prefix is
        not ``0xed01``.
    """
    if not isinstance(did, str):
        raise ValueError("DID must be a string")
    if not did.startswith("did:key:"):
        raise ValueError("DID must use the did:key method")
    fragment = did[len("did:key:") :]
    if not fragment:
        raise ValueError("DID has empty fragment")
    if fragment[0] != "z":
        raise ValueError("DID multibase prefix must be 'z'")
    body = fragment[1:]
    if not body:
        raise ValueError("DID has empty base58 body")
    try:
        decoded = base58.b58decode(body)
    except Exception as exc:
        raise ValueError(f"invalid base58 body: {exc}") from exc
    if len(decoded) != _EXPECTED_LEN:
        raise ValueError(
            f"decoded body must be {_EXPECTED_LEN} bytes, got {len(decoded)}"
        )
    if decoded[:2] != _ED25519_PREFIX:
        raise ValueError(f"multicodec prefix must be 0xed01, got {decoded[:2].hex()}")
    return decoded[2:]
