"""P16 tests: Full skill surface validation — all 15 tools."""
from pathlib import Path

import tomli


SKILL_TOML = Path(__file__).resolve().parents[2] / "skills" / "mitosis-governance" / "SKILL.toml"

ALL_15_TOOLS = {
    # Governance (10)
    "attest_identity",
    "submit_proposal",
    "get_evidence",
    "submit_straw_poll",
    "discuss",
    "get_deliberation_summary",
    "cast_vote",
    "submit_bid",
    "get_session_state",
    "get_vote_results",
    # Execution (5)
    "get_task",
    "submit_commitment",
    "submit_task_output",
    "get_task_status",
    "get_settlement",
}


def _load_skill():
    with open(SKILL_TOML, "rb") as f:
        return tomli.load(f)


# ---------- Test 1: All 15 tools present ----------

def test_all_fifteen_tools_present():
    """All 15 governance + execution tools are defined in the TOML."""
    data = _load_skill()
    tool_names = {t["name"] for t in data["tools"]}
    assert tool_names == ALL_15_TOOLS, (
        f"Missing: {ALL_15_TOOLS - tool_names}, "
        f"Extra: {tool_names - ALL_15_TOOLS}"
    )


# ---------- Test 2: No duplicate tool names ----------

def test_no_duplicate_tools():
    """Tool names must be unique across the entire SKILL.toml (15 total)."""
    data = _load_skill()
    names = [t["name"] for t in data["tools"]]
    assert len(names) == len(set(names)), (
        f"Duplicate tool names found: "
        f"{[n for n in names if names.count(n) > 1]}"
    )
    assert len(names) == 15, f"Expected 15 tools, found {len(names)}"
