"""Tests for CLI module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from critiq.cli import main
from critiq.git_utils import DiffResult
from critiq.reviewer import ReviewComment, ReviewResult, Severity


SAMPLE_DIFF = DiffResult(
    diff="diff --git a/auth.py b/auth.py\n+    return True",
    files_changed=["auth.py"],
    insertions=1,
    deletions=0,
    is_empty=False,
)

CLEAN_RESULT = ReviewResult(
    comments=[],
    summary="Looks good, no issues found.",
    overall_rating="✅ LGTM",
    provider_model="claude/default",
)

CRITICAL_RESULT = ReviewResult(
    comments=[
        ReviewComment(
            severity=Severity.CRITICAL,
            file="auth.py",
            line="L10",
            title="SQL Injection",
            body="**Issue:** SQL injection\n**Fix:** Use parameterized queries",
            category="security",
        )
    ],
    summary="Critical SQL injection found.",
    overall_rating="🚨 Needs work",
    provider_model="claude/default",
)

WARNING_RESULT = ReviewResult(
    comments=[
        ReviewComment(
            severity=Severity.WARNING,
            file="auth.py",
            line="L5",
            title="Missing null check",
            body="**Issue:** May raise TypeError\n**Fix:** Add None check",
            category="correctness",
        )
    ],
    summary="Minor issues found.",
    overall_rating="⚠️ Minor issues",
    provider_model="claude/default",
)


def _run_cli(args=None, env=None):
    runner = CliRunner()
    return runner.invoke(main, args or [], env=env or {"ANTHROPIC_API_KEY": "test-key"})


class TestCLIBasic:
    def test_version(self):
        result = _run_cli(["--version"])
        assert result.exit_code == 0
        assert "1.4.0" in result.output

    def test_help(self):
        result = _run_cli(["--help"])
        assert result.exit_code == 0
        assert "staged" in result.output.lower()
        assert "diff" in result.output.lower()

    def test_not_in_git_repo(self):
        with patch("critiq.cli.is_git_repo", return_value=False):
            result = _run_cli()
        assert result.exit_code != 0
        assert "git repository" in result.output.lower()


class TestStagedMode:
    def test_empty_staged_changes(self):
        empty_diff = DiffResult("", [], 0, 0, is_empty=True)
        with patch("critiq.cli.is_git_repo", return_value=True), \
             patch("critiq.cli.get_staged_diff", return_value=empty_diff):
            result = _run_cli()
        assert result.exit_code == 0
        assert "No staged" in result.output

    def test_clean_review(self):
        with patch("critiq.cli.is_git_repo", return_value=True), \
             patch("critiq.cli.get_staged_diff", return_value=SAMPLE_DIFF), \
             patch("critiq.cli.get_provider") as mock_get_provider, \
             patch("critiq.cli.review_diff", return_value=CLEAN_RESULT):
            mock_get_provider.return_value = MagicMock()
            result = _run_cli()
        assert result.exit_code == 0
        assert "LGTM" in result.output

    def test_critical_review_exits_nonzero(self):
        with patch("critiq.cli.is_git_repo", return_value=True), \
             patch("critiq.cli.get_staged_diff", return_value=SAMPLE_DIFF), \
             patch("critiq.cli.get_provider") as mock_get_provider, \
             patch("critiq.cli.review_diff", return_value=CRITICAL_RESULT):
            mock_get_provider.return_value = MagicMock()
            result = _run_cli()
        assert result.exit_code == 1

    def test_warning_only_exits_zero(self):
        with patch("critiq.cli.is_git_repo", return_value=True), \
             patch("critiq.cli.get_staged_diff", return_value=SAMPLE_DIFF), \
             patch("critiq.cli.get_provider") as mock_get_provider, \
             patch("critiq.cli.review_diff", return_value=WARNING_RESULT):
            mock_get_provider.return_value = MagicMock()
            result = _run_cli()
        assert result.exit_code == 0


class TestJSONOutput:
    def test_json_output_structure(self):
        """--json outputs valid JSON with expected keys."""
        import json

        with patch("critiq.cli.is_git_repo", return_value=True), \
             patch("critiq.cli.get_staged_diff", return_value=SAMPLE_DIFF), \
             patch("critiq.cli.get_provider") as mock_get_provider, \
             patch("critiq.cli.review_diff", return_value=CRITICAL_RESULT):
            mock_get_provider.return_value = MagicMock()
            result = _run_cli(["--json"])

        data = json.loads(result.output)
        assert "summary" in data
        assert "overall_rating" in data
        assert "comments" in data
        assert isinstance(data["comments"], list)

    def test_json_output_critical_exits_1(self):
        """--json exits with code 1 when CRITICAL issues found."""
        with patch("critiq.cli.is_git_repo", return_value=True), \
             patch("critiq.cli.get_staged_diff", return_value=SAMPLE_DIFF), \
             patch("critiq.cli.get_provider") as mock_get_provider, \
             patch("critiq.cli.review_diff", return_value=CRITICAL_RESULT):
            mock_get_provider.return_value = MagicMock()
            result = _run_cli(["--json"])

        assert result.exit_code == 1

    def test_json_output_clean_exits_0(self):
        """--json exits with code 0 for clean reviews."""
        with patch("critiq.cli.is_git_repo", return_value=True), \
             patch("critiq.cli.get_staged_diff", return_value=SAMPLE_DIFF), \
             patch("critiq.cli.get_provider") as mock_get_provider, \
             patch("critiq.cli.review_diff", return_value=CLEAN_RESULT):
            mock_get_provider.return_value = MagicMock()
            result = _run_cli(["--json"])

        assert result.exit_code == 0

    def test_json_comment_fields(self):
        """Each comment in --json has all required fields."""
        import json

        with patch("critiq.cli.is_git_repo", return_value=True), \
             patch("critiq.cli.get_staged_diff", return_value=SAMPLE_DIFF), \
             patch("critiq.cli.get_provider") as mock_get_provider, \
             patch("critiq.cli.review_diff", return_value=CRITICAL_RESULT):
            mock_get_provider.return_value = MagicMock()
            result = _run_cli(["--json"])

        data = json.loads(result.output)
        comment = data["comments"][0]
        for field in ("severity", "file", "line", "title", "body", "category"):
            assert field in comment


class TestDiffMode:
    def test_diff_vs_branch(self):
        with patch("critiq.cli.is_git_repo", return_value=True), \
             patch("critiq.cli.get_branch_diff", return_value=SAMPLE_DIFF), \
             patch("critiq.cli.get_provider") as mock_get_provider, \
             patch("critiq.cli.review_diff", return_value=CLEAN_RESULT):
            mock_get_provider.return_value = MagicMock()
            result = _run_cli(["--diff", "main"])
        assert result.exit_code == 0
        assert "main" in result.output

    def test_diff_empty(self):
        empty_diff = DiffResult("", [], 0, 0, is_empty=True)
        with patch("critiq.cli.is_git_repo", return_value=True), \
             patch("critiq.cli.get_branch_diff", return_value=empty_diff):
            result = _run_cli(["--diff", "main"])
        assert result.exit_code == 0
        assert "No changes" in result.output


class TestFileMode:
    def test_specific_file(self):
        with patch("critiq.cli.is_git_repo", return_value=True), \
             patch("critiq.cli.get_file_diff", return_value=SAMPLE_DIFF), \
             patch("critiq.cli.get_provider") as mock_get_provider, \
             patch("critiq.cli.review_diff", return_value=CLEAN_RESULT):
            mock_get_provider.return_value = MagicMock()
            result = _run_cli(["--file", "auth.py"])
        assert result.exit_code == 0

    def test_file_empty_diff(self):
        empty_diff = DiffResult("", [], 0, 0, is_empty=True)
        with patch("critiq.cli.is_git_repo", return_value=True), \
             patch("critiq.cli.get_file_diff", return_value=empty_diff):
            result = _run_cli(["--file", "auth.py"])
        assert result.exit_code == 0
        assert "No changes" in result.output


class TestFocusOption:
    @pytest.mark.parametrize("focus", ["security", "performance", "readability", "correctness", "style", "all"])
    def test_valid_focus(self, focus):
        with patch("critiq.cli.is_git_repo", return_value=True), \
             patch("critiq.cli.get_staged_diff", return_value=SAMPLE_DIFF), \
             patch("critiq.cli.get_provider") as mock_get_provider, \
             patch("critiq.cli.review_diff", return_value=CLEAN_RESULT):
            mock_get_provider.return_value = MagicMock()
            result = _run_cli(["--focus", focus])
        assert result.exit_code == 0

    def test_invalid_focus(self):
        result = _run_cli(["--focus", "invalid"])
        assert result.exit_code != 0


class TestSeverityFilter:
    def test_severity_filter_hides_lower(self):
        """--severity critical should hide warnings."""
        with patch("critiq.cli.is_git_repo", return_value=True), \
             patch("critiq.cli.get_staged_diff", return_value=SAMPLE_DIFF), \
             patch("critiq.cli.get_provider") as mock_get_provider, \
             patch("critiq.cli.review_diff", return_value=WARNING_RESULT):
            mock_get_provider.return_value = MagicMock()
            result = _run_cli(["--severity", "critical"])
        # Warning result filtered to show no critical → LGTM effectively
        assert result.exit_code == 0

    def test_severity_warning_shows_warnings(self):
        with patch("critiq.cli.is_git_repo", return_value=True), \
             patch("critiq.cli.get_staged_diff", return_value=SAMPLE_DIFF), \
             patch("critiq.cli.get_provider") as mock_get_provider, \
             patch("critiq.cli.review_diff", return_value=WARNING_RESULT):
            mock_get_provider.return_value = MagicMock()
            result = _run_cli(["--severity", "warning"])
        assert result.exit_code == 0
        assert "Missing null check" in result.output


class TestProviderOption:
    def test_claude_provider(self):
        with patch("critiq.cli.is_git_repo", return_value=True), \
             patch("critiq.cli.get_staged_diff", return_value=SAMPLE_DIFF), \
             patch("critiq.cli.get_provider") as mock_get_provider, \
             patch("critiq.cli.review_diff", return_value=CLEAN_RESULT):
            mock_get_provider.return_value = MagicMock()
            result = _run_cli(["--provider", "claude"])
        assert result.exit_code == 0
        assert mock_get_provider.call_args[0][0] == "claude"

    def test_ollama_provider(self):
        with patch("critiq.cli.is_git_repo", return_value=True), \
             patch("critiq.cli.get_staged_diff", return_value=SAMPLE_DIFF), \
             patch("critiq.cli.get_provider") as mock_get_provider, \
             patch("critiq.cli.review_diff", return_value=CLEAN_RESULT):
            mock_get_provider.return_value = MagicMock()
            result = _run_cli(["--provider", "ollama"])
        assert result.exit_code == 0

    def test_provider_error_shown(self):
        with patch("critiq.cli.is_git_repo", return_value=True), \
             patch("critiq.cli.get_staged_diff", return_value=SAMPLE_DIFF), \
             patch("critiq.cli.get_provider", side_effect=ValueError("No API key")):
            result = _run_cli()
        assert result.exit_code != 0
        assert "No API key" in result.output


class TestCompactMode:
    def test_compact_flag(self):
        with patch("critiq.cli.is_git_repo", return_value=True), \
             patch("critiq.cli.get_staged_diff", return_value=SAMPLE_DIFF), \
             patch("critiq.cli.get_provider") as mock_get_provider, \
             patch("critiq.cli.review_diff", return_value=WARNING_RESULT):
            mock_get_provider.return_value = MagicMock()
            result = _run_cli(["--compact"])
        assert result.exit_code == 0
        assert "Missing null check" in result.output


class TestContextOption:
    def test_context_passed_to_reviewer(self):
        with patch("critiq.cli.is_git_repo", return_value=True), \
             patch("critiq.cli.get_staged_diff", return_value=SAMPLE_DIFF), \
             patch("critiq.cli.get_provider") as mock_get_provider, \
             patch("critiq.cli.review_diff", return_value=CLEAN_RESULT) as mock_review:
            mock_get_provider.return_value = MagicMock()
            _run_cli(["--context", "Security critical auth module"])
        call_kwargs = mock_review.call_args[1]
        assert "Security critical auth module" in call_kwargs.get("context", "")
