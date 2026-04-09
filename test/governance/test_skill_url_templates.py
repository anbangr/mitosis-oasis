"""P11 tests: URL template validation for SKILL.toml tools."""
import re
from pathlib import Path

import tomli


SKILL_TOML = Path(__file__).resolve().parents[2] / "skills" / "metosis-governance" / "SKILL.toml"

# Canonical API endpoints from oasis/governance/endpoints.py and oasis/execution/endpoints.py
API_ENDPOINTS = {
    "attest_identity": "/api/governance/sessions/{session_id}/identity/attest",
    "submit_proposal": "/api/governance/sessions/{session_id}/proposals",
    "get_evidence": "/api/governance/sessions/{session_id}/regulatory/evidence",
    "submit_straw_poll": "/api/governance/sessions/{session_id}/deliberation/straw-poll",
    "discuss": "/api/governance/sessions/{session_id}/deliberation/discuss",
    "get_deliberation_summary": "/api/governance/sessions/{session_id}/deliberation/summary",
    "cast_vote": "/api/governance/sessions/{session_id}/vote",
    "submit_bid": "/api/governance/sessions/{session_id}/bids",
    "get_session_state": "/api/governance/sessions/{session_id}",
    "get_vote_results": "/api/governance/sessions/{session_id}/vote/results",
    "get_task": "/api/execution/tasks/{task_id}",
    "submit_commitment": "/api/execution/tasks/{task_id}/commit",
    "submit_task_output": "/api/execution/tasks/{task_id}/output",
    "get_task_status": "/api/execution/tasks/{task_id}/status",
    "get_settlement": "/api/execution/tasks/{task_id}/settlement",
}


def _load_skill():
    with open(SKILL_TOML, "rb") as f:
        return tomli.load(f)


# ---------- Test 1: URL templates contain expected path parameter ----------

# Execution tools use {task_id}; governance tools use {session_id}
EXECUTION_TOOLS = {"get_task", "submit_commitment", "submit_task_output", "get_task_status", "get_settlement"}


def test_url_templates_contain_path_param():
    """Every tool URL template must include its expected path parameter."""
    data = _load_skill()
    for tool in data["tools"]:
        url = tool["url_template"]
        if tool["name"] in EXECUTION_TOOLS:
            assert "{task_id}" in url, (
                f"Tool {tool['name']!r}: url_template {url!r} missing {{task_id}}"
            )
        else:
            assert "{session_id}" in url, (
                f"Tool {tool['name']!r}: url_template {url!r} missing {{session_id}}"
            )


# ---------- Test 2: No broken placeholders ----------

def test_no_broken_placeholders():
    """URL templates must not contain unresolved or malformed placeholders
    other than {session_id} or {task_id}."""
    data = _load_skill()
    # Match any {placeholder} token
    placeholder_re = re.compile(r"\{(\w+)\}")
    allowed = {"session_id", "task_id"}

    for tool in data["tools"]:
        url = tool["url_template"]
        found = set(placeholder_re.findall(url))
        unexpected = found - allowed
        assert not unexpected, (
            f"Tool {tool['name']!r}: unexpected placeholders {unexpected} in {url!r}"
        )


# ---------- Test 3: All endpoints match the API ----------

def test_endpoints_match_api():
    """Each tool's url_template must exactly match the canonical API endpoint."""
    data = _load_skill()
    tool_urls = {t["name"]: t["url_template"] for t in data["tools"]}

    for name, expected_url in API_ENDPOINTS.items():
        assert name in tool_urls, f"Tool {name!r} not found in SKILL.toml"
        assert tool_urls[name] == expected_url, (
            f"Tool {name!r}: expected {expected_url!r}, got {tool_urls[name]!r}"
        )
