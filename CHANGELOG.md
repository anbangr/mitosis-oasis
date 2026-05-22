# Changelog

All notable changes to this project will be documented in this file.

## [0.5.0] — 2026-05-21 — Bundle 2 (Adjudicator Accountability)

### Added

- **Impeachment** (spec §2.1-2.2): `POST /api/adjudication/impeach`
  endpoint, EIP-712-gated, requires ceil(2q/3) supermajority of valid
  signatures. Accept → ban target (both registries) + 100% stake slash
  to treasury + on-chain evidence CID.
- **Watchdog** (spec §2.4): hourly apscheduler job; z-score ≥ 2.0
  anomaly detection on adjudicator approval-rate and freeze-lift-rate
  in a 30-day rolling window. Calibration mode below 10 decisions.
- **Rotation policy** (spec §1.2): `enforce_rotation()` blocks
  > `rotation_max_consecutive` (default 2) consecutive same-adjudicator
  > decisions of the same type.
- **COI recusal** (spec §1.2): `is_conflicted()` rejects adjudicators
  who own any agent in the current mission.
- **72-hour freeze auto-lift** (spec §2.4): 5-minute apscheduler sweep
  auto-unfreezes any freeze older than `max_freeze_duration_ms` without
  `manual_extension=true`.
- New tables: `adjudicator_registry`, `impeachment`, `watchdog_anomaly`.
- New columns: `agent_registry.banned`, `adjudication_decision.frozen_at`,
  `adjudication_decision.manual_extension`, `adjudication_decision.issued_by_did`.
- New constitution params: `adjudicator_quorum`, `adjudicator_stake`,
  `watchdog_zscore_threshold`, `watchdog_window_days`,
  `watchdog_anomaly_threshold`, `max_freeze_duration_ms`,
  `rotation_max_consecutive`.
- ≥5 new spec_v097 tests (ADJ-097, 098, 099, 110, 111).

### Breaking

- `sanctions._record_decision()` now requires `issued_by_did`
  (the adjudicator, not just the target).
- `POST /api/adjudication/impeach` is EIP-712-gated. Caller must send
  `X-EIP712-Signature` + `X-EIP712-Signer` headers.

## [0.4.0] - 2026-05-20

**Bundle 1 — Cryptographic Foundation release.** Replaces v0.2.x mock crypto
(empty signatures, `did:mock:` strings, no typed-data) with production-grade
Ed25519 + secp256k1 + W3C `did:key` + EIP-712 typed-data binding across the
entire OASIS protocol stack.

### Added
- **Ed25519 signing primitives** (`oasis/crypto/ed25519.py`) via `pynacl ^1.5.0`:
  `generate_keypair()`, `keypair_from_seed()`, `sign()`, `verify()` — deterministic
  test fixtures derived from `sha256(test_node_name)`.
- **secp256k1 primitives** (`oasis/crypto/secp256k1.py`) wrapping
  `eth-account >=0.10.0,<0.14.0` for EIP-712 envelope signing and recovery.
- **W3C `did:key` resolver** (`oasis/crypto/did.py`) — pure-Python, multicodec
  `0xed01` + base58-btc encoding, no Rust toolchain required (`base58 ^2.1.0`).
- **EIP-712 typed-data layer** (`oasis/crypto/eip712.py` + `typed_data.py`) with
  full envelope digest via `Account.sign_message(encode_typed_data(...))` —
  signatures are bitwise-identical to MetaMask / Rabby / Frame for the same
  typed data. Exposes `SanctionTypedData`, `ConstitutionAmendmentTypedData`,
  and `ImpeachmentTypedData` schemas.
- **EIP-712 FastAPI middleware** (`oasis/api_auth.py`) — `require_eip712_sig`
  dependency factory gates Rules Hub (`POST /slash`, `POST /freeze`) and
  Override Panel (`PUT /constitution`) binding actions via
  `X-EIP712-Signature` + `X-EIP712-Signer` headers.
- **`agent_registry.public_key` column** — 32-byte Ed25519 pubkey stored as
  lowercase hex, populated at agent registration.
- **`message_log.signature` + `message_log.payload_json` columns** — detached
  Ed25519 sig (128-char hex) and full Pydantic JSON stored alongside the
  canonical signed bytes.
- **`oasis.governance.messages.canonical_signed_bytes(msg)` helper** — single
  source of truth for what bytes are signed; uses `json.dumps(sort_keys=True,
  separators=(",", ":"))` for deterministic cross-platform canonicalisation.
- **Clerk `did:key` keypair persistence** (`oasis/governance/clerks/bootstrap.py`)
  via `ensure_clerk_keys(db_path, keys_dir)` — mints or reloads Ed25519 keypairs
  for Registrar, Speaker, Regulator, Codifier; deletes legacy
  `did:oasis:clerk-{role}` rows and re-inserts under `did:key:zXXX` with
  `public_key` populated. Key files written at mode `0o600`, directory at
  `0o700`; `data/clerk_keys/` is gitignored.
- **Deterministic test fixtures** (`test/conftest.py`): `ed25519_keypair` and
  `eth_account_signer` fixtures seeded from test node names.
- **≥10 spec_v097 rubric tests** across IDN-114 (`did:key` resolution),
  IDN-117 (Ed25519 attestation), ADJ-105 (EIP-712 binding), ADJ-106
  (session-auth observation).

### Breaking
- **Clerk DIDs migrated** from `did:oasis:clerk-{role}` to `did:key:zXXX`
  derived from persisted Ed25519 pubkeys. Any caller hardcoding the old
  strings must look up the role via `ensure_clerk_keys` instead.
- **Agents registering without a `public_key`** are rejected by
  `verify_identity`. `IdentityAttestation.agent_did` must start with
  `did:key:`; legacy `did:mock:` / `did:oasis:` formats are rejected.
- **All MSG2–MSG7 signature fields** tightened to exactly 64-byte lowercase hex
  (`min_length=128, max_length=128, pattern=r"^[0-9a-f]{128}$"`) — no more
  empty-string placeholder signatures.
- **`message_log.payload` now carries canonical signed bytes (hex)** rather than
  Pydantic JSON. JSON moved to `message_log.payload_json`. Any reader doing
  `json.loads(row["payload"])` must switch to `row["payload_json"]`.
- **Slash / freeze endpoints** accept canonical `SanctionTypedData` body
  `{"target_did", "amount_wei", "reason", "nonce"}` — the legacy `amount: float`
  field is removed. Constitution PUT accepts
  `{"param_name", "param_value", "nonce"}`.
- **All binding routes** require `X-EIP712-Signature` + `X-EIP712-Signer`
  headers; read-only routes (`GET /treasury`, `/decisions`, `/alerts`) remain
  unprotected.

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
