# Fork Divergence

`mitosis-oasis` is a hard fork of CAMEL-AI OASIS. Upstream context is helpful, but it is not authoritative for current production behavior.

## Intentional Divergences

- Embedded agent architecture replaced by an external-agent HTTP service model
- FastAPI API layer added as the primary integration surface
- governance/execution/adjudication/observatory branch split added
- SQLite-backed coordination and observability state expanded for Mitosis workflows

## Upstream Material You Should Treat Carefully

- legacy docs that describe embedded CAMEL agents as the main integration model
- tests under upstream-oriented paths that this fork explicitly excludes
- docs that do not mention the HTTP platform contract

## Documentation Rule

When internal engineering docs and upstream-style public docs diverge, the internal engineering docs in this canonical set win for production work.
