"""P16 tests: Execution tool validation for SKILL.toml."""
from pathlib import Path

import tomli


SKILL_TOML = Path(__file__).resolve().parents[2] / "skills" / "metosis-governance" / "SKILL.toml"

EXECUTION_TOOLS = {
    "get_task",
    "submit_commitment",
    "submit_task_output",
    "get_task_status",
    "get_settlement",
}

EXECUTION_ENDPOINTS = {
    "get_task": "/api/execution/tasks/{task_id}",
    "submit_commitment": "/api/execution/tasks/{task_id}/commit",
    "submit_task_output": "/api/execution/tasks/{task_id}/output",
    "get_task_status": "/api/execution/tasks/{task_id}/status",
    "get_settlement": "/api/execution/tasks/{task_id}/settlement",
}

EXECUTION_METHODS = {
    "get_task": "GET",
    "submit_commitment": "POST",
    "submit_task_output": "POST",
    "get_task_status": "GET",
    "get_settlement": "GET",
}


def _load_skill():
    with open(SKILL_TOML, "rb") as f:
        return tomli.load(f)


# ---------- Test 1: All 5 execution tools present ----------

def test_execution_tools_present():
    """All 5 execution HTTP tools are defined in the TOML."""
    data = _load_skill()
    tool_names = {t["name"] for t in data["tools"]}
    missing = EXECUTION_TOOLS - tool_names
    assert not missing, f"Missing execution tools: {missing}"


# ---------- Test 2: URL templates correct ----------

def test_execution_url_templates():
    """Each execution tool URL template matches the canonical API endpoint."""
    data = _load_skill()
    tool_urls = {t["name"]: t["url_template"] for t in data["tools"]}
    for name, expected_url in EXECUTION_ENDPOINTS.items():
        assert name in tool_urls, f"Tool {name!r} not found in SKILL.toml"
        assert tool_urls[name] == expected_url, (
            f"Tool {name!r}: expected {expected_url!r}, got {tool_urls[name]!r}"
        )


# ---------- Test 3: Args documented with correct required fields ----------

def test_execution_args_documented():
    """Each execution tool has documented arguments with descriptions."""
    data = _load_skill()
    exec_tools = {t["name"]: t for t in data["tools"] if t["name"] in EXECUTION_TOOLS}

    for name, tool in exec_tools.items():
        args = tool.get("args", [])
        assert len(args) > 0, f"Tool {name!r} has no documented args"
        # Every tool must have task_id
        arg_names = {a["name"] for a in args}
        assert "task_id" in arg_names, (
            f"Tool {name!r}: missing required 'task_id' argument"
        )
        # All args have non-empty descriptions
        for arg in args:
            desc = arg.get("description", "")
            assert isinstance(desc, str) and len(desc.strip()) > 0, (
                f"Tool {name!r}, arg {arg['name']!r}: description is empty"
            )
        # HTTP method matches
        assert tool.get("method") == EXECUTION_METHODS[name], (
            f"Tool {name!r}: expected method {EXECUTION_METHODS[name]!r}, "
            f"got {tool.get('method')!r}"
        )
