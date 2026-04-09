"""P11 tests: SKILL.toml parsing and structure validation."""
from pathlib import Path

import tomli


SKILL_TOML = Path(__file__).resolve().parents[2] / "skills" / "metosis-governance" / "SKILL.toml"


def _load_skill():
    with open(SKILL_TOML, "rb") as f:
        return tomli.load(f)


# ---------- Test 1: TOML parses without error ----------

def test_skill_toml_parses():
    """SKILL.toml is valid TOML and can be loaded."""
    data = _load_skill()
    assert isinstance(data, dict)
    assert "skill" in data
    assert "tools" in data


# ---------- Test 2: All 15 tools are present ----------

EXPECTED_TOOLS = {
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
    "get_task",
    "submit_commitment",
    "submit_task_output",
    "get_task_status",
    "get_settlement",
}


def test_all_ten_tools_present():
    """All 15 governance + execution HTTP tools are defined in the TOML."""
    data = _load_skill()
    tool_names = {t["name"] for t in data["tools"]}
    assert tool_names == EXPECTED_TOOLS, (
        f"Missing: {EXPECTED_TOOLS - tool_names}, "
        f"Extra: {tool_names - EXPECTED_TOOLS}"
    )


# ---------- Test 3: All tools have kind='http' ----------

def test_all_tools_have_http_kind():
    """Every tool entry must have kind='http'."""
    data = _load_skill()
    for tool in data["tools"]:
        assert tool.get("kind") == "http", (
            f"Tool {tool['name']!r} has kind={tool.get('kind')!r}, expected 'http'"
        )
