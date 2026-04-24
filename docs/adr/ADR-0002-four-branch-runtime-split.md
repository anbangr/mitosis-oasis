# ADR-0002: Four-Branch Runtime Split

## Status

Accepted

## Context

The repo models distinct governance, execution, adjudication, and observability concerns with different logic and data needs.

## Decision

Keep the runtime split into four major branches with shared startup wiring and platform core.

## Consequences

- Architecture and component docs map cleanly to branch boundaries.
- Branch-specific behavior can evolve without collapsing all logic into one service layer.
