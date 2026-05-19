# Changelog

All notable changes to this project will be documented in this file.

## [0.3.0] - 2026-05-19

**Bundle 0 — AgentCity v0.97 parity bug-fix release.** Closes nine
issues surfaced by the 2026-05-18 coverage audit (oasis-coverage-audit-2026-05-18.md)
and its codex addendum, landing nine PRs (#4–#11) and bringing all three version surfaces back into lockstep at 0.3.0.

**Breaking change:** version surfaces previously drifted (pyproject.toml=0.2.6,
oasis/__init__.py=0.2.5, oasis/api.py=0.4.0). This release brings them to a single
canonical 0.3.0. Consumers pinning to the API version "0.4.0" must downgrade their
pin string to "0.3.0"; the FastAPI surface itself is backwards compatible.

### Fixed
- **spec §1.7** Raise `quorum_threshold` constitutional default from 0.51 → 0.60 (PR #7).
- **spec §2.2-2.3** Split the conflated `reputation_alpha` knob: introduced `reputation_lambda` for EMA smoothing per spec §2.2-2.3 so adjudication no longer shares a coupling with settlement (PR #5).
- **spec §2.6** Repurposed `reputation_alpha` as the settlement reputation-multiplier slope per spec §2.6; `SettlementCalculator` now reads it independently of the EMA path (PR #5).
- **spec §1.7** Identity-quorum guard no longer counts `IDENTITY_ATTESTATION` rows from inactive or non-producer agents; both quorum and reputation-floor queries now INNER JOIN `agent_registry` filtered on `agent_type = 'producer' AND active = 1` (PR #11).
- **spec §1.2** Bid scoring formula corrected to the spec-canonical `0.6 · Q + 0.4 · P` weighting (was previously implementation-drifted) (PR #9).
- **spec §1.5** Tier 3 PoP timeout floor raised from 30s → 5 minutes to match the spec-mandated proof-of-personhood execution budget (PR #8).
- **spec §8.5** Identity-quorum guard `msg_type` string drift fixed; state-machine query now reads the canonical `IDENTITY_ATTESTATION` literal that the Registrar actually writes (was reading legacy `IdentityVerificationResponse` and silently failing) (PR #6).

### Added
- Spec-v0.97 test package bootstrap (`test/spec_v097/`) with shared fixtures and constitutional-constant seeds (PR #4).
- 50/50 slash split: slashed stake now divides between `treasury` and a new `insurance_pool` ledger (spec §1.4), each carrying a `decision_id` FK to the originating `adjudication_decision` row for audit-trail reconstruction (PR #10).
- End-to-end legislative happy-path waypoint smoke test (`test/e2e/test_full_protocol_smoke.py`, 10 tests) covering quorum, reputation floor, edge cases, and inactive-attester attack vector (PR #11).

### Changed
- `SanctionEngine.reduce_reputation` now uses `config.reputation_lambda` for EMA smoothing.
- `SettlementCalculator` now uses `config.reputation_lambda` for EMA smoothing.
- Extracted `_compute_ema` helper on `SanctionEngine` for testability.

### Source

- Coverage audit: [`mitosis-paper/agentcity-ref/oasis-coverage-audit-2026-05-18.md`](../mitosis-paper/agentcity-ref/oasis-coverage-audit-2026-05-18.md)
- Codex addendum: [`mitosis-paper/agentcity-ref/oasis-coverage-audit-2026-05-18-addendum-codex.md`](../mitosis-paper/agentcity-ref/oasis-coverage-audit-2026-05-18-addendum-codex.md)
- Design spec: [`docs/superpowers/specs/2026-05-18-agentcity-v097-parity-design.md`](docs/superpowers/specs/2026-05-18-agentcity-v097-parity-design.md)
- Plan: [`docs/superpowers/plans/2026-05-18-bundle-0-bug-fix.md`](docs/superpowers/plans/2026-05-18-bundle-0-bug-fix.md)

## [0.2.6] - 2026-05-18

### Fixed
- Split `reputation_alpha` into separate `reputation_alpha` (settlement multiplier slope) and `reputation_lambda` (EMA smoothing) parameters to prevent unintended coupling between adjudication and settlement logic.

### Added
- RED-gate tests verifying α/λ parameter independence (`test/adjudication/test_reputation_parameters.py`).
- Spec-v0.97 test infrastructure with shared fixtures and constitutional constants (`test/spec_v097/`).
- Additional constitutional parameters: `fairness_minimum`, `protocol_fee_bps`, `reputation_alpha`.

### Changed
- `SanctionEngine.reduce_reputation` now uses `config.reputation_lambda` for EMA smoothing.
- `SettlementCalculator` now uses `config.reputation_lambda` for EMA smoothing.
- Extracted `_compute_ema` helper on `SanctionEngine` for testability.
