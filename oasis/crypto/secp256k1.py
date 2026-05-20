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

from eth_account._utils.signing import sign_message_hash
from eth_keys import keys


def sign_hash(private_key: bytes, msg_hash: bytes) -> bytes:
    r"""Sign a 32-byte message hash with a secp256k1 private key.

    Parameters
    ----------
    private_key:
        The raw private key bytes.
    msg_hash:
        Exactly 32 bytes.

    Returns
    -------
    bytes
        65-byte signature (r || s || v) where *v* is canonical 27/28.

    Raises
    ------
    ValueError
        If *msg_hash* is not exactly 32 bytes.
    """
    if len(msg_hash) != 32:
        raise ValueError(f"msg_hash must be exactly 32 bytes, got {len(msg_hash)}")

    priv_key = keys.PrivateKey(private_key)
    v, r, s, sig_bytes = sign_message_hash(priv_key, msg_hash)
    return sig_bytes


def recover_signer(msg_hash: bytes, sig: bytes) -> str:
    r"""Recover the EIP-55 checksum address from a message hash and signature.

    Accepts signatures where the recovery byte *v* is either 0/1 or the
    canonical form 27/28.

    Parameters
    ----------
    msg_hash:
        Exactly 32 bytes.
    sig:
        Exactly 65 bytes (r || s || v).

    Returns
    -------
    str
        The recovered Ethereum address, EIP-55 checksum-cased.

    Raises
    ------
    ValueError
        If *msg_hash* is not exactly 32 bytes or *sig* is not exactly 65 bytes.
    """
    if len(msg_hash) != 32:
        raise ValueError(f"msg_hash must be exactly 32 bytes, got {len(msg_hash)}")
    if len(sig) != 65:
        raise ValueError(f"sig must be exactly 65 bytes, got {len(sig)}")

    v = sig[64]
    if v >= 27:
        v = v - 27

    normalized_sig = sig[:64] + bytes([v])
    signature = keys.Signature(signature_bytes=normalized_sig)
    pubkey = signature.recover_public_key_from_msg_hash(msg_hash)
    return pubkey.to_checksum_address()
