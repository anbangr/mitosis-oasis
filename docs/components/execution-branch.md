# Execution Branch

## Purpose

The execution branch manages how approved work turns into assigned tasks, commitments, dispatched execution, and validated outputs.

## Responsibilities

- task routing
- stake or commitment handling
- execution dispatch
- output validation

## Structure

| Path | Responsibility |
|---|---|
| `oasis/execution/endpoints.py` | execution API routes |
| `oasis/execution/service.py` | shared service instance and orchestration |
| `oasis/execution/schema.py` | execution branch database tables |

## Interfaces

- Input: execution requests and branch state from governance outputs
- Output: assignments, execution results, validated outputs, events

## Runtime Flow

1. Execution request arrives through the API.
2. Branch service loads or updates execution state.
3. Routing and commitment logic determine assignment.
4. Output is validated before downstream settlement or observability updates.

## Failure Modes

- execution schema drift
- assignment logic mismatch with expected runtime contracts
- validator rejects outputs unexpectedly

## Tests

- execution API tests
- service behavior tests where present

## Change Risks

- execution outputs often feed adjudication and observatory paths immediately
