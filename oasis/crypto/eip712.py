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

from eth_account import Account
from eth_account.messages import SignableMessage, encode_typed_data
from eth_hash.auto import keccak

from oasis.crypto.typed_data import TypedDataMessage


def _resolve_schema(primary_type: str) -> list[dict[str, str]]:
    r"""Look up the EIP-712 schema for *primary_type* via subclass registry.

    Raises
    ------
    ValueError
        If no registered subclass matches *primary_type*.
    """
    for cls in TypedDataMessage.__subclasses__():
        if cls.PRIMARY_TYPE == primary_type:
            return cls.TYPE_SCHEMA
    raise ValueError(f"primary_type={primary_type}")


def signable_typed_data(
    domain: dict[str, object],
    primary_type: str,
    message: dict[str, object],
) -> SignableMessage:
    r"""Build a ``SignableMessage`` for the given typed-data parameters.

    This is a public helper so callers (e.g. ``oasis.api_auth``) can pass
    the ``SignableMessage`` directly to ``Account.recover_message``.

    Returns
    -------
    SignableMessage
        The encoded EIP-712 message wrapping the full envelope.
    """
    schema = _resolve_schema(primary_type)
    return encode_typed_data(
        domain_data=domain,
        message_types={primary_type: schema},
        message_data=message,
    )


def hash_typed_data(
    domain: dict[str, object],
    primary_type: str,
    message: dict[str, object],
) -> bytes:
    r"""Return the 32-byte full EIP-712 envelope digest.

    The digest is ``keccak(b"\\x19" + version + header + body)`` — i.e.
    the same hash that ``Account.sign_message`` and
    ``Account.recover_message`` operate on internally.
    """
    signable = signable_typed_data(domain, primary_type, message)
    try:
        from eth_account.messages import _hash_eip191_message

        return _hash_eip191_message(signable)
    except Exception:
        # Fallback to the spec definition if the internal helper moves.
        return keccak(b"\x19" + signable.version + signable.header + signable.body)


def sign(
    private_key: bytes,
    domain: dict[str, object],
    primary_type: str,
    message: dict[str, object],
) -> bytes:
    r"""Sign a typed-data message and return the 65-byte signature (r || s || v).

    Uses ``Account.sign_message(signable, private_key)`` so the signature
    is computed over the full EIP-712 envelope digest, exactly as MetaMask
    and other wallets do.
    """
    signable = signable_typed_data(domain, primary_type, message)
    signed = Account.sign_message(signable, private_key=private_key)
    return signed.signature


def recover_signer(
    domain: dict[str, object],
    primary_type: str,
    message: dict[str, object],
    signature: bytes,
) -> str:
    r"""Recover the EIP-55 checksum address that signed the typed-data message.

    Mirrors the signing path via ``Account.recover_message``.
    """
    signable = signable_typed_data(domain, primary_type, message)
    return Account.recover_message(signable, signature=signature)


def verify(
    domain: dict[str, object],
    primary_type: str,
    message: dict[str, object],
    signature: bytes,
    expected_signer: str,
) -> bool:
    r"""Verify that *signature* over the typed-data message was made by *expected_signer*.

    Returns ``False`` on any internal exception (bad signature length,
    unregistered primary type, recovery failure, etc.).
    """
    try:
        recovered = recover_signer(domain, primary_type, message, signature)
        return recovered.lower() == expected_signer.lower()
    except Exception:
        return False
