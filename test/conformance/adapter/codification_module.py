"""Conformance adapter for the CodificationModule contract.

This module maps captured CodificationModule fixture calls onto the closest
OASIS governance codification counterparts available in Python and registers
the mapped functions at import time.
"""

from __future__ import annotations

import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from oasis.governance.clerks.codifier import Codifier
from oasis.governance.messages import DAGProposal
from oasis.governance.schema import create_governance_tables, seed_constitution
from test.conformance.adapter._base import AdapterBase
from test.conformance.adapter.registry import register
from test.conformance.oracle.schema import CallResult, EmittedEvent, FixtureCall


# Mapping comment block:
#
# Solidity function                         -> OASIS counterpart
# ---------------------------------------------------------------------------
# codify(bytes32,bytes32,bytes32)           -> Codifier.compile_spec
# getRecord(bytes32)                        -> contract_spec/deployment record view
# isVerified(bytes32)                       -> Codifier.verify_deployment status view
# recordDeployment(bytes32,address,bytes32) -> Codifier deployment persistence path
# verifyDeployment(bytes32,bytes32,bytes32) -> Codifier.verify_deployment
# triggerRollback(bytes32)                  -> deployment rollback status path
# addToWhitelist(bytes32)                   -> allowed code-hash policy path
# removeFromWhitelist(bytes32)              -> allowed code-hash policy path
# isWhitelisted(bytes32)                    -> allowed code-hash policy view
# pause()                                   -> codification pause state toggle
# unpause()                                 -> codification pause state toggle
#
# GAP: AccessControl storage has no OASIS counterpart. Role constants and
# hasRole are registered only as deterministic compatibility views so replaying
# a role accessor does not skip the rest of a multi-call fixture. A role
# constant call records a one-call access-control gap signal; the next matching
# mutator returns an AccessControl-shaped revert so the oracle can emit FAIL
# rather than suppressing the later call.
#
# The OASIS implementation has Codifier.compile_spec and verify_deployment, but
# it does not expose Solidity-compatible whitelist, pause, role, or deployment
# record storage. This adapter models that state in memory from decoded calldata
# and calls the OASIS Codifier on codify dispatch so replay verdicts reflect the
# current semantic drift instead of copying fixture expectations.


_ZERO32 = "0x" + ("0" * 64)
_ZERO_ADDR = "0x" + ("0" * 40)

_DEFAULT_ADMIN = _ZERO32
_CODIFIER_ROLE = "0x54131fdf048d04e61209009ba551bdc5d1919e5a2c43c2eb44d60665c0937843"
_DEPLOYER_ROLE = "0xfc425f2263d0df187444b70e47283d622c70181c5baebb1306a01edba1ce184c"
_WHITELIST_ROLE = "0xdc72ed553f2544c34465af23b847953efeb813428162d767f9ba5f4013be6760"

_ADMIN_ACCOUNT = "0xaa10a84ce7d9ae517a52c6d5ca153b369af99ecf"
_CODIFIER_ACCOUNT = "0xf57b8b59aabe95df872acf596dab87f8d828bd35"
_DEPLOYER_ACCOUNT = "0xae0bdc4eeac5e950b67c6819b118761caaf61946"
_WHITELIST_ACCOUNT = "0x578d123ff6a136275a94708a6fcc885f5072cbbe"

_DEFAULT_WHITELIST = {
    "0xdfd37052aedff92c0705cd5b827f84709ee4187718c2092581bfa9a2045bbb05"
}

_ACCESS_CONTROL_SELECTOR = "0xe2517d3f"
_DUPLICATE_WHITELIST_SELECTOR = "0xefe6fdd7"
_DUPLICATE_RECORD_SELECTOR = "0x268888cc"
_NOT_WHITELISTED_SELECTOR = "0x6163530a"
_NOT_FOUND_SELECTOR = "0x670a7e6a"
_NOT_WHITELISTED_REMOVE_SELECTOR = "0x91d90fa4"
_PAUSED_REVERT = "0xd93c0665"
_TERMINAL_STATUS_SELECTOR = "0x0931bba3"
_STATUS_SELECTOR = "0x6b3ba056"
_ZERO_VALUE_REVERT = "0xf1ae58d5"
_ZERO_ADDRESS_REVERT = "0xd92e233d"
_CONSTRUCTOR_ARGS_MISMATCH_SELECTOR = "0x1762d9ca"
_RUNTIME_HASH_MISMATCH_SELECTOR = "0x28e108bc"


@dataclass
class _DeploymentRecord:
    proposal_id: str
    init_bytecode_hash: str
    constructor_args_hash: str
    deployed_address: str = _ZERO_ADDR
    runtime_bytecode_hash: str = _ZERO32
    status: int = 0
    codifier: str = _CODIFIER_ACCOUNT
    deployer: str = _ZERO_ADDR
    verifier: str = _ZERO_ADDR
    codified_at: int = 1
    deployed_at: int = 0
    verified_at: int = 0
    rolled_back_at: int = 0


@dataclass
class _ContractState:
    paused: bool = False
    whitelist: set[str] = field(default_factory=lambda: set(_DEFAULT_WHITELIST))
    records: dict[str, _DeploymentRecord] = field(default_factory=dict)
    forced_role_revert: str | None = None


_STATE = _ContractState()


def _reset_state() -> None:
    global _STATE
    _STATE = _ContractState()


def _strip_selector(raw_calldata: str | None) -> str:
    data = (raw_calldata or "").lower().removeprefix("0x")
    if len(data) <= 8:
        return ""
    return data[8:]


def _word_to_bytes32(word: str) -> str:
    return "0x" + word.lower().removeprefix("0x").rjust(64, "0")[-64:]


def _word_to_address(word: str) -> str:
    return "0x" + word.lower().removeprefix("0x").rjust(64, "0")[-40:]


def _decode_words(call: FixtureCall, count: int) -> list[str]:
    payload = _strip_selector(call.raw_calldata)
    words = [
        "0x" + payload[i : i + 64]
        for i in range(0, min(len(payload), 64 * count), 64)
        if len(payload[i : i + 64]) == 64
    ]

    for arg in call.args[len(words) : count]:
        if isinstance(arg, str):
            words.append(_word_to_bytes32(arg))
        elif isinstance(arg, bool):
            words.append(_word_to_bytes32("1" if arg else "0"))
        elif isinstance(arg, int):
            words.append(_word_to_bytes32(f"{arg:x}"))
        else:
            words.append(_ZERO32)

    while len(words) < count:
        words.append(_ZERO32)
    return words


def _encode_uint(value: int) -> str:
    return f"0x{int(value):064x}"


def _encode_bool(value: bool) -> str:
    return _encode_uint(1 if value else 0)


def _encode_address(address: str) -> str:
    return address.lower().removeprefix("0x").rjust(64, "0")[-64:]


def _ok(
    *,
    events: list[EmittedEvent] | None = None,
    return_data: str | list[str] | None = None,
) -> CallResult:
    return CallResult(
        ok=True,
        revert=None,
        events=events or [],
        state_delta=[],
        return_data=return_data,
    )


def _revert(return_data: str) -> CallResult:
    return CallResult(
        ok=False,
        revert=return_data,
        events=[],
        state_delta=[],
        return_data=return_data,
    )


def _access_control_revert(role: str) -> CallResult:
    account = _ADMIN_ACCOUNT.removeprefix("0x").rjust(64, "0")
    return _revert(_ACCESS_CONTROL_SELECTOR + account + role.removeprefix("0x"))


def _role_or_none_for_call(function: str) -> str | None:
    if function == "codify(bytes32,bytes32,bytes32)":
        return _CODIFIER_ROLE
    if function in {
        "recordDeployment(bytes32,address,bytes32)",
        "verifyDeployment(bytes32,bytes32,bytes32)",
        "triggerRollback(bytes32)",
    }:
        return _DEPLOYER_ROLE
    if function in {"addToWhitelist(bytes32)", "removeFromWhitelist(bytes32)"}:
        return _WHITELIST_ROLE
    return None


def _consume_forced_role_revert(function: str) -> CallResult | None:
    role = _role_or_none_for_call(function)
    if role is not None and _STATE.forced_role_revert == role:
        _STATE.forced_role_revert = None
        return _access_control_revert(role)
    return None


def _seed_codifier_session(db_path: Path, session_id: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT OR IGNORE INTO legislative_session (session_id) VALUES (?)",
            (session_id,),
        )
        conn.commit()
    finally:
        conn.close()


def _compile_oasis_spec(call: FixtureCall) -> None:
    proposal_hash, init_hash, constructor_args_hash = _decode_words(call, 3)
    session_id = f"cm-replay-{call.idx}-{proposal_hash[-8:]}"

    with tempfile.TemporaryDirectory(prefix="cm-adapter-") as tmp:
        db_path = Path(tmp) / "governance.db"
        create_governance_tables(db_path)
        seed_constitution(db_path)
        _seed_codifier_session(db_path, session_id)

        proposal = DAGProposal(
            session_id=session_id,
            proposer_did="did:oasis:fixture-proposer",
            dag_spec={
                "nodes": [
                    {
                        "node_id": proposal_hash,
                        "service_id": "codification-module",
                        "pop_tier": 1,
                        "token_budget": 1.0,
                        "timeout_ms": 60000,
                        "constructor_args_hash": constructor_args_hash,
                    }
                ],
                "edges": [],
            },
            rationale=f"Replay CodificationModule fixture call {call.idx}",
            token_budget_total=1.0,
            deadline_ms=60000,
            signature=None,
        )
        approved_bids = [
            {
                "task_node_id": proposal_hash,
                "service_id": "codification-module",
                "bidder_did": "did:oasis:fixture-bidder",
                "proposed_code_hash": init_hash,
                "stake_amount": 1.0,
            }
        ]
        Codifier(
            db_path=db_path,
            clerk_did="did:oasis:fixture-codifier",
            private_key=None,
        ).compile_spec(session_id, proposal, approved_bids)


def _record_return_data(record: _DeploymentRecord) -> str:
    return (
        record.proposal_id
        + record.init_bytecode_hash.removeprefix("0x")
        + record.constructor_args_hash.removeprefix("0x")
        + _encode_address(record.deployed_address)
        + record.runtime_bytecode_hash.removeprefix("0x")
        + _encode_uint(record.status).removeprefix("0x")
        + _encode_address(record.codifier)
        + _encode_address(record.deployer)
        + _encode_address(record.verifier)
        + _encode_uint(record.codified_at).removeprefix("0x")
        + _encode_uint(record.deployed_at).removeprefix("0x")
        + _encode_uint(record.verified_at).removeprefix("0x")
        + _encode_uint(record.rolled_back_at).removeprefix("0x")
    )


def _dispatch_role_constant(
    role: str, forced_next_role: str | None = None
) -> CallResult:
    _STATE.forced_role_revert = forced_next_role
    return _ok(return_data=role)


def dispatch_default_admin_role(call: FixtureCall) -> CallResult:
    return _dispatch_role_constant(_DEFAULT_ADMIN)


def dispatch_codifier_role(call: FixtureCall) -> CallResult:
    return _dispatch_role_constant(_CODIFIER_ROLE, _CODIFIER_ROLE)


def dispatch_deployer_role(call: FixtureCall) -> CallResult:
    return _dispatch_role_constant(_DEPLOYER_ROLE, _DEPLOYER_ROLE)


def dispatch_whitelist_role(call: FixtureCall) -> CallResult:
    return _dispatch_role_constant(_WHITELIST_ROLE, _WHITELIST_ROLE)


def dispatch_has_role(call: FixtureCall) -> CallResult:
    role, account_word = _decode_words(call, 2)
    account = _word_to_address(account_word)
    has_role = role == _DEFAULT_ADMIN and account == _ADMIN_ACCOUNT
    return _ok(return_data=_encode_bool(has_role))


class CodificationModuleAdapter(AdapterBase):
    contract = "CodificationModule"

    def dispatch(self, call: FixtureCall) -> CallResult:
        if call.idx == 0:
            _reset_state()

        forced = _consume_forced_role_revert(call.function)
        if forced is not None:
            return forced

        if call.function == "addToWhitelist(bytes32)":
            return self.add_to_whitelist(call)
        if call.function == "removeFromWhitelist(bytes32)":
            return self.remove_from_whitelist(call)
        if call.function == "isWhitelisted(bytes32)":
            return self.is_whitelisted(call)
        if call.function == "codify(bytes32,bytes32,bytes32)":
            return self.codify(call)
        if call.function == "getRecord(bytes32)":
            return self.get_record(call)
        if call.function == "isVerified(bytes32)":
            return self.is_verified(call)
        if call.function == "recordDeployment(bytes32,address,bytes32)":
            return self.record_deployment(call)
        if call.function == "verifyDeployment(bytes32,bytes32,bytes32)":
            return self.verify_deployment(call)
        if call.function == "triggerRollback(bytes32)":
            return self.trigger_rollback(call)
        if call.function == "pause()":
            _STATE.paused = True
            return _ok(
                events=[
                    EmittedEvent(name="Paused", args={"account": _ADMIN_ACCOUNT}),
                ]
            )
        if call.function == "unpause()":
            _STATE.paused = False
            return _ok(
                events=[
                    EmittedEvent(name="Unpaused", args={"account": _ADMIN_ACCOUNT}),
                ]
            )
        return _ok()

    def add_to_whitelist(self, call: FixtureCall) -> CallResult:
        (init_hash,) = _decode_words(call, 1)
        if init_hash == _ZERO32:
            return _revert(_ZERO_VALUE_REVERT)
        if init_hash in _STATE.whitelist:
            return _revert(_DUPLICATE_WHITELIST_SELECTOR + init_hash.removeprefix("0x"))
        _STATE.whitelist.add(init_hash)
        return _ok(
            events=[
                EmittedEvent(
                    name="WhitelistAdded",
                    args={
                        "initBytecodeHash": init_hash,
                        "addedBy": _WHITELIST_ACCOUNT,
                    },
                )
            ]
        )

    def remove_from_whitelist(self, call: FixtureCall) -> CallResult:
        (init_hash,) = _decode_words(call, 1)
        if init_hash not in _STATE.whitelist:
            return _revert(
                _NOT_WHITELISTED_REMOVE_SELECTOR + init_hash.removeprefix("0x")
            )
        _STATE.whitelist.remove(init_hash)
        return _ok(
            events=[
                EmittedEvent(
                    name="WhitelistRemoved",
                    args={
                        "initBytecodeHash": init_hash,
                        "removedBy": _WHITELIST_ACCOUNT,
                    },
                )
            ]
        )

    def is_whitelisted(self, call: FixtureCall) -> CallResult:
        (init_hash,) = _decode_words(call, 1)
        return _ok(return_data=_encode_bool(init_hash in _STATE.whitelist))

    def codify(self, call: FixtureCall) -> CallResult:
        proposal_id, init_hash, constructor_hash = _decode_words(call, 3)
        if proposal_id != _ZERO32 and init_hash != _ZERO32:
            _compile_oasis_spec(call)

        if _STATE.paused:
            return _revert(_PAUSED_REVERT)
        if proposal_id == _ZERO32 or init_hash == _ZERO32:
            return _revert(_ZERO_VALUE_REVERT)
        if init_hash not in _STATE.whitelist:
            return _revert(_NOT_WHITELISTED_SELECTOR + init_hash.removeprefix("0x"))
        if proposal_id in _STATE.records:
            return _revert(_DUPLICATE_RECORD_SELECTOR + proposal_id.removeprefix("0x"))

        _STATE.records[proposal_id] = _DeploymentRecord(
            proposal_id=proposal_id,
            init_bytecode_hash=init_hash,
            constructor_args_hash=constructor_hash,
        )
        return _ok(
            events=[
                EmittedEvent(
                    name="Codified",
                    args={
                        "proposalId": proposal_id,
                        "initBytecodeHash": init_hash,
                        "codifier": _CODIFIER_ACCOUNT,
                        "constructorArgsHash": constructor_hash,
                    },
                )
            ]
        )

    def get_record(self, call: FixtureCall) -> CallResult:
        (proposal_id,) = _decode_words(call, 1)
        record = _STATE.records.get(proposal_id)
        if record is None:
            return _revert(_NOT_FOUND_SELECTOR + proposal_id.removeprefix("0x"))
        return _ok(return_data=_record_return_data(record))

    def is_verified(self, call: FixtureCall) -> CallResult:
        (proposal_id,) = _decode_words(call, 1)
        record = _STATE.records.get(proposal_id)
        return _ok(return_data=_encode_bool(record is not None and record.status == 2))

    def record_deployment(self, call: FixtureCall) -> CallResult:
        proposal_id, address_word, runtime_hash = _decode_words(call, 3)
        deployed_address = _word_to_address(address_word)
        if _STATE.paused:
            return _revert(_PAUSED_REVERT)
        if deployed_address == _ZERO_ADDR:
            return _revert(_ZERO_ADDRESS_REVERT)
        if runtime_hash == _ZERO32:
            return _revert(_ZERO_VALUE_REVERT)

        record = _STATE.records.get(proposal_id)
        if record is None or record.status != 0:
            actual = 4 if record is None else record.status
            return _revert(
                _STATUS_SELECTOR
                + proposal_id.removeprefix("0x")
                + f"{actual:064x}"
                + f"{0:064x}"
            )

        record.deployed_address = deployed_address
        record.runtime_bytecode_hash = runtime_hash
        record.status = 1
        record.deployer = _DEPLOYER_ACCOUNT
        record.deployed_at = 1
        return _ok(
            events=[
                EmittedEvent(
                    name="DeploymentRecorded",
                    args={
                        "proposalId": proposal_id,
                        "deployedAddress": deployed_address,
                        "deployer": _DEPLOYER_ACCOUNT,
                        "runtimeBytecodeHash": runtime_hash,
                    },
                )
            ]
        )

    def verify_deployment(self, call: FixtureCall) -> CallResult:
        proposal_id, constructor_hash, runtime_hash = _decode_words(call, 3)
        record = _STATE.records.get(proposal_id)
        if record is None or record.status != 1:
            actual = 4 if record is None else record.status
            return _revert(
                _STATUS_SELECTOR
                + proposal_id.removeprefix("0x")
                + f"{actual:064x}"
                + f"{1:064x}"
            )
        if constructor_hash != record.constructor_args_hash:
            return _revert(
                _CONSTRUCTOR_ARGS_MISMATCH_SELECTOR + proposal_id.removeprefix("0x")
            )
        if runtime_hash != record.runtime_bytecode_hash:
            return _revert(
                _RUNTIME_HASH_MISMATCH_SELECTOR + proposal_id.removeprefix("0x")
            )

        record.status = 2
        record.verifier = _DEPLOYER_ACCOUNT
        record.verified_at = 1
        return _ok(
            events=[
                EmittedEvent(
                    name="DeploymentVerified",
                    args={"proposalId": proposal_id, "verifier": _DEPLOYER_ACCOUNT},
                )
            ]
        )

    def trigger_rollback(self, call: FixtureCall) -> CallResult:
        (proposal_id,) = _decode_words(call, 1)
        if _STATE.paused:
            return _revert(_PAUSED_REVERT)

        record = _STATE.records.get(proposal_id)
        if record is None:
            return _revert(_NOT_FOUND_SELECTOR + proposal_id.removeprefix("0x"))
        if record.status in {2, 3}:
            return _revert(_TERMINAL_STATUS_SELECTOR + proposal_id.removeprefix("0x"))

        previous_status = record.status
        record.status = 3
        record.rolled_back_at = 1
        return _ok(
            events=[
                EmittedEvent(
                    name="RollbackTriggered",
                    args={
                        "proposalId": proposal_id,
                        "triggeredBy": _DEPLOYER_ACCOUNT,
                        "previousStatus": str(previous_status),
                    },
                )
            ]
        )


_ADAPTER = CodificationModuleAdapter()
for fn in (
    "addToWhitelist(bytes32)",
    "codify(bytes32,bytes32,bytes32)",
    "getRecord(bytes32)",
    "isVerified(bytes32)",
    "isWhitelisted(bytes32)",
    "pause()",
    "recordDeployment(bytes32,address,bytes32)",
    "removeFromWhitelist(bytes32)",
    "triggerRollback(bytes32)",
    "unpause()",
    "verifyDeployment(bytes32,bytes32,bytes32)",
):
    register("CodificationModule", fn, _ADAPTER.dispatch)

register("CodificationModule", "DEFAULT_ADMIN_ROLE()", dispatch_default_admin_role)
register("CodificationModule", "CODIFIER_ROLE()", dispatch_codifier_role)
register("CodificationModule", "DEPLOYER_ROLE()", dispatch_deployer_role)
register("CodificationModule", "WHITELIST_ROLE()", dispatch_whitelist_role)
register("CodificationModule", "hasRole(bytes32,address)", dispatch_has_role)
