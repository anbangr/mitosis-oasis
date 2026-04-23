# Contributing to Mitosis OASIS

This file describes the contribution contract for the forked Mitosis-maintained OASIS repo. For the canonical internal engineering documentation set, start with [docs/index.md](docs/index.md).

## Contribution Model

- Internal contributors should work from branches and open PRs against `main`.
- External contributors can use the standard fork-and-pull-request workflow.
- If a change affects the HTTP platform contract, deployment behavior, or branch state model, call that out explicitly in the PR description.

## Definition of Done

A change is ready to merge when:

- `pytest -v` passes
- the canonical docs are updated if behavior, CI/CD, or operations changed
- downstream contract changes for `mitosis-prototype` or `mitosis-control-plane` are documented
- public docs are updated when the user-facing behavior changed

## Review Expectations

- Prefer clear names over abbreviations.
- Prefer `logger` over `print`.
- Keep HTTP contract changes explicit and tested.
- Treat observability output and websocket behavior as real contracts, not incidental implementation details.

## Documentation Expectations

Update docs in the same change when you modify:

- route shapes or health behavior
- deploy status or target host assumptions
- branch initialization or DB handling
- anything where the upstream/public docs would now give the wrong mental model

## Canonical Docs

- [Architecture](docs/architecture.md)
- [Development](docs/development.md)
- [Testing](docs/testing.md)
- [CI/CD](docs/cicd.md)
- [Operations](docs/operations.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Fork divergence](docs/fork-divergence.md)
