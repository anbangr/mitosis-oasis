# Interfaces

This document focuses on the repo-to-repo contracts `mitosis-oasis` exposes.

## Prototype -> OASIS HTTP Contract

The prototype is the main consumer; OASIS is the producer of the HTTP platform contract.

### Expected stable surfaces

- health endpoint availability
- route behavior used by the prototype adapter
- request/response semantics for platform-backed operations
- observability endpoints if the prototype or operators rely on them

### Contract rule

If a route shape or health semantic changes, update:

- this file
- `mitosis-prototype/docs/interfaces.md`
- any relevant flow docs

## Control Plane -> OASIS Platform/Observability Contract

The control plane consumes:

- health checks
- platform reachability
- observability/dashboard-related outputs

If OASIS changes a surface the control plane uses operationally, treat it as a cross-repo contract change.

## Internal Branch Contract Note

Governance, execution, adjudication, and observatory are separate internal branches, but external consumers should not need to understand internal module layout to use the stable HTTP contract.
