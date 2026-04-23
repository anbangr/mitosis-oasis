# Mitosis OASIS Engineering Docs

This file is the canonical engineering entrypoint for `mitosis-oasis`.

The repo also contains a public-facing Mintlify docs site. That site is useful for external adopters, but the documents below are the current source of truth for internal development and production operation.

## Canonical Docs

| Document | Purpose |
|---|---|
| `architecture.md` | Internal runtime architecture and branch boundaries |
| `development.md` | Local setup and daily developer workflow |
| `testing.md` | Pytest and API-level validation expectations |
| `cicd.md` | Inlined workflow behavior, public/private repo constraint, current deploy status |
| `operations.md` | Service bring-up, health checks, and deployment posture |
| `troubleshooting.md` | Common API, DB, and runner/deploy issues |
| `api.md` | High-level HTTP and websocket surface map |
| `configuration.md` | Runtime variables and deploy-time knobs |
| `fork-divergence.md` | What this repo keeps from upstream and what it intentionally replaces |
| `observability.md` | Observatory routes, websocket stream, and runtime signals |

## Reference Material

- Mintlify/public docs under `docs/*.mdx`
- `IMPLEMENTATION_PLAN.md`
- `CLAUDE.md`

For cross-repo production flow, see the workspace handbook at `../docs/`.
