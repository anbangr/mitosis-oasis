# Mitosis-OASIS ↔ AgentCity Protocol Conformance — Design

**Date:** 2026-05-25
**Status:** Draft, pending user review
**Author:** Anbang (via `/superpowers:brainstorming`)
**Related:**

- `docs/adr/ADR-0003-default-llm-provider-for-experiments.md` (prior experiment pattern)
- `~/Documents/Antigravity/netx-workspace/netx-gstack/ECOSYSTEM.md` v10 (Separation of Power consistency mandate)
- `mitosis-gstack/inbox/2026-05-21-synergy-demo-agent-pick.md`
- `agentcity-workspace/agent-city-contract/contracts/src/` (canonical source of truth)

---

## 1. Problem

`mitosis-oasis/` is a Python re-implementation of the **Separation of Power** semantics that AgentCity implements on-chain in Solidity. Modules in `oasis/governance/`, `oasis/execution/`, and `oasis/adjudication/` mirror the AgentCity contracts (Legislation / Execution / Adjudication branches). ECOSYSTEM.md v10 (decision 2026-04-20) requires that this terminology and these semantics be byte-for-byte consistent across artifacts — including code.

There is no evidence that the oasis Python implementation actually behaves the same way as the contracts on equivalent inputs. The Synergy Demo (gate 2026-06-04, ECOSYSTEM.md v10) makes that drift load-bearing: a Mitosis-sourced agent that participates in an AgentCity workflow must respect the same governance / execution / adjudication contracts that the on-chain side enforces.

**Question this design answers:** how do we run structured, ADR-style experiments that verify mitosis-oasis is protocol-conformant with the AgentCity Solidity contracts on the Separation of Power surface?

---

## 2. Scope and non-scope

### In scope

- **Protocol surface:** Separation of Power semantics — `oasis/governance/` (Legislation), `oasis/execution/` (Execution), `oasis/adjudication/` (Adjudication), plus the supporting `AgentRegistry`, `ReputationRegistry`, `Treasury`, `DEXWhitelist` contracts.
- **Ground truth:** AgentCity Solidity contracts in `agent-city-contract/contracts/src/core/` (~27 core contracts + matching interfaces in `contracts/src/interfaces/`).
- **Rigor level:** exhaustive function-level coverage — every external/public function on every SoP-relevant contract is either matched by an oasis adapter (PASS/FAIL graded) or surfaced as a documented GAP.
- **Diff granularity:** events (name + args, in order) + observable end-state (mappings, balances, role assignments, status enums). Revert reasons captured but not asserted by default.
- **Execution environment:** oasis-only at experiment time (no live EVM). Contracts execute once, offline, to capture reference fixtures.
- **Reporting:** ADR-style `conformance.md` memo + machine-readable `conformance.json` per run. Per-power pass-threshold gates.

### Out of scope

- Mission lifecycle / escrow conformance as a separate surface (mission semantics are folded into the Execution power).
- Gas accounting, Solidity storage-slot equality, and revert-reason equality. All three are pre-wired into the fixture schema as opt-in run flags but disabled by default.
- Property-based fuzzing of contract inputs (recorded as a Phase-4 follow-up; "Approach C" from the brainstorm).
- "Live conformance" mode that emits verdicts during the Synergy Demo flow at runtime (recorded as a Phase-5 follow-up in §7).
- Backend REST / SDK surface conformance, identity+reputation+staking economic conformance — these are separate surfaces requiring their own designs.
- Modifying AgentCity contracts or the Foundry test corpus.

---

## 3. Architecture

```
agent-city-contract/                          mitosis-oasis/
  test/ (198 Foundry tests)                     test/conformance/
        │                                        ├── fixtures/         ← committed JSON corpus
        │  one-time / on contract change         │     legislation/
        │  invoke trace-fixture-generator        │     execution/
        ▼                                        │     adjudication/
  forge test --trace + tracer hook ──────────►   │     support/
  (script/CaptureFixtures.s.sol +                ├── adapter/          ← oasis call dispatcher
   tools/capture_fixtures.py)                    ├── oracle/           ← fixture loader + diff
        │                                        ├── matrix/           ← coverage + scoreboard
        │   fixture JSON per call:               └── reports/<sha>/
        │     selector, args, msg.sender,              ├── conformance.md
        │     events[], state_delta[]                  └── conformance.json
        ▼                                       docs/conformance/
  per-test JSON files                             power_map.json       ← contract → power
```

**Three units, each with one job, communicating through the fixture JSON schema as a contract.**

1. **Trace-fixture generator** — lives in `agent-city-contract/script/CaptureFixtures.s.sol` + `agent-city-contract/tools/capture_fixtures.py`. Runs Foundry's existing 198-test corpus once with `vm.recordLogs()` and storage snapshotting. Emits per-test JSON files into `mitosis-oasis/test/conformance/fixtures/`. Idempotent; only re-runs when `contracts_sha` changes. Optionally republished by a contract-side CI job as an artifact.
2. **Oasis replay harness** — `mitosis-oasis/test/conformance/test_replay.py` (pytest, `-m conformance`). Loads each fixture, dispatches calls through the adapter registry, captures oasis-emitted events + observable state, runs the oracle.
3. **Conformance matrix + scoreboard** — `mitosis-oasis/test/conformance/matrix/`. Aggregates per-call verdicts into per-power and per-contract rollups; emits `conformance.md` (ADR-style memo) and `conformance.json` (machine-readable rollup) into `mitosis-oasis/test/conformance/reports/<contracts_sha>/`.

The contract repo is read-only from oasis's perspective at experiment time. The only cross-repo coupling is the offline fixture-generator invocation.

---

## 4. Fixture JSON schema

One file per Foundry test. Path:
`test/conformance/fixtures/<power>/<primary_contract>/<foundry_test_name>.json`.

```json
{
  "fixture_version": 1,
  "source": {
    "foundry_test": "MissionFactoryTest::test_createMission_happy_path",
    "contracts_sha": "0xabc…",
    "captured_at": "2026-05-25T12:34:56Z"
  },
  "power": "execution",
  "primary_contract": "MissionFactory",
  "calls": [
    {
      "idx": 0,
      "target_contract": "AgentRegistry",
      "selector": "0x…",
      "function": "register(address,bytes32)",
      "args": ["0xProvider", "0x…cid"],
      "msg_sender": "0xProvider",
      "value_wei": "0",
      "result": { "kind": "ok", "return_data": ["1"] },
      "events": [
        {
          "name": "AgentRegistered",
          "args": { "agent": "0xProvider", "tokenId": "1", "uri": "0x…cid" }
        }
      ],
      "state_delta": [
        {
          "kind": "mapping_set",
          "contract": "AgentRegistry",
          "name": "ownerOf",
          "key": "1",
          "value": "0xProvider"
        },
        {
          "kind": "counter_inc",
          "contract": "AgentRegistry",
          "name": "totalSupply",
          "delta": "1"
        }
      ],
      "revert_reason": null
    }
  ]
}
```

### Schema invariants

- `state_delta` is **semantic, not storage-slot**. Tracer translates raw `SSTORE`s into structured records (`mapping_set`, `counter_inc`, `field_set`, `array_push`, `array_pop`) using Foundry's storage layout output. Required because the Python re-implementation does not share Solidity storage layout.
- `result.kind ∈ {"ok", "revert"}`. `revert_reason` is always captured but only asserted when the run is invoked with `--strict-reverts`. Default diff level ignores it.
- `power ∈ {"legislation", "execution", "adjudication", "support"}` is assigned via a static `docs/conformance/power_map.json` keyed by contract name. Single source of truth for branch assignment; used by both generator and scoreboard.
- Addresses are lowercased hex strings. Integers (uint of any width) are decimal strings. Bytes are `0x`-prefixed hex strings. This normalization is applied at capture time so the oracle never has to negotiate type coercion.

---

## 5. Oasis adapter + oracle

### Adapter registry

`test/conformance/adapter/registry.py` holds a single committed table:

```python
CONTRACT_FN_MAP: dict[tuple[str, str], Callable] = {
    ("MissionFactory", "createMission(...)"): MissionFactoryAdapter.create_mission,
    ("AgentRegistry",  "register(...)"):       AgentRegistryAdapter.register,
    # …
}
```

A missing entry → that fixture call is reported as `GAP` (no oasis counterpart), not `FAIL`. The map is the single source of truth for "what oasis claims to implement." Adding a function to the map is the only way to opt it into PASS/FAIL grading.

### Per-contract adapters

One file per contract under `test/conformance/adapter/` (`mission_factory.py`, `agent_registry.py`, …). Each adapter:

1. Receives the call's args as raw fixture-typed values (lowercased hex addresses, decimal-string integers, hex bytes) and converts to oasis-native types.
2. Invokes the matching oasis Python function.
3. Captures events through a context-managed `EventBus.record()` block.
4. Captures observable state through a `StateView.snapshot_diff()` pre/post.
5. Returns `CallResult { events: list, state_delta: list, ok: bool, revert: str | None }`.

### Oracle

`test/conformance/oracle/diff.py` is a pure comparator. Given `(expected: FixtureCall, actual: CallResult)` it returns a structured verdict:

- **Event sequence equality:** names in order, args equal under typed normalization (addresses lowercased, ints as strings, bytes as `0x…` hex). Extra or missing events → `FAIL` with a structured diff payload.
- **State delta equality:** every fixture delta entry must appear in `actual.state_delta` (unordered set under a normalized key). Extra deltas in `actual` are **allowed** by default (oasis may track ancillary state); flippable via `--strict-state-superset` if needed.
- **Result kind:** `ok` vs `revert` must match. `revert_reason` ignored unless `--strict-reverts`.

### Scaffolding required in oasis runtime

Two small additions to oasis itself (one-time, mechanical edits):

- **`EventBus`** — a contextvar-scoped recorder. SoP modules publish to it whenever they perform a Solidity-equivalent emission. Today most oasis modules emit through `oasis.observability` or inline `dict()` returns; we standardize on `bus.emit(name, **args)`. Touches every module under `governance/ | execution/ | adjudication/`, but mechanically (no behavior change).
- **`StateView`** — a snapshot helper that produces a normalized `{contract, name, key} → value` view of oasis in-memory state. Lives in `test/conformance/adapter/state_view.py` so it's test-only and does not pollute runtime.

### Deliberate non-features

- No EVM emulation, no Solidity storage layout in Python, no gas accounting.
- No multi-process or async coordination — replay is single-threaded per fixture for determinism.
- No automated GAP closing. A reported GAP is a human decision to implement-or-accept.

---

## 6. Conformance matrix, scoreboard, gates

### Inputs

A flat list of per-call results from the harness:

```
{ fixture_id, test_name, call_idx, power, contract, function,
  verdict ∈ {PASS, FAIL, GAP, ERROR}, diff?: {...} }
```

`ERROR` = harness exception (adapter raised, oasis crashed). Distinct from `FAIL` (oasis ran fine, just produced wrong events/state).

### Outputs

**`conformance.json`** — machine-readable, full per-call list plus rollup:

```json
{
  "contracts_sha": "0xabc…",
  "run_id": "2026-05-25T12:34Z",
  "fixture_count": 198,
  "call_count": 1842,
  "by_power": {
    "legislation": {
      "pass": 312,
      "fail": 4,
      "gap": 18,
      "error": 0,
      "pct_pass": 0.93
    },
    "execution": {
      "pass": 689,
      "fail": 12,
      "gap": 31,
      "error": 0,
      "pct_pass": 0.94
    },
    "adjudication": {
      "pass": 401,
      "fail": 9,
      "gap": 22,
      "error": 1,
      "pct_pass": 0.92
    },
    "support": {
      "pass": 320,
      "fail": 2,
      "gap": 11,
      "error": 0,
      "pct_pass": 0.96
    }
  },
  "by_contract": {},
  "top_failures": [],
  "gap_list": []
}
```

**`conformance.md`** — ADR-style memo, same shape as ADR-0003 follow-ups: status line, contracts-sha, headline scoreboard table, per-power threshold check, top-10 failing functions with one-line diff summaries, gap list grouped by contract, pending-work section.

### Pass thresholds

| Power        | PASS threshold (of non-GAP calls) | GAP threshold |
| ------------ | --------------------------------- | ------------- |
| Legislation  | ≥ 95% PASS                        | informational |
| Execution    | ≥ 95% PASS                        | informational |
| Adjudication | ≥ 95% PASS                        | informational |
| Support      | ≥ 90% PASS                        | informational |

**`pct_pass` is computed against `PASS + FAIL + ERROR`, excluding `GAP`.** Gaps are a coverage axis, separate from correctness. A run with 100% PASS and 80 GAPs means "what oasis implements is correct, but coverage is incomplete" — different remediation than "things are implemented wrong." Both numbers are surfaced in the memo.

**`ERROR > 0` is fatal**, regardless of pct_pass. The harness must run cleanly for percentages to be meaningful.

### Multi-seed policy

Replay is deterministic — no LLM, no randomness in oasis SoP code by current design. One run per `contracts_sha` is sufficient. If oasis later introduces stochastic adjudication paths (e.g. randomized juror selection), add a seed axis at that time.

### Where it runs

`pytest -m conformance` under `mitosis-oasis/`. Wired into the existing prototype CI runner (`ci-prototype` on the CI droplet). Artifacts written to `mitosis-oasis/test/conformance/reports/<contracts_sha>/`.

---

## 7. Phasing

Three phases, each independently shippable. Each phase ends with an ADR-style memo and a verdict; the next phase only starts after the prior phase passes its exit gate.

### Phase 1 — Harness scaffolding + Legislation power end-to-end

**Scope.** Build fixture generator, oasis `EventBus` + `StateView` abstractions, adapter registry, oracle, scoreboard. Apply to legislation contracts only: `ConstitutionalParameters`, `ConstitutionalReview`, `LegislativePipeline`, `CodificationModule`, `VotingVerifier`, `GovernanceRegistry`. ~6 contracts × ~10 functions ≈ 60 functions in the initial matrix.

**Why first.** The harness is the riskiest piece. Validating event capture, state-delta translation, and adapter shape on one branch prevents reworking ~26 adapters when an abstraction is wrong.

**Exit gate.** Legislation conformance ≥ 95% PASS of non-GAP calls. ERROR = 0. Gap list documented. `conformance.md` v1 committed.

**Estimated effort.** ~1 engineer-week harness + ~1 engineer-week adapter wiring.

### Phase 2 — Execution + Adjudication coverage

**Scope.** Apply the validated harness to the remaining two SoP powers.

- Execution: `Mission`, `MissionFactory`, `CollaborationContract`, `ProducerContract`, `SettlementModule`, `VerificationModule`, `GateModule`, `StakingRegistry`.
- Adjudication: `AdjudicationCase`, `AdjudicatorRegistry`, `Guardian`, `SanctionRegistry`, `CollusionEvidence`, `ContagionEvidence`, `EvidenceAnchor`.

**Expected risk.** Adjudication has the deepest semantic complexity and likely the highest GAP rate — several adjudication primitives are partially implemented in oasis today.

**Exit gate.** Each power ≥ 95% PASS. Gap list filed as oasis-side tickets for the most-referenced gaps.

**Estimated effort.** ~2 engineer-weeks.

### Phase 3 — Support contracts + CI integration

**Scope.** Cover `AgentRegistry`, `ReputationRegistry`, `Treasury`, `DEXWhitelist`. Wire `pytest -m conformance` into oasis CI on a contract-source-change trigger (contract-repo CI job publishes fixtures as an artifact → oasis CI consumes → run conformance). Add nightly run that posts the matrix to `mitosis-oasis/README.md`.

**Exit gate.** Support ≥ 90% PASS. CI green. Scoreboard visible in README. Drift detection working (contracts-sha mismatch fails the run loudly).

**Estimated effort.** ~1 engineer-week.

### Total budget

~4 engineer-weeks for the full three-phase exhaustive matrix. Phase 1 alone delivers the first defensible "is mitosis-oasis conforming to AgentCity?" answer (for legislation), which is the Synergy Demo prerequisite.

### Out of scope, recorded as follow-ups

- **Phase 4 (fuzz):** property-based input fuzzing on top of the fixture corpus. Opt-in after Phase 3 if FAIL clusters suggest under-tested input spaces.
- **Phase 5 (live):** "live conformance" mode that runs the same adapter inline with the Synergy Demo flow and emits a per-mission verdict at settlement time. The `EventBus` + `StateView` abstractions are designed to be reusable here.
- **Strict modes:** storage-exact equality and revert-reason matching — pre-wired into the fixture schema, flippable via `--strict-state-superset` / `--strict-reverts` run flags when desired.

---

## 8. Risks and mitigations

| Risk                                                                    | Mitigation                                                                                                                                       |
| ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| 198 Foundry tests don't exercise every public function (coverage holes) | Generator emits per-function exercise count. Holes appear as "function never appears in any fixture" — explicit, not silent.                     |
| Foundry storage-layout output drifts between solc versions              | Pin solc version in `foundry.toml`; embed `solc_version` in fixture `source` block; CI mismatch fails the run.                                   |
| Adapter mistranslates fixture args                                      | Type normalization fixed at capture time (lowercased hex, decimal-string ints). Adapters use one shared deserializer.                            |
| Oasis emits ancillary events not in fixtures (false FAIL)               | Default oracle allows extra events to be **missing-from-actual is FAIL, extra-in-actual is FAIL** — adjust default if needed (see open Q below). |
| Oasis stores state ancillary to the contract model                      | `state_delta` superset mode is the default — extra-in-actual allowed. Strict mode flippable.                                                     |
| Contract source changes invalidate fixtures                             | Fixture `contracts_sha` is checked at harness startup. Mismatch → fast-fail with "regenerate fixtures" message.                                  |
| Tracer fails for `DELEGATECALL` / library calls                         | Capture covers external/public entrypoints only. Internal library calls are folded into the caller's state_delta.                                |

---

## 9. Open questions resolved during brainstorm

- **Protocol surface:** Separation of Power semantics (governance / execution / adjudication + supporting registries).
- **Ground truth:** AgentCity Solidity contracts (operational truth).
- **Rigor:** exhaustive function-level coverage.
- **Reference capture:** from existing Foundry tests (one-shot, offline).
- **Runtime:** oasis-only at experiment time; no live EVM.
- **Diff level:** events + observable state; revert reasons captured but not asserted by default.
- **Approach:** A (Foundry-replay fixture corpus + oasis-only re-execution).

---

## 10. Open question for review

One small policy question deliberately left for review:

**Q1. Default oracle behavior for extra events emitted by oasis but absent in the fixture.**

The current spec says events are an ordered sequence; extra events in `actual` cause `FAIL`. That mirrors the state-delta strict-superset flag in its strictest position. Alternative: allow extra events by default (oasis may publish to its observability bus more verbosely than Solidity does), with a `--strict-event-set` flag to flip to the strict policy.

Recommendation: **default to strict event-set equality** (extra events = FAIL). Rationale: Solidity event emission is intentional and semantically meaningful; an extra event in oasis usually means oasis is doing something the contract doesn't, which is the kind of drift we want to catch. If real false-positives appear during Phase 1, flip the default then.

Open for the user to override during spec review.
