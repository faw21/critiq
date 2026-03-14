"""Tests for the fixer module."""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console

from critiq.fixer import (
    FixResult,
    _backup_file,
    _build_fix_system_prompt,
    _build_fix_user_prompt,
    _group_issues_by_file,
    _read_file,
    _show_diff,
    generate_fix,
    interactive_fix,
)
from critiq.reviewer import ReviewComment, ReviewResult, Severity


# ─── Fixtures ───────────────────────────────────────────────────────────────


def _make_comment(
    severity: Severity = Severity.CRITICAL,
    file: str = "src/auth.py",
    line: str = "L42",
    title: str = "SQL Injection",
    body: str = "**Issue:** Use parameterized queries\n**Fix:** db.execute('?', (val,))",
    category: str = "security",
) -> ReviewComment:
    return ReviewComment(
        severity=severity,
        file=file,
        line=line,
        title=title,
        body=body,
        category=category,
    )


def _make_result(comments: list[ReviewComment] | None = None) -> ReviewResult:
    return ReviewResult(
        comments=comments or [_make_comment()],
        summary="Review summary",
        overall_rating="🚨 Needs work",
        provider_model="claude/test",
    )


# ─── _build_fix_system_prompt ────────────────────────────────────────────────


class TestBuildFixSystemPrompt:
    def test_contains_key_instructions(self):
        prompt = _build_fix_system_prompt()
        assert "fix" in prompt.lower()
        assert "complete" in prompt.lower()
        assert "markdown" in prompt.lower() or "fence" in prompt.lower()

    def test_instructs_minimal_changes(self):
        prompt = _build_fix_system_prompt()
        assert "minimal" in prompt.lower() or "only modify" in prompt.lower()


# ─── _build_fix_user_prompt ─────────────────────────────────────────────────


class TestBuildFixUserPrompt:
    def test_contains_file_path(self):
        issues = [_make_comment()]
        prompt = _build_fix_user_prompt("src/auth.py", "def foo(): pass", issues)
        assert "src/auth.py" in prompt

    def test_contains_issue_title(self):
        issues = [_make_comment(title="SQL Injection detected")]
        prompt = _build_fix_user_prompt("src/auth.py", "def foo(): pass", issues)
        assert "SQL Injection detected" in prompt

    def test_contains_file_content(self):
        issues = [_make_comment()]
        prompt = _build_fix_user_prompt("src/auth.py", "def secret(): pass", issues)
        assert "def secret(): pass" in prompt

    def test_contains_severity_label(self):
        issues = [_make_comment(severity=Severity.CRITICAL)]
        prompt = _build_fix_user_prompt("src/auth.py", "", issues)
        assert "CRITICAL" in prompt

    def test_multiple_issues_all_listed(self):
        issues = [
            _make_comment(title="Issue One"),
            _make_comment(title="Issue Two", severity=Severity.WARNING),
        ]
        prompt = _build_fix_user_prompt("src/auth.py", "", issues)
        assert "Issue One" in prompt
        assert "Issue Two" in prompt


# ─── _group_issues_by_file ──────────────────────────────────────────────────


class TestGroupIssuesByFile:
    def test_groups_same_file(self):
        issues = [
            _make_comment(file="a.py"),
            _make_comment(file="a.py", title="Second issue"),
        ]
        grouped = _group_issues_by_file(issues)
        assert len(grouped) == 1
        assert len(grouped["a.py"]) == 2

    def test_groups_multiple_files(self):
        issues = [
            _make_comment(file="a.py"),
            _make_comment(file="b.py"),
        ]
        grouped = _group_issues_by_file(issues)
        assert "a.py" in grouped
        assert "b.py" in grouped

    def test_skips_issues_without_file(self):
        issues = [
            _make_comment(file=""),
            _make_comment(file="a.py"),
        ]
        grouped = _group_issues_by_file(issues)
        assert "" not in grouped
        assert "a.py" in grouped


# ─── _read_file ─────────────────────────────────────────────────────────────


class TestReadFile:
    def test_reads_existing_file(self, tmp_path):
        f = tmp_path / "foo.py"
        f.write_text("def foo(): pass", encoding="utf-8")
        content = _read_file(str(f))
        assert content == "def foo(): pass"

    def test_returns_none_for_missing_file(self):
        result = _read_file("/nonexistent/path/file.py")
        assert result is None


# ─── _backup_file ────────────────────────────────────────────────────────────


class TestBackupFile:
    def test_creates_backup(self, tmp_path):
        f = tmp_path / "auth.py"
        f.write_text("original content", encoding="utf-8")
        backup_path = _backup_file(f)
        assert Path(backup_path).exists()
        assert Path(backup_path).read_text() == "original content"

    def test_backup_has_correct_extension(self, tmp_path):
        f = tmp_path / "auth.py"
        f.write_text("content", encoding="utf-8")
        backup_path = _backup_file(f)
        assert backup_path.endswith(".critiq.bak")

    def test_original_file_unchanged(self, tmp_path):
        f = tmp_path / "auth.py"
        f.write_text("original", encoding="utf-8")
        _backup_file(f)
        assert f.read_text() == "original"


# ─── _show_diff ─────────────────────────────────────────────────────────────


class TestShowDiff:
    def test_returns_zero_when_no_changes(self):
        console = Console(force_terminal=True)
        result = _show_diff("same content", "same content", "foo.py", console)
        assert result == 0

    def test_returns_changed_line_count(self):
        console = Console(force_terminal=True)
        result = _show_diff("line1\nline2\n", "line1\nchanged\n", "foo.py", console)
        assert result > 0

    def test_handles_empty_files(self):
        console = Console(force_terminal=True)
        result = _show_diff("", "new content\n", "foo.py", console)
        assert result > 0


# ─── generate_fix ────────────────────────────────────────────────────────────


class TestGenerateFix:
    def test_calls_provider_with_system_and_user(self):
        mock_provider = MagicMock()
        mock_provider.complete.return_value = "def fixed(): pass"

        result = generate_fix(
            "src/auth.py",
            "def broken(): pass",
            [_make_comment()],
            mock_provider,
        )

        assert mock_provider.complete.call_count == 1
        system_arg = mock_provider.complete.call_args[0][0]
        user_arg = mock_provider.complete.call_args[0][1]
        assert "fix" in system_arg.lower()
        assert "src/auth.py" in user_arg

    def test_returns_fixed_content(self):
        mock_provider = MagicMock()
        mock_provider.complete.return_value = "def fixed(): return 42"

        result = generate_fix("a.py", "def broken(): pass", [_make_comment()], mock_provider)
        assert result == "def fixed(): return 42"

    def test_strips_markdown_fences(self):
        mock_provider = MagicMock()
        mock_provider.complete.return_value = "```python\ndef fixed(): pass\n```"

        result = generate_fix("a.py", "def broken(): pass", [_make_comment()], mock_provider)
        assert "```" not in result
        assert "def fixed(): pass" in result

    def test_strips_plain_fences(self):
        mock_provider = MagicMock()
        mock_provider.complete.return_value = "```\ndef fixed(): pass\n```"

        result = generate_fix("a.py", "", [_make_comment()], mock_provider)
        assert "```" not in result


# ─── interactive_fix ─────────────────────────────────────────────────────────


class TestInteractiveFix:
    def _mock_provider(self, fixed_content: str = "def fixed(): pass") -> MagicMock:
        mock = MagicMock()
        mock.complete.return_value = fixed_content
        return mock

    def test_returns_empty_when_no_fixable_issues(self):
        result_with_no_fixable = _make_result(comments=[
            _make_comment(severity=Severity.INFO),
        ])
        console = Console(force_terminal=False)
        results = interactive_fix(
            result_with_no_fixable,
            self._mock_provider(),
            console,
            fix_all=True,
        )
        assert results == []

    def test_skips_missing_files(self, tmp_path):
        review_result = _make_result(comments=[
            _make_comment(file="/nonexistent/path/auth.py"),
        ])
        console = Console(force_terminal=False)
        results = interactive_fix(
            review_result,
            self._mock_provider(),
            console,
            fix_all=True,
        )
        assert len(results) == 1
        assert results[0].applied is False

    def test_fix_all_applies_without_prompting(self, tmp_path):
        target_file = tmp_path / "auth.py"
        target_file.write_text(
            "query = f'SELECT * FROM users WHERE id={user_id}'\n",
            encoding="utf-8",
        )

        review_result = _make_result(comments=[
            _make_comment(file=str(target_file)),
        ])

        fixed_content = "query = db.execute('SELECT * FROM users WHERE id=?', (user_id,))\n"
        console = Console(force_terminal=False)

        results = interactive_fix(
            review_result,
            self._mock_provider(fixed_content),
            console,
            fix_all=True,
        )

        assert len(results) == 1
        assert results[0].applied is True
        # File should be updated
        assert target_file.read_text() == fixed_content
        # Backup should exist
        backup = tmp_path / "auth.py.critiq.bak"
        assert backup.exists()

    def test_severity_filter_only_fixes_matching(self, tmp_path):
        target_file = tmp_path / "utils.py"
        target_file.write_text("def foo(): pass\n", encoding="utf-8")

        review_result = _make_result(comments=[
            _make_comment(severity=Severity.INFO, file=str(target_file), title="Minor style"),
        ])

        console = Console(force_terminal=False)
        # Only fix CRITICAL issues — INFO should be filtered out
        results = interactive_fix(
            review_result,
            self._mock_provider(),
            console,
            fix_all=True,
            severity_filter={Severity.CRITICAL},
        )
        assert results == []

    def test_generator_exception_handled_gracefully(self, tmp_path):
        target_file = tmp_path / "auth.py"
        target_file.write_text("def foo(): pass\n", encoding="utf-8")

        review_result = _make_result(comments=[
            _make_comment(file=str(target_file)),
        ])

        failing_provider = MagicMock()
        failing_provider.complete.side_effect = Exception("LLM unavailable")

        console = Console(force_terminal=False)
        results = interactive_fix(
            review_result,
            failing_provider,
            console,
            fix_all=True,
        )

        assert len(results) == 1
        assert results[0].applied is False
        # Original file should be untouched
        assert target_file.read_text() == "def foo(): pass\n"

    def test_no_change_fix_not_applied(self, tmp_path):
        """When LLM returns identical content, no fix is applied."""
        original = "def foo(): pass\n"
        target_file = tmp_path / "auth.py"
        target_file.write_text(original, encoding="utf-8")

        review_result = _make_result(comments=[
            _make_comment(file=str(target_file)),
        ])

        console = Console(force_terminal=False)
        # Provider returns same content
        results = interactive_fix(
            review_result,
            self._mock_provider(original),
            console,
            fix_all=True,
        )

        assert len(results) == 1
        assert results[0].applied is False

    def test_groups_multiple_issues_per_file_into_one_fix(self, tmp_path):
        target_file = tmp_path / "auth.py"
        target_file.write_text("def foo(): pass\n", encoding="utf-8")

        review_result = _make_result(comments=[
            _make_comment(file=str(target_file), title="Issue 1"),
            _make_comment(file=str(target_file), title="Issue 2"),
        ])

        mock_provider = self._mock_provider("def foo(): return 42\n")
        console = Console(force_terminal=False)

        interactive_fix(
            review_result,
            mock_provider,
            console,
            fix_all=True,
        )

        # LLM should be called ONCE for the file (both issues batched)
        assert mock_provider.complete.call_count == 1
        call_args = mock_provider.complete.call_args[0][1]
        assert "Issue 1" in call_args
        assert "Issue 2" in call_args
