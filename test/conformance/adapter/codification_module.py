"""Conformance adapter for the CodificationModule contract.

This module maps captured CodificationModule fixture calls onto OASIS
governance codification behavior where a production Python counterpart exists.
Functions with no OASIS counterpart are intentionally left unregistered so the
replay harness reports them as GAP instead of masking drift with Solidity-state
simulation.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from oasis.governance.clerks.codifier import Codifier
from oasis.governance.messages import CodedContractSpec, DAGProposal
from oasis.governance.schema import create_governance_tables, seed_constitution
from test.conformance.adapter._base import AdapterBase
from test.conformance.adapter.registry import register
from test.conformance.oracle.schema import CallResult, EmittedEvent, FixtureCall


# Mapping comment block:
#
# Solidity function                         -> OASIS counterpart
# ---------------------------------------------------------------------------
# codify(bytes32,bytes32,bytes32)           -> Codifier.compile_spec
# verifyDeployment(bytes32,bytes32,bytes32) -> Codifier.verify_deployment
#
# Explicit gaps:
# GAP: DEFAULT_ADMIN_ROLE()                 -> AccessControl role constant only
# GAP: CODIFIER_ROLE()                      -> AccessControl role constant only
# GAP: DEPLOYER_ROLE()                      -> AccessControl role constant only
# GAP: WHITELIST_ROLE()                     -> AccessControl role constant only
# GAP: hasRole(bytes32,address)             -> AccessControl role storage
# GAP: addToWhitelist(bytes32)              -> Solidity whitelist storage/policy
# GAP: removeFromWhitelist(bytes32)         -> Solidity whitelist storage/policy
# GAP: isWhitelisted(bytes32)               -> Solidity whitelist storage view
# GAP: pause()                              -> Solidity pause flag
# GAP: unpause()                            -> Solidity pause flag
# GAP: getRecord(bytes32)                   -> Solidity deployment-record storage
# GAP: isVerified(bytes32)                  -> Solidity deployment-record status
# GAP: recordDeployment(bytes32,address,bytes32)
#                                             -> Solidity deployment-record storage
# GAP: triggerRollback(bytes32)             -> Solidity rollback status storage
#
# OASIS has Codifier.compile_spec and Codifier.verify_deployment, but it does
# not expose Solidity-compatible whitelist, pause, role, or deployment-record
# storage. Those functions are not registered. Missing registry lookups are the
# conformance signal for those surfaces.


_ZERO32 = "0x" + ("0" * 64)


def _strip_selector(raw_calldata: str | None) -> str:
    data = (raw_calldata or "").lower().removeprefix("0x")
    if len(data) <= 8:
        return ""
    return data[8:]


def _word_to_bytes32(word: str) -> str:
    return "0x" + word.lower().removeprefix("0x").rjust(64, "0")[-64:]


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


def _encode_bool(value: bool) -> str:
    return f"0x{1 if value else 0:064x}"


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


def _with_codifier(callback) -> Any:
    with tempfile.TemporaryDirectory(prefix="cm-adapter-") as tmp:
        db_path = Path(tmp) / "governance.db"
        create_governance_tables(db_path)
        seed_constitution(db_path)
        codifier = Codifier(
            db_path=db_path,
            clerk_did="did:oasis:fixture-codifier",
            private_key=None,
        )
        return callback(db_path, codifier)


def _compile_oasis_spec(call: FixtureCall) -> tuple[str, CodedContractSpec]:
    proposal_hash, init_hash, constructor_args_hash = _decode_words(call, 3)
    session_id = f"cm-replay-{call.idx}-{proposal_hash[-8:]}"

    def compile_in_db(db_path: Path, codifier: Codifier):
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
        return session_id, codifier.compile_spec(session_id, proposal, approved_bids)

    return _with_codifier(compile_in_db)


def _verification_spec(call: FixtureCall) -> tuple[CodedContractSpec, dict]:
    proposal_hash, constructor_args_hash, runtime_hash = _decode_words(call, 3)
    service_contract_specs = {
        "dag_spec": {
            "nodes": [
                {
                    "node_id": proposal_hash,
                    "service_id": "codification-module",
                    "constructor_args_hash": constructor_args_hash,
                    "runtime_bytecode_hash": runtime_hash,
                }
            ],
            "edges": [],
        },
        "service_assignments": [
            {
                "node_id": proposal_hash,
                "service_id": "codification-module",
                "runtime_bytecode_hash": runtime_hash,
            }
        ],
        "bid_assignments": {"did:oasis:fixture-bidder": 1.0},
    }
    spec = CodedContractSpec(
        session_id=f"cm-verify-{call.idx}-{proposal_hash[-8:]}",
        collaboration_contract_spec={"session_id": proposal_hash},
        guardian_module_spec={"budget_enforcement": True},
        verification_module_spec={"code_hash_verification": True},
        gate_module_spec={"constitutional_validation": True},
        service_contract_specs=service_contract_specs,
        validation_proof=f"fixture-{proposal_hash[-8:]}",
        signature=None,
    )
    deployed_contract = {
        "collaboration_contract_spec": spec.collaboration_contract_spec,
        "guardian_module_spec": spec.guardian_module_spec,
        "verification_module_spec": spec.verification_module_spec,
        "gate_module_spec": spec.gate_module_spec,
        "service_contract_specs": spec.service_contract_specs,
    }
    return spec, deployed_contract


class CodificationModuleAdapter(AdapterBase):
    contract = "CodificationModule"

    def dispatch(self, call: FixtureCall) -> CallResult:
        if call.function == "codify(bytes32,bytes32,bytes32)":
            return self.codify(call)
        if call.function == "verifyDeployment(bytes32,bytes32,bytes32)":
            return self.verify_deployment(call)
        return _ok()

    def codify(self, call: FixtureCall) -> CallResult:
        session_id, spec = _compile_oasis_spec(call)
        return _ok(
            events=[
                EmittedEvent(
                    name="SpecCompiled",
                    args={
                        "sessionId": session_id,
                        "validationProof": spec.validation_proof,
                    },
                )
            ],
            return_data=[spec.validation_proof],
        )

    def verify_deployment(self, call: FixtureCall) -> CallResult:
        spec, deployed_contract = _verification_spec(call)

        def verify_in_db(db_path: Path, codifier: Codifier):
            _seed_codifier_session(db_path, spec.session_id)
            return codifier.verify_deployment(spec, deployed_contract)

        result = _with_codifier(verify_in_db)
        return _ok(
            events=[
                EmittedEvent(
                    name="OasisDeploymentVerified",
                    args={
                        "passed": str(result["passed"]).lower(),
                        "mismatches": ",".join(result["mismatches"]),
                    },
                )
            ],
            return_data=_encode_bool(result["passed"]),
        )


_ADAPTER = CodificationModuleAdapter()
for fn in (
    "codify(bytes32,bytes32,bytes32)",
    "verifyDeployment(bytes32,bytes32,bytes32)",
):
    register("CodificationModule", fn, _ADAPTER.dispatch)
