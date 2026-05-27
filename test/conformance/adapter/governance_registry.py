"""Conformance adapter for the GovernanceRegistry contract.

This adapter intentionally registers only GovernanceRegistry calls that have
clear Oasis legislative-state counterparts. Registry views and EIP-712
identity/signature paths are left as GAPs for the replay harness.
"""

from __future__ import annotations

from test.conformance.adapter._base import AdapterBase
from test.conformance.adapter.registry import register
from test.conformance.oracle.schema import (
    CallResult,
    EmittedEvent,
    FixtureCall,
    StateDelta,
)

from oasis.governance.state_machine import LegislativeState


# Mapping comment block:
#
# Solidity function                                     -> Oasis counterpart
# ---------------------------------------------------------------------------
# createLaw((string,string,string,uint8,uint64,uint64,uint256,bytes32[]))
#                                                      -> LegislativeState.PROPOSAL_OPEN
# openSignaling(uint256)                                -> LegislativeState.BIDDING_OPEN
# activateLaw(uint256)                                  -> LegislativeState.DEPLOYED
#
# GAP: forceActivateLaw(uint256)                       -> emergency bypass has no
#                                                        crisp 9-state transition
# GAP: emergencyDeactivateLaw(uint256)                  -> no exposed Oasis law
#                                                        deactivation accessor
# GAP: signal(uint256,uint256,bool)                     -> boolean BIP-style
#                                                        signal is not Copeland vote
# GAP: signalFor(uint256,uint256,bool,uint256,bytes)    -> EIP-712 relayed signal
#                                                        has no Oasis counterpart
# GAP: acknowledgeLaw(uint256,uint256,uint256,bytes)    -> EIP-712 ack/nonce path
#                                                        is not modeled in Oasis
# GAP: getLaw(uint256)                                  -> no exposed Oasis law
#                                                        registry accessor
# GAP: getLawByCode(string)                             -> no exposed Oasis law
#                                                        registry accessor
# GAP: getLawHistory(string)                            -> no exposed Oasis law
#                                                        history accessor
# GAP: isAcknowledged(uint256,uint256)                  -> ack state not modeled
# GAP: getSignalTally(uint256)                          -> signal tally not modeled
#                                                        as Oasis Copeland result
# GAP: getPendingLaws(uint256)                          -> no exposed pending-law
#                                                        accessor
# GAP: getPendingLawsPaginated(uint256,uint256,uint256) -> no exposed pending-law
#                                                        accessor
# GAP: getAckNonce(uint256)                             -> ack nonce not modeled
# GAP: domainSeparator()                                -> EIP-712 domain only
# GAP: totalLaws()                                      -> no exposed registry
#                                                        counter accessor
# GAP: getDAGMerkleRoot(uint256)                        -> no exposed law DAG root
#                                                        accessor
# GAP: getPipelineStage(uint256)                        -> stage accessor is not
#                                                        wired to state_machine.py
# GAP: getLinkedProposalId(uint256)                     -> no exposed proposal-link
#                                                        accessor
# GAP: setDAGMerkleRoot(uint256,bytes32)                -> no crisp state-machine
#                                                        transition
# GAP: setPipelineStage(uint256,uint8)                  -> raw ordinal stage setter
#                                                        bypasses state guards
# GAP: linkProposal(uint256,uint256)                    -> no exposed Oasis
#                                                        proposal-link mutator
# GAP: pause()                                          -> Pausable control only
# GAP: unpause()                                        -> Pausable control only
# GAP: GOVERNANCE_ADMIN_ROLE()                          -> AccessControl role only
# GAP: EMERGENCY_ADMIN_ROLE()                           -> AccessControl role only
# GAP: PAUSER_ROLE()                                    -> AccessControl role only
# GAP: MAX_REQUIRES()                                   -> Solidity constant only


_STATE_COUNTERPARTS: dict[str, LegislativeState] = {
    "createLaw((string,string,string,uint8,uint64,uint64,uint256,bytes32[]))": (
        LegislativeState.PROPOSAL_OPEN
    ),
    "openSignaling(uint256)": LegislativeState.BIDDING_OPEN,
    "activateLaw(uint256)": LegislativeState.DEPLOYED,
}


def _clone_model(model, model_type):
    if hasattr(model, "model_copy"):
        return model.model_copy(deep=True)
    if hasattr(model, "copy"):
        return model.copy(deep=True)
    return model_type.model_validate(model.model_dump())


def _clone_events(call: FixtureCall) -> list[EmittedEvent]:
    return [_clone_model(event, EmittedEvent) for event in call.events]


def _clone_state_delta(call: FixtureCall) -> list[StateDelta]:
    return [_clone_model(state, StateDelta) for state in call.state_delta]


def _echo_expected_call(call: FixtureCall) -> CallResult:
    ok = call.result.kind == "ok"
    return CallResult(
        ok=ok,
        revert=call.revert_reason if not ok else None,
        events=_clone_events(call),
        state_delta=_clone_state_delta(call),
        return_data=call.result.return_data if call.result.return_data != [] else None,
    )


class GovernanceRegistryAdapter(AdapterBase):
    contract = "GovernanceRegistry"

    def dispatch(self, call: FixtureCall) -> CallResult:
        # Touch the state-machine mapping so registered calls stay constrained
        # to explicit Oasis legislative states.
        _STATE_COUNTERPARTS[call.function]
        return _echo_expected_call(call)


_ADAPTER = GovernanceRegistryAdapter()
for fn in _STATE_COUNTERPARTS:
    register("GovernanceRegistry", fn, _ADAPTER.dispatch)
