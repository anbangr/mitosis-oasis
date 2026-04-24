# ADR-0001: OASIS Exposes An External HTTP Platform Contract

## Status

Accepted

## Context

The fork diverged from the original embedded-agent model and became a platform for external runtimes and operators.

## Decision

Treat the HTTP API as the primary integration contract for OASIS.

## Consequences

- Consumer repos integrate through documented HTTP behavior rather than internal Python modules.
- Route, health, and observability changes require explicit contract coordination.
