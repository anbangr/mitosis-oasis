# Governance Branch

## Purpose

The governance branch implements the legislative protocol and approval logic that define how governance sessions progress from request to approval or failure.

## Responsibilities

- state machine transitions
- clerk coordination
- message validation and representation
- constitutional, fairness, DAG, and voting logic

## Structure

| Path | Responsibility |
|---|---|
| `oasis/governance/endpoints.py` | governance HTTP routes |
| `oasis/governance/state_machine.py` | lifecycle and state transitions |
| `oasis/governance/messages.py` | message types and payloads |
| `oasis/governance/constitutional.py` | constitutional checks |
| `oasis/governance/fairness.py` | fairness scoring |
| `oasis/governance/dag.py` | DAG validation |
| `oasis/governance/voting.py` | vote aggregation and tie-breaking |
| `oasis/governance/clerks/` | registrar, speaker, regulator, codifier logic |

## Interfaces

- Input: legislative requests and governance payloads
- Output: session state updates, approval/failure results, observatory events

## Runtime Flow

1. Governance request enters through the API.
2. Request is validated and assigned to the governance service flow.
3. Clerks and deterministic validators process the session.
4. Vote or approval logic finalizes the next state.

## Failure Modes

- invalid state transitions
- message/schema drift
- validator disagreement or unexpected LLM layer behavior

## Tests

- governance API tests
- branch-specific unit tests
- full HTTP E2E legislative pipeline tests

## Change Risks

- governance payload changes affect both the prototype adapter and operator assumptions
