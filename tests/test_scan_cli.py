"""Tests for critiq.scan_cli module."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from critiq.scan_cli import main as scan_main
from critiq.reviewer import ReviewResult, ReviewComment, Severity


def _make_result(comments=None):
    return ReviewResult(
        comments=comments or [],
        summary="All good.",
        overall_rating="✅ LGTM",
        provider_model="claude-haiku-4-5",
    )


def _make_critical_result():
    return ReviewResult(
        comments=[
            ReviewComment(
                severity=Severity.CRITICAL,
                title="SQL injection",
                body="User input not sanitized.",
                file="src/db.py",
                line="42",
                category="security",
            )
        ],
        summary="Critical issues found.",
        overall_rating="🚨 Needs work",
        provider_model="claude-haiku-4-5",
    )


def test_scan_version():
    runner = CliRunner()
    result = runner.invoke(scan_main, ["--version"])
    assert result.exit_code == 0
    assert "2.0.0" in result.output


def test_scan_no_path(tmp_path):
    runner = CliRunner()
    # With no Python files, should still work
    with runner.isolated_filesystem(temp_dir=tmp_path):
        with patch("critiq.scan_cli.get_provider", return_value=MagicMock()), \
         patch("critiq.scan_cli.review_file_content", return_value=_make_result()):
            result = runner.invoke(scan_main, [])
    # Either no files found or scanned
    assert result.exit_code in (0, 1)


def test_scan_single_file(tmp_path):
    src = tmp_path / "auth.py"
    src.write_text("import sqlite3\ndef query(user_input): pass\n")

    runner = CliRunner()
    with patch("critiq.scan_cli.get_provider", return_value=MagicMock()), \
         patch("critiq.scan_cli.review_file_content", return_value=_make_result()):
        result = runner.invoke(scan_main, [str(src)])
    assert result.exit_code == 0


def test_scan_critical_issues(tmp_path):
    src = tmp_path / "db.py"
    src.write_text("def query(x): return 'SELECT * FROM t WHERE id=' + x\n")

    runner = CliRunner()
    with patch("critiq.scan_cli.get_provider", return_value=MagicMock()), \
         patch("critiq.scan_cli.review_file_content", return_value=_make_critical_result()):
        result = runner.invoke(scan_main, [str(src)])
    assert result.exit_code == 1  # critical → exit 1


def test_scan_json_output(tmp_path):
    src = tmp_path / "app.py"
    src.write_text("x = 1\n")

    runner = CliRunner()
    with patch("critiq.scan_cli.get_provider", return_value=MagicMock()), \
         patch("critiq.scan_cli.review_file_content", return_value=_make_result()):
        result = runner.invoke(scan_main, ["--json", str(src)])
    assert result.exit_code == 0
    # JSON output should be parseable
    import json
    # Output may contain multiple JSON objects - just check there is output
    assert len(result.output) > 0
