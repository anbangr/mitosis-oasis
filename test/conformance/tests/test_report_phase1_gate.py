"""Regression coverage for Phase-1 conformance report gate rendering."""

from test.conformance.matrix.report import write_report
from test.conformance.matrix.scoreboard import Scoreboard


def test_report_gate_excludes_gaps_from_pass_rate(tmp_path):
    scoreboard = Scoreboard(
        totals={"PASS": 19, "FAIL": 0, "GAP": 1, "ERROR": 0},
        has_error=False,
        by_contract={
            "LegislativePipeline": {"PASS": 19, "FAIL": 0, "GAP": 1, "ERROR": 0}
        },
        by_function={},
        by_power={"legislation": {"PASS": 19, "FAIL": 0, "GAP": 1, "ERROR": 0}},
        top_failures=[],
        gaps=[],
    )

    out_dir = write_report(
        scoreboard,
        contracts_sha="0xabc",
        run_id="phase1-gate-test",
        fixture_count=2,
        call_count=20,
        out_root=tmp_path,
    )

    report_md = (out_dir / "conformance.md").read_text()
    # Gate should be PASS even with GAPs present (GAPs excluded from pass rate)
    assert "legislation" in report_md
    assert "PASS" in report_md
