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

from typing import ClassVar

from pydantic import BaseModel

DOMAIN = {
    "name": "MitosisOasis",
    "version": "0.8.1",
    "chainId": 0,
    "verifyingContract": "0x" + "0" * 40,
}

EIP712_DOMAIN_TYPE = [
    {"name": "name", "type": "string"},
    {"name": "version", "type": "string"},
    {"name": "chainId", "type": "uint256"},
    {"name": "verifyingContract", "type": "address"},
]


class TypedDataMessage(BaseModel):
    r"""Base class for EIP-712 typed-data messages.

    Subclasses must declare ``TYPE_SCHEMA`` (list of dicts) and
    ``PRIMARY_TYPE`` (str) as class variables.
    """

    TYPE_SCHEMA: ClassVar[list[dict[str, str]]] = []
    PRIMARY_TYPE: ClassVar[str] = ""

    def to_dict(self) -> dict[str, object]:
        r"""Return a plain dict suitable for ``eth_account.messages.encode_typed_data``."""
        return self.model_dump(by_alias=True)


class SanctionTypedData(TypedDataMessage):
    r"""EIP-712 typed data for a sanction action (slash / freeze)."""

    target_did: str
    amount_wei: int
    reason: str
    nonce: int

    TYPE_SCHEMA: ClassVar[list[dict[str, str]]] = [
        {"name": "target_did", "type": "string"},
        {"name": "amount_wei", "type": "uint256"},
        {"name": "reason", "type": "string"},
        {"name": "nonce", "type": "uint256"},
    ]
    PRIMARY_TYPE: ClassVar[str] = "Sanction"


class ConstitutionAmendmentTypedData(TypedDataMessage):
    r"""EIP-712 typed data for a constitution amendment proposal."""

    param_name: str
    param_value: str
    nonce: int

    TYPE_SCHEMA: ClassVar[list[dict[str, str]]] = [
        {"name": "param_name", "type": "string"},
        {"name": "param_value", "type": "string"},
        {"name": "nonce", "type": "uint256"},
    ]
    PRIMARY_TYPE: ClassVar[str] = "ConstitutionAmendment"


class ImpeachmentTypedData(TypedDataMessage):
    r"""EIP-712 typed data for an impeachment action (Bundle 2)."""

    target_did: str
    evidence_cid: str
    motion_id: str

    TYPE_SCHEMA: ClassVar[list[dict[str, str]]] = [
        {"name": "target_did", "type": "string"},
        {"name": "evidence_cid", "type": "string"},
        {"name": "motion_id", "type": "string"},
    ]
    PRIMARY_TYPE: ClassVar[str] = "Impeachment"
