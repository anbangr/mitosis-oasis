# CLAUDE.md — Mitosis OASIS

AI assistant guidance for the Mitosis OASIS codebase. Read this before making
any changes.

---

## Project Overview

**Mitosis OASIS** is a simulation platform for testing the AgentCity governance
protocol. It is a fork of `camel-ai/oasis` with CAMEL dependencies removed and
replaced by a FastAPI HTTP API layer. External agents (ZeroClaw/OpenClaw)
interact with the platform via REST rather than being embedded agents.

- **Version**: 0.2.5
- **Python**: 3.10–3.11 (constrained in `pyproject.toml`)
- **Package manager**: Poetry
- **API framework**: FastAPI + Uvicorn

---

## Repository Layout

```
mitosis-oasis/
├── oasis/                  # Main application source
│   ├── governance/         # Legislative branch (sessions, proposals, voting)
│   ├── execution/          # Execution branch (task routing, commitment, runners)
│   ├── adjudication/       # Adjudication branch (sanctions, settlement, treasury)
│   ├── observatory/        # Dashboard branch (event bus, WebSocket, web UI)
│   ├── social_platform/    # Social simulation engine
│   ├── social_agent/       # Agent graph
│   ├── clock/              # Time management
│   ├── api.py              # FastAPI app entry point
│   ├── server.py           # Uvicorn launcher (python -m oasis.server)
│   └── config.py           # PlatformConfig dataclass
├── test/                   # Pytest test suite
│   ├── governance/         # Governance unit + E2E tests
│   ├── execution/          # Execution tests
│   ├── adjudication/       # Adjudication tests
│   ├── observatory/        # Observatory tests
│   ├── cross_branch/       # Cross-branch integration tests
│   ├── api/                # API-level tests
│   ├── infra/              # Infrastructure tests (recsys excluded from CI)
│   └── conftest.py         # Root fixtures
├── skills/
│   └── mitosis-governance/ # 15 HTTP tools for ZeroClaw agents (SKILL.toml)
├── docs/                   # Documentation site
├── deploy/                 # Docker Compose config
├── licenses/               # License template + update_license.py
├── Dockerfile
├── pyproject.toml          # Poetry config + pytest config
├── .pre-commit-config.yaml
├── README.md
├── CONTRIBUTING.md
└── IMPLEMENTATION_PLAN.md  # 17-phase roadmap
```

### Each branch module contains the same set of files

| File | Purpose |
|------|---------|
| `schema.py` | SQLite table definitions (`CREATE TABLE` + helpers) |
| `endpoints.py` | FastAPI router with REST endpoints |
| `messages.py` | Pydantic request/response models |
| `*.py` (business logic) | Domain logic (voting, fairness, sanctions, etc.) |

---

## Development Commands

### Setup

```bash
pip install poetry
poetry install
```

System packages required for the Cairo / igraph dependencies:

```bash
apt-get install -y libcairo2-dev pkg-config libigraph-dev
```

### Run the server

```bash
# Development (auto-reload)
python -m oasis.server

# Or directly
uvicorn oasis.api:app --host 0.0.0.0 --port 8000 --reload
```

### Run tests

```bash
# All tests
pytest

# Specific branch
pytest test/governance/
pytest test/execution/
pytest test/adjudication/
pytest test/observatory/
pytest test/cross_branch/

# Verbose
pytest -v
```

Tests that are **excluded from CI** (do not run these and expect them to pass):
- `test/infra/recsys` — requires external TwHIN model
- `test/agent` — removed agent tests

### Linting & formatting

```bash
# Run all pre-commit hooks
pre-commit run --all-files

# Individual tools
ruff format .          # code formatting
ruff check . --fix     # linting with auto-fix
flake8 .               # PEP8 check
isort .                # import sorting
mdformat README.md     # markdown formatting
```

The pre-commit hooks also run a **license header checker** — every `.py` file
must begin with the Apache 2.0 header. The template is in
`licenses/license_template.txt`. Run `python licenses/update_license.py . licenses/license_template.txt`
to add missing headers.

### Docker

```bash
docker build -t mitosis-oasis .
docker run -p 8000:8000 mitosis-oasis
```

---

## Architecture: Four Branches

The system models a constitutional separation of powers.

```
Legislative (governance/)      Executive (execution/)
    ↓ passes proposals              ↓ routes & runs tasks
Adjudication (adjudication/)   Observatory (observatory/)
    ↓ resolves disputes             ↓ streams events / dashboard
```

### 1. Legislative branch (`oasis/governance/`)

Manages the full lifecycle of governance sessions:

- **State machine** (`state_machine.py`): 9 states — OPEN → ATTESTING →
  PROPOSING → DELIBERATING → VOTING → BIDDING → CLOSED → EXECUTED → ARCHIVED
- **Clerks** (`clerks/`): 4 agents — Registrar, Speaker, Regulator, Codifier
- **Voting** (`voting.py`): Copeland algorithm (ranked-choice, pairwise)
- **Fairness** (`fairness.py`): HHI & Kendall τ metrics
- **Constitutional checks** (`constitutional.py`): 6 constitutional rules
- **DAG validation** (`dag.py`): validates and recursively decomposes task DAGs

### 2. Execution branch (`oasis/execution/`)

Routes and executes tasks after the legislative phase:

- **Router** (`router.py`): bid → assignment pipeline
- **Commitment** (`commitment.py`): stake locking
- **Runner** (`runner.py`): dispatcher supporting LLM and synthetic modes
- **Synthetic** (`synthetic.py`): task generation with configurable quality
- **Validator** (`validator.py`): output validation

### 3. Adjudication branch (`oasis/adjudication/`)

Handles disputes and reputation management:

- **Guardian** (`guardian.py`): alert generation
- **Override panel** (`override_panel.py`): 2-layer dispute resolution
- **Sanctions** (`sanctions.py`): freeze / slash / EMA reputation updates
- **Settlement** (`settlement.py`): reward formula
- **Treasury** (`treasury.py`): fee management
- **Coordination** (`coordination.py`): detects collusion patterns

### 4. Observatory branch (`oasis/observatory/`)

Provides real-time observability:

- **Event bus** (`event_bus.py`): publish / subscribe / replay
- **WebSocket** (`websocket.py`): `GET /ws/events` live stream
- **Dashboard** (`dashboard.py`): HTML/CSS/Chart.js dark-theme UI (8 panels)

---

## Configuration (`oasis/config.py`)

```python
@dataclass
class PlatformConfig:
    execution_mode: "llm" | "synthetic" = "synthetic"
    synthetic_quality: "perfect" | "mixed" | "adversarial" = "mixed"
    synthetic_success_rate: float = 0.8
    adjudication_llm_enabled: bool = False
    freeze_threshold: float = 0.9
```

The FastAPI app creates temporary SQLite databases at startup (one per branch)
via the lifespan handler in `oasis/api.py`.

---

## Database Conventions

- **Engine**: SQLite with `PRAGMA foreign_keys = ON`
- **Schema init**: `create_*_tables(db_path: str)` in each branch's `schema.py`
- **Timestamps**: `CURRENT_TIMESTAMP` for all event records
- **DIDs**: `did:mock:{type}-{id}` format (e.g., `did:mock:producer-1`)
- **IDs**: UUIDs or semantic strings (e.g., `session_id`, `proposal_id`)
- **Seeding helpers**: `seed_constitution()`, `seed_clerks()` used in tests

---

## Testing Conventions

### Fixtures (defined in `test/conftest.py` and per-branch `conftest.py`)

- `db_path` — temporary SQLite path via `tmp_path`
- `governance_db` — pre-initialized governance database
- `sample_agents` — `SAMPLE_PRODUCERS`, `SAMPLE_CLERKS` constants
- `sample_dag` — a valid `SAMPLE_DAG` for proposal tests

### Rules

- Each test gets a **fresh, isolated database** — never share state between tests
- Use `pytest-asyncio` (configured with `asyncio_mode = "auto"` — no manual
  `@pytest.mark.asyncio` needed)
- Test files follow the pattern `test_<module>.py`
- End-to-end tests live in a dedicated `e2e/` subdirectory per branch

---

## Code Style & Naming Conventions

- **Style guide**: Google Python Style Guide enforced by Ruff
- **Docstrings**: Google-style, 79-char line limit, raw strings (`r"""..."""`)
- **Naming**: snake_case for functions/variables, PascalCase for classes
- **No abbreviations**: `display_name` not `disp_name`; clarity over brevity
  (agents read code too)
- **Verb-first functions**: `create_governance_tables`, `seed_constitution`,
  `cast_vote`
- **Imports**: isort-sorted; stdlib → third-party → local

### License header

Every `.py` file must start with the Apache 2.0 license header. The pre-commit
`check-license` hook enforces this. When creating new files, run
`python licenses/update_license.py . licenses/license_template.txt` before
committing.

---

## API Overview

### Endpoints summary

| Branch | Approx. endpoints |
|--------|------------------|
| Legislative | 20 |
| Execution | 7 |
| Adjudication | 9 |
| Observatory (REST) | 7 |
| Observatory WebSocket | 1 (`/ws/events`) |
| Health | 1 (`/api/health`) |

### ZeroClaw skill tools (`skills/mitosis-governance/SKILL.toml`)

15 HTTP tools that external agents call:
`attest_identity`, `submit_proposal`, `get_evidence`, `submit_straw_poll`,
`discuss`, `get_deliberation_summary`, `cast_vote`, `submit_bid`,
`get_session_state`, `get_vote_results`, `get_task`, `submit_commitment`,
`submit_task_output`, `get_task_status`, `get_settlement`.

---

## CI/CD

Defined in `.github/workflows/ci.yml`, using reusable workflows from
`anbangr/mitosis-cicd`:

1. **python-ci** — `pytest` on Python 3.10 with system deps (libcairo2-dev,
   libigraph-dev). Ruff formatting and coverage are disabled in CI.
2. **docker** (on main push) — builds and pushes to GHCR
   (`ghcr.io/anbangr/mitosis-oasis`).
3. **deploy** (on main push, after docker) — SSH deploy to DigitalOcean; health
   check at `/api/health`.

CI is skipped for changes to `**.md`, `docs/**`, `LICENSE`, `.gitignore`.

---

## Key Files Quick Reference

| Path | What it is |
|------|-----------|
| `oasis/api.py` | FastAPI app, lifespan DB init, all routers included |
| `oasis/server.py` | `uvicorn.run()` launcher |
| `oasis/config.py` | `PlatformConfig` dataclass |
| `oasis/governance/state_machine.py` | 9-state legislative engine |
| `oasis/governance/voting.py` | Copeland ranked-choice voting |
| `oasis/governance/clerks/` | Registrar, Speaker, Regulator, Codifier |
| `oasis/execution/runner.py` | LLM/synthetic task dispatcher |
| `oasis/adjudication/sanctions.py` | Freeze/slash/EMA reputation |
| `oasis/observatory/event_bus.py` | Pub/sub/replay event system |
| `oasis/observatory/dashboard.py` | Web UI (8 panels, dark theme) |
| `test/conftest.py` | Root pytest fixtures |
| `test/governance/conftest.py` | Governance-specific fixtures |
| `skills/mitosis-governance/SKILL.toml` | 15 ZeroClaw HTTP tools |
| `pyproject.toml` | Poetry deps + pytest config |
| `.pre-commit-config.yaml` | Ruff, flake8, isort, mdformat, license hooks |
| `IMPLEMENTATION_PLAN.md` | 17-phase roadmap |

---

## Things to Avoid

- Do **not** modify `test/infra/recsys` or `test/agent` — these are excluded
  from CI for reasons outside our control.
- Do **not** commit files without the Apache 2.0 license header.
- Do **not** use abbreviations in identifiers — the codebase explicitly
  prioritizes readability for agent consumers.
- Do **not** create shared mutable state across tests — each test must
  provision its own `tmp_path`-based database.
- Do **not** push directly to `main` — use feature branches and PRs.
