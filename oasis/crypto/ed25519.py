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

from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey


def generate_keypair() -> tuple[bytes, bytes]:
    r"""Generate a fresh Ed25519 keypair.

    Returns
    -------
    tuple[bytes, bytes]
        (private_key, public_key) — both 32-byte ``bytes``.
    """
    sk = SigningKey.generate()
    return sk.encode(), sk.verify_key.encode()


def keypair_from_seed(seed: bytes) -> tuple[bytes, bytes]:
    r"""Deterministically derive an Ed25519 keypair from a 32-byte seed.

    Parameters
    ----------
    seed:
        Exactly 32 bytes.

    Returns
    -------
    tuple[bytes, bytes]
        (private_key, public_key) — both 32-byte ``bytes``.

    Raises
    ------
    ValueError
        If *seed* is not exactly 32 bytes.
    """
    if len(seed) != 32:
        raise ValueError(f"seed must be exactly 32 bytes, got {len(seed)}")
    sk = SigningKey(seed)
    return sk.encode(), sk.verify_key.encode()


def sign(private_key: bytes, message: bytes) -> bytes:
    r"""Sign a message with an Ed25519 private key.

    Parameters
    ----------
    private_key:
        Exactly 32 bytes.
    message:
        Arbitrary-length message bytes.

    Returns
    -------
    bytes
        64-byte detached signature.

    Raises
    ------
    ValueError
        If *private_key* is not exactly 32 bytes.
    """
    if len(private_key) != 32:
        raise ValueError(
            f"private_key must be exactly 32 bytes, got {len(private_key)}"
        )
    sk = SigningKey(private_key)
    return sk.sign(message).signature


def verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    r"""Verify an Ed25519 detached signature.

    Returns ``False`` (never raises) for any invalid input — wrong-length
    keys/signatures, corrupted messages, or mismatched keys.

    Parameters
    ----------
    public_key:
        32-byte public key.
    message:
        The message that was signed.
    signature:
        64-byte detached signature.

    Returns
    -------
    bool
        ``True`` iff the signature is valid for *message* under *public_key*.
    """
    if len(public_key) != 32 or len(signature) != 64:
        return False
    try:
        VerifyKey(public_key).verify(message, signature)
        return True
    except BadSignatureError:
        return False
