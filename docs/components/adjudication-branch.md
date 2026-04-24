# Adjudication Branch

## Purpose

The adjudication branch handles review, sanctions, overrides, settlement, and treasury-relevant follow-up to execution outcomes.

## Responsibilities

- alert and review logic
- override or panel decision paths
- sanctions and settlement handling
- treasury-affecting consequences

## Structure

| Path | Responsibility |
|---|---|
| `oasis/adjudication/endpoints.py` | adjudication routes |
| `oasis/adjudication/schema.py` | adjudication storage |

## Interfaces

- Input: execution outcomes, alerts, policy signals
- Output: sanctions, settlement values, adjudication records, observatory events

## Runtime Flow

1. Execution-related or policy-driven input reaches adjudication routes.
2. Review logic determines whether intervention is required.
3. Settlement and sanction logic updates branch state.
4. Results propagate to observability and downstream consumers.

## Failure Modes

- inconsistent sanction state
- missing upstream execution context
- adjudication API shape drifting from tests

## Tests

- adjudication API tests
- cross-branch behavior tests where present

## Change Risks

- settlement semantics can change observability and economic assumptions elsewhere
