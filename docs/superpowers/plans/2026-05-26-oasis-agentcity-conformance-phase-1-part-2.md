# Mitosis-OASIS ↔ AgentCity Conformance — Phase 1 Part 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the second half of Phase 1 — five per-contract adapters, scoreboard, report writer, end-to-end replay entrypoint, and the ADR-style Phase-1 verdict memo. Produces the first defensible "is mitosis-oasis conformant to AgentCity Legislation?" answer.

**Architecture:** Reuses the harness built in Part 1 (oracle, adapters, EventCollector, StateView, registry). Adds per-contract adapter modules under `test/conformance/adapter/`. Captures additional fixtures for LegislativePipeline / CodificationModule / VotingVerifier / GovernanceRegistry by running the existing `tools/capture_fixtures.py` from agent-city-contract (read-only — no modifications to that repo). Adds scoreboard aggregation + report writer + pytest entrypoint.

**Tech Stack:** Python 3.10–3.11 / Poetry / Pytest (oasis side); existing `tools/capture_fixtures.py` from agent-city-contract (run read-only).

**Spec:** `docs/superpowers/specs/2026-05-25-mitosis-oasis-agentcity-conformance-design.md`

**Part 1:** `docs/superpowers/plans/2026-05-25-oasis-agentcity-conformance-phase-1.md` (Tasks 1-10, shipped as mitosis-oasis PR #23, v0.8.1)

## Hard constraint

**DO NOT modify any file under `/Users/anbang/Documents/Antigravity/agentcity-workspace/`.** The capture script and Solidity entry point are frozen at branch `feat/conformance-fixture-capture`. This plan only runs the capture script read-only to produce fixtures into mitosis-oasis.

## Plan adjustment from original Part-1 plan

- **Task 11 (standalone ConstitutionalParameters adapter) merged into Task 12.** ConstitutionalReview test corpus exercises CP indirectly but no direct CP calls appear as `target_contract` in any fixture. CP becomes a GAP unless future fixture captures include a CP-direct test.
- **Task 9c amendment landed in Part 1.** Capture script now decodes function selectors → canonical signatures and labels deployed contract addresses. Fixtures emit `target_contract: "ConstitutionalReview"` and `function: "setQuorum(uint256)"` directly.
- **Codex review remediation landed in Part 1.** Oracle now compares `return_data` on ok + revert; state diff uses multiset comparison; fixture-corpus validation tests guard against fixture rot; EventCollector raises clear errors when unseeded; calldata decoder stub committed.

## Task index

| #   | Title                                         | Effort |
| --- | --------------------------------------------- | ------ |
| 12  | Adapter — ConstitutionalReview (+ CP fold-in) | 3 h    |
| 13  | Capture + Adapter — LegislativePipeline       | 3 h    |
| 14  | Capture + Adapter — CodificationModule        | 3 h    |
| 15  | Capture + Adapter — VotingVerifier            | 3 h    |
| 16  | Capture + Adapter — GovernanceRegistry        | 3 h    |
| 17  | Scoreboard aggregation                        | 2 h    |
| 18  | Report generator (conformance.md + .json)     | 2 h    |
| 19  | End-to-end replay entrypoint + conftest       | 2 h    |
| 20  | Phase-1 run + ADR-style memo + verdict commit | 2 h    |

Total: ~23 hours. Tasks 12-16 are independent (parallel-safe in spirit, but commit serially). Tasks 17-19 depend on 12-16. Task 20 is the final integration.

## Repo state at start of Part 2

- **mitosis-oasis** branch: `main` after PR #23 merge (`v0.8.1`)
- Create a new feature branch: `feat/agentcity-conformance-phase-1-part-2` off main
- Existing infrastructure (do NOT recreate):
  - `test/conformance/oracle/{schema,diff}.py` — pydantic + diff
  - `test/conformance/adapter/{registry,_base,event_capture,state_view,_calldata}.py` — scaffolding
  - `test/conformance/matrix/__init__.py` — empty, ready for scoreboard
  - `test/conformance/fixtures/legislation/ConstitutionalReview/*.json` — 15 fixtures

## Task 12: Adapter — ConstitutionalReview (with CP fold-in)

**Files:**

- Create: `mitosis-oasis/test/conformance/adapter/constitutional_review.py`
- Create: `mitosis-oasis/test/conformance/adapter/constitutional_parameters.py` (small — for any CP-direct calls discovered later)
- Test: `mitosis-oasis/test/conformance/tests/test_adapter_constitutional_review.py`

- [ ] **Step 1: Read both sources.**
  - Solidity: `agentcity-workspace/agent-city-contract/contracts/src/core/ConstitutionalReview.sol` and `ConstitutionalParameters.sol`
  - oasis: `mitosis-oasis/oasis/governance/constitutional.py` (the `ConstitutionalGuard` class + helpers)
  - Functions exercised by current fixtures: `reviewProposal(bytes32,bool,bytes32)`, `hasPassed(bytes32)`, `setConstitutionalParams(address)`, `pause()`, `getVerdict(bytes32)`, `constitutionalParams()`, `getReview(bytes32)`, `unpause()`

- [ ] **Step 2: Write the mapping comment block** at the top of `constitutional_review.py`. For each Solidity function, name its oasis counterpart (or mark GAP if none). Include event-name → oasis EventType mapping.

- [ ] **Step 3: Write the failing replay test.**

```python
"""Replay-driven test for ConstitutionalReview adapter."""

import json
from pathlib import Path

import pytest

from oasis.observatory.event_bus import EventBus
from test.conformance.adapter.event_capture import EventCollector
from test.conformance.adapter.registry import lookup
from test.conformance.oracle.diff import DiffOptions, diff_call
from test.conformance.oracle.schema import Fixture

# Import the adapter so it registers itself.
import test.conformance.adapter.constitutional_review  # noqa: F401


FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "legislation" / "ConstitutionalReview"


def _fixture_files() -> list[Path]:
    return sorted(FIXTURE_DIR.glob("*.json"))


@pytest.fixture(autouse=True)
def _isolate_bus(tmp_path: Path):
    EventBus.reset()
    EventBus.get_instance(db_path=tmp_path / "obs.db")
    yield
    EventBus.reset()


@pytest.mark.parametrize("fixture_path", _fixture_files(), ids=lambda p: p.stem)
@pytest.mark.conformance
def test_constitutional_review_replay(fixture_path: Path) -> None:
    fixture = Fixture.model_validate(json.loads(fixture_path.read_text()))
    for call in fixture.calls:
        fn = lookup(call.target_contract, call.function)
        if fn is None:
            pytest.skip(f"GAP: no adapter for {call.target_contract}.{call.function}")
        with EventCollector():
            actual = fn(call)
        verdict = diff_call(
            expected=call, actual=actual, opts=DiffOptions(),
            fixture_id=fixture_path.stem, power=fixture.power,
        )
        assert verdict.verdict == "PASS", verdict.diff
```

- [ ] **Step 4: Write the adapter.** Follow the structure shown in the Part-1 plan's Task 11 (template). Register each matched `(contract, function)` pair into `CONTRACT_FN_MAP`. For functions with no oasis counterpart, leave them OUT — the harness will report GAP at replay time.

- [ ] **Step 5: Run the replay test.** Real FAILs are conformance signal. Do NOT modify the test to make it pass. Document each FAIL in the Phase-1 memo (Task 20).

- [ ] **Step 6: Commit.**

```bash
git add test/conformance/adapter/constitutional_review.py \
        test/conformance/adapter/constitutional_parameters.py \
        test/conformance/tests/test_adapter_constitutional_review.py
git commit -m "feat(conformance): ConstitutionalReview adapter + CP fold-in + replay test"
```

## Task 13: Capture + Adapter — LegislativePipeline

**Files:**

- Touch: `mitosis-oasis/test/conformance/fixtures/legislation/LegislativePipeline/*.json` (capture)
- Create: `mitosis-oasis/test/conformance/adapter/legislative_pipeline.py`
- Test: `mitosis-oasis/test/conformance/tests/test_adapter_legislative_pipeline.py`

- [ ] **Step 1: Capture fixtures** (read-only invocation of the capture script):

```bash
cd /Users/anbang/Documents/Antigravity/agentcity-workspace/agent-city-contract
python3 tools/capture_fixtures.py \
    --contracts LegislativePipeline \
    --repo-root contracts \
    --out ../../mitosis-workspace/mitosis-oasis/test/conformance/fixtures/legislation
```

- [ ] **Step 2: Validate fixtures.**

```bash
cd /Users/anbang/Documents/Antigravity/mitosis-workspace/mitosis-oasis
.venv/bin/python -c "
from pathlib import Path
import json
from test.conformance.oracle.schema import Fixture
root = Path('test/conformance/fixtures/legislation/LegislativePipeline')
for f in root.glob('*.json'):
    Fixture.model_validate(json.loads(f.read_text()))
    print('OK', f.name)
"
```

- [ ] **Step 3: Read sources.**
  - Solidity: `agent-city-contract/contracts/src/core/LegislativePipeline.sol`
  - oasis: `oasis/governance/dag.py` + `oasis/governance/scheduler/` + `oasis/governance/clerks/` (Speaker handles MSG3 DAGProposal)

- [ ] **Step 4: Write mapping comment block.**
- [ ] **Step 5: Write failing replay test** (mirror Task 12's template, swap paths/names).
- [ ] **Step 6: Write the adapter.**
- [ ] **Step 7: Run replay; FAILs are signal.**
- [ ] **Step 8: Commit:**

```bash
git add test/conformance/adapter/legislative_pipeline.py \
        test/conformance/tests/test_adapter_legislative_pipeline.py \
        test/conformance/fixtures/legislation/LegislativePipeline/
git commit -m "feat(conformance): LegislativePipeline adapter + fixtures + replay test"
```

## Task 14: Capture + Adapter — CodificationModule

Same shape as Task 13. Specific paths:

- Solidity: `agent-city-contract/contracts/src/core/CodificationModule.sol`
- oasis: `oasis/governance/clerks/` (Codifier) + `oasis/governance/constitutional.py` (spec compilation)

Steps 1-8 identical to Task 13 with contract name `CodificationModule`. Commit message: `feat(conformance): CodificationModule adapter + fixtures + replay test`.

## Task 15: Capture + Adapter — VotingVerifier

Same shape. Specific paths:

- Solidity: `agent-city-contract/contracts/src/core/VotingVerifier.sol`
- oasis: `oasis/governance/voting.py` (Copeland method) + `oasis/governance/messages.py` (vote envelopes)

Steps 1-8 identical to Task 13 with contract name `VotingVerifier`. Commit message: `feat(conformance): VotingVerifier adapter + fixtures + replay test`.

## Task 16: Capture + Adapter — GovernanceRegistry

Same shape. Specific paths:

- Solidity: `agent-city-contract/contracts/src/core/GovernanceRegistry.sol`
- oasis: `oasis/governance/__init__.py` exports + `oasis/governance/state_machine.py` (9-state legislative engine)

Steps 1-8 identical to Task 13 with contract name `GovernanceRegistry`. Commit message: `feat(conformance): GovernanceRegistry adapter + fixtures + replay test`.

## Task 17: Scoreboard aggregation

**Files:**

- Create: `mitosis-oasis/test/conformance/matrix/scoreboard.py`
- Test: `mitosis-oasis/test/conformance/tests/test_scoreboard.py`

Pure-function aggregator per Part-1 plan Task 17. Reuse that task's code verbatim — no changes needed. Tests, implementation, and commit are unchanged from the original plan.

## Task 18: Report generator

**Files:**

- Create: `mitosis-oasis/test/conformance/matrix/report.py`
- Test: `mitosis-oasis/test/conformance/tests/test_report.py`

Per Part-1 plan Task 18. Reuse verbatim. Writes `conformance.json` + `conformance.md` to `test/conformance/reports/<contracts_sha>/`.

## Task 19: End-to-end replay entrypoint + conftest

**Files:**

- Create: `mitosis-oasis/test/conformance/test_replay.py`
- Create: `mitosis-oasis/test/conformance/conftest.py`

Per Part-1 plan Task 19. Import all 5 adapter modules at the top of `test_replay.py` so they register on test discovery. The single end-to-end test walks every fixture in `fixtures/legislation/**/*.json`, dispatches each call through the registry, collects verdicts, and writes the report.

Two adjustments from the original Task-19 template:

1. **Adapter imports updated:** import the 5 adapter modules that actually exist (no separate `constitutional_parameters` import — it's folded into `constitutional_review`).

```python
import test.conformance.adapter.constitutional_review   # noqa: F401  (+ CP fold-in)
import test.conformance.adapter.legislative_pipeline    # noqa: F401
import test.conformance.adapter.codification_module     # noqa: F401
import test.conformance.adapter.voting_verifier         # noqa: F401
import test.conformance.adapter.governance_registry     # noqa: F401
```

2. **Phase-1 gate excludes ERROR-on-bus-not-seeded:** if any test triggers the EventCollector "bus not seeded" error, that's a harness bug, not a conformance signal. The conftest fixture seeds the bus per-test; if a fixture bypasses conftest, ERROR is fatal per the original plan.

## Task 20: Phase-1 run + ADR-style memo + verdict commit

**Files:**

- Create: `mitosis-oasis/docs/conformance/phase-1-memo.md`
- Touch: `mitosis-oasis/docs/conformance/phase-1/{conformance.md,conformance.json}` (copies from reports/)

Per Part-1 plan Task 20. Run the end-to-end replay, copy the generated report into the docs tree, and write the human memo.

Exit gate (from spec §7): **Legislation conformance ≥ 95% PASS of non-GAP calls, ERROR = 0.**

If the gate fails: file the top failing functions as oasis-side tickets; do NOT silently lower the gate. The conformance signal is the deliverable — a 60% PASS is also a deliverable, just one that says "oasis governance has substantial drift from AgentCity legislation contracts and needs reconciliation."

Commit message: `docs(conformance): Phase-1 Legislation verdict memo + report snapshot`

## Acceptance criteria for Part 2 ship

- All five adapters land (or document their GAPs clearly).
- `pytest -m conformance` runs end-to-end, produces a real `conformance.md` + `conformance.json`.
- Phase-1 memo is written with real numbers (no `<placeholder>` strings).
- Verdict is honest: PASS, PARTIAL, or FAIL. Do not stretch a 70% PASS into "essentially passing."
- Memo links back to: spec, Part-1 plan, Part-2 plan, and any oasis-side tickets filed against failing functions.

## Out of scope, recorded as follow-ups

- **Phase 2:** Execution + Adjudication powers — separate plan after Phase 1 lands.
- **Phase 3:** Support contracts + CI integration — separate plan.
- **Fuzzing (Approach C):** opt-in after Phase 3 if FAIL clusters suggest under-tested input spaces.
- **`eth-abi` install:** the calldata decoder stub activates once `eth-abi` is added to oasis deps. Track as a small follow-up commit.
- **Live conformance mode:** for the Synergy Demo. Recorded in spec §7 as Phase 5.
- **Fixture corpus refresh on contract changes:** the capture script is in agent-city-contract; when AgentCity contracts change, that repo's CI should publish a fresh corpus as an artifact. Set up in a future cross-repo sync.

## Risks

- **GAP rate may be high.** Especially for VotingVerifier (Copeland method differences) and CodificationModule (spec-compilation semantics). High GAP rate is honest, not a failure — file tickets and ship the memo.
- **Multiple FAILs may share a root cause** in oasis (e.g., wrong event payload structure across many functions). When clustering FAILs, look for the upstream fix.
- **Fixture coverage of GovernanceRegistry may be thin** since most of its semantics emerge during integration. Use any fixtures captured, document gaps in the memo.

## Total budget for Part 2

~23 engineer-hours. Phase 1 total (Part 1 + Part 2): ~63 hours, vs the spec's 80-hour estimate. Tracking under budget despite the Codex review remediation work in Part 1.
