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
import tomlkit
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_hash.auto import keccak

from oasis.crypto.eip712 import (
    hash_typed_data,
    recover_signer,
    sign,
    signable_typed_data,
    verify,
)
from oasis.crypto.typed_data import (
    DOMAIN,
    ConstitutionAmendmentTypedData,
    ImpeachmentTypedData,
    SanctionTypedData,
    TypedDataMessage,
)

_TARGET_DID = "did:key:z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doY"


@pytest.fixture()
def acct():
    return Account.create()


@pytest.fixture()
def sanction_data():
    return SanctionTypedData(
        target_did=_TARGET_DID,
        amount_wei=100,
        reason="test",
        nonce=1,
    )


# ---------------------------------------------------------------------------
# T1 — hash is full EIP-712 envelope digest
# ---------------------------------------------------------------------------


def test_t1_hash_is_full_eip712_envelope(sanction_data):
    r"""hash_typed_data returns 32-byte EIP-712 envelope digest, not the bare struct hash."""
    schema = SanctionTypedData.TYPE_SCHEMA
    message = sanction_data.to_dict()

    our = hash_typed_data(DOMAIN, "Sanction", message)

    signable = encode_typed_data(
        domain_data=DOMAIN,
        message_types={"Sanction": schema},
        message_data=message,
    )
    canonical = keccak(b"\x19" + signable.version + signable.header + signable.body)

    assert our == canonical
    assert len(our) == 32
    assert our != signable.body, "must be full envelope digest, not bare struct hash"


# ---------------------------------------------------------------------------
# T2 — sign+verify roundtrip via our API
# ---------------------------------------------------------------------------


def test_t2_sign_verify_roundtrip(acct, sanction_data):
    r"""sign + recover_signer round-trip recovers the original address; sig is 65 bytes."""
    message = sanction_data.to_dict()

    sig = sign(acct.key, DOMAIN, "Sanction", message)
    recovered = recover_signer(DOMAIN, "Sanction", message, sig)

    assert len(sig) == 65
    assert recovered.lower() == acct.address.lower()


# ---------------------------------------------------------------------------
# T3 — verify returns False for wrong signer
# ---------------------------------------------------------------------------


def test_t3_verify_wrong_signer(acct, sanction_data):
    r"""verify returns False for the zero address; True for the actual signer."""
    message = sanction_data.to_dict()
    sig = sign(acct.key, DOMAIN, "Sanction", message)

    assert (
        verify(
            DOMAIN,
            "Sanction",
            message,
            sig,
            expected_signer="0x0000000000000000000000000000000000000000",
        )
        is False
    )
    assert (
        verify(DOMAIN, "Sanction", message, sig, expected_signer=acct.address) is True
    )


# ---------------------------------------------------------------------------
# T4 — hash on ConstitutionAmendment works
# ---------------------------------------------------------------------------


def test_t4_hash_constitution_amendment():
    r"""hash_typed_data accepts ConstitutionAmendment primary type and returns 32 bytes."""
    data = ConstitutionAmendmentTypedData(
        rule_id="rule-001",
        content="Amend section 4",
        nonce=1,
    )
    digest = hash_typed_data(DOMAIN, "ConstitutionAmendment", data.to_dict())

    assert isinstance(digest, bytes)
    assert len(digest) == 32


# ---------------------------------------------------------------------------
# T5 — unknown primary_type rejected
# ---------------------------------------------------------------------------


def test_t5_unknown_primary_type_raises():
    r"""hash_typed_data raises ValueError matching /primary_type=Bogus/ for unknown types."""
    with pytest.raises(ValueError, match=r"primary_type=Bogus"):
        hash_typed_data(DOMAIN, "Bogus", {})


# ---------------------------------------------------------------------------
# T6 — raw eth_account signature verifies through our API (wallet compatibility)
# ---------------------------------------------------------------------------


def test_t6_raw_ethaccount_sig_verifies(acct, sanction_data):
    r"""A raw Account.sign_message(encode_typed_data(...)) sig verifies via oasis.crypto.eip712.verify."""
    schema = SanctionTypedData.TYPE_SCHEMA
    message = sanction_data.to_dict()

    signable = encode_typed_data(
        domain_data=DOMAIN,
        message_types={"Sanction": schema},
        message_data=message,
    )
    signed = Account.sign_message(signable, private_key=acct.key)

    assert verify(DOMAIN, "Sanction", message, signed.signature, acct.address) is True


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_edge_domain_version_matches_pyproject():
    r"""DOMAIN["version"] must equal the version declared in pyproject.toml at all times.

    Bundle 1 ships at pyproject == 0.3.0 (DOMAIN must match). Feature 12's
    v0.4.0 release commit bumps both surfaces atomically; the deleted
    test_edge_domain_version_is_040 over-constrained Feature 5 to ship
    pyproject == 0.4.0 prematurely, which contradicted the lockstep gate.
    """
    with open("pyproject.toml") as f:
        doc = tomlkit.parse(f.read())
    pyproject_version = doc["tool"]["poetry"]["version"]
    assert DOMAIN["version"] == pyproject_version


def test_edge_verify_swallows_exceptions(sanction_data):
    r"""verify returns False (never raises) on a garbage 65-byte signature."""
    result = verify(
        DOMAIN, "Sanction", sanction_data.to_dict(), b"\x00" * 65, "0x" + "00" * 20
    )
    assert result is False


def test_edge_verify_unknown_primary_type_returns_false(acct):
    r"""verify returns False for an unregistered primary_type, unlike hash_typed_data which raises."""
    result = verify(DOMAIN, "UnknownType", {}, b"\x00" * 65, acct.address)
    assert result is False


def test_edge_all_typed_data_subclasses_registered():
    r"""All three TypedDataMessage subclasses are discoverable via __subclasses__()."""
    names = {cls.__name__ for cls in TypedDataMessage.__subclasses__()}
    assert "SanctionTypedData" in names
    assert "ConstitutionAmendmentTypedData" in names
    assert "ImpeachmentTypedData" in names


def test_edge_sign_returns_exactly_65_bytes(acct, sanction_data):
    r"""sign returns exactly 65 bytes (r||s||v) given a 32-byte private key."""
    assert len(acct.key) == 32
    sig = sign(acct.key, DOMAIN, "Sanction", sanction_data.to_dict())
    assert len(sig) == 65
    assert isinstance(sig, bytes)


def test_edge_signable_typed_data_is_public_helper(sanction_data):
    r"""signable_typed_data returns a SignableMessage, allowing callers to use Account.recover_message directly."""
    from eth_account.messages import SignableMessage

    message = sanction_data.to_dict()
    signable = signable_typed_data(DOMAIN, "Sanction", message)
    assert isinstance(signable, SignableMessage)


def test_edge_domain_fields():
    r"""DOMAIN has correct name, chainId, and verifyingContract."""
    assert DOMAIN["name"] == "MitosisOasis"
    assert DOMAIN["chainId"] == 0
    assert DOMAIN["verifyingContract"] == "0x" + "0" * 40


def test_edge_impeachment_typed_data_is_subclass():
    r"""ImpeachmentTypedData is a subclass of TypedDataMessage."""
    assert issubclass(ImpeachmentTypedData, TypedDataMessage)


def test_edge_recover_signer_returns_checksum_address(acct, sanction_data):
    r"""recover_signer returns an EIP-55 checksum address string."""
    message = sanction_data.to_dict()
    sig = sign(acct.key, DOMAIN, "Sanction", message)
    recovered = recover_signer(DOMAIN, "Sanction", message, sig)

    assert isinstance(recovered, str)
    assert re.fullmatch(r"0x[a-fA-F0-9]{40}", recovered)
    assert recovered.lower() == acct.address.lower()


def test_edge_sign_not_using_signhash(acct, sanction_data):
    r"""sign uses Account.sign_message (not Account.signHash); the two paths yield different digests."""
    schema = SanctionTypedData.TYPE_SCHEMA
    message = sanction_data.to_dict()

    signable = encode_typed_data(
        domain_data=DOMAIN,
        message_types={"Sanction": schema},
        message_data=message,
    )
    envelope_hash = keccak(b"\x19" + signable.version + signable.header + signable.body)
    struct_hash = signable.body

    assert envelope_hash != struct_hash, (
        "EIP-712 envelope digest must differ from bare struct hash; "
        "sign must use the full envelope (Account.sign_message), not Account.signHash"
    )

    sig = sign(acct.key, DOMAIN, "Sanction", message)
    assert verify(DOMAIN, "Sanction", message, sig, acct.address) is True


def test_edge_sanction_typed_data_has_required_class_vars():
    r"""SanctionTypedData exposes TYPE_SCHEMA (list) and PRIMARY_TYPE (str) class vars."""
    assert hasattr(SanctionTypedData, "TYPE_SCHEMA")
    assert hasattr(SanctionTypedData, "PRIMARY_TYPE")
    assert isinstance(SanctionTypedData.TYPE_SCHEMA, list)
    assert SanctionTypedData.PRIMARY_TYPE == "Sanction"


def test_edge_constitution_amendment_has_required_class_vars():
    r"""ConstitutionAmendmentTypedData exposes TYPE_SCHEMA and PRIMARY_TYPE class vars."""
    assert hasattr(ConstitutionAmendmentTypedData, "TYPE_SCHEMA")
    assert hasattr(ConstitutionAmendmentTypedData, "PRIMARY_TYPE")
    assert isinstance(ConstitutionAmendmentTypedData.TYPE_SCHEMA, list)
    assert ConstitutionAmendmentTypedData.PRIMARY_TYPE == "ConstitutionAmendment"


def test_edge_impeachment_has_required_class_vars():
    r"""ImpeachmentTypedData exposes TYPE_SCHEMA and PRIMARY_TYPE class vars."""
    assert hasattr(ImpeachmentTypedData, "TYPE_SCHEMA")
    assert hasattr(ImpeachmentTypedData, "PRIMARY_TYPE")
    assert isinstance(ImpeachmentTypedData.TYPE_SCHEMA, list)
    assert ImpeachmentTypedData.PRIMARY_TYPE == "Impeachment"
