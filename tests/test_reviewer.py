"""Tests for reviewer module."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from critiq.git_utils import DiffResult
from critiq.reviewer import (
    ReviewResult,
    Severity,
    _build_language_hints,
    _build_system_prompt,
    _build_user_prompt,
    _detect_languages,
    _parse_review,
    _parse_severity,
    review_diff,
)


SAMPLE_DIFF = DiffResult(
    diff="""\
diff --git a/src/auth.py b/src/auth.py
index abc123..def456 100644
--- a/src/auth.py
+++ b/src/auth.py
@@ -10,3 +10,7 @@ def login(user, password):
+    sql = f"SELECT * FROM users WHERE name='{user}'"
+    return db.execute(sql)
-    return authenticate(user, password)
""",
    files_changed=["src/auth.py"],
    insertions=2,
    deletions=1,
    is_empty=False,
)


SAMPLE_REVIEW_RESPONSE = """\
## Summary
The change replaces a safe authentication call with raw SQL, introducing a critical SQL injection vulnerability.

## Rating
🚨 Needs work

## Findings

### [CRITICAL] SQL Injection vulnerability
**File:** `src/auth.py` (line 11)
**Category:** security
**Issue:** User input is directly interpolated into SQL string without parameterization.
**Fix:** Use parameterized queries: `db.execute("SELECT * FROM users WHERE name=?", (user,))`

### [WARNING] Removed authentication call
**File:** `src/auth.py` (line 13)
**Category:** correctness
**Issue:** The original `authenticate()` call was removed; this may bypass existing auth logic.
**Fix:** Understand why this was removed and ensure auth requirements are still met.
"""


class TestDetectLanguages:
    def test_python_files(self):
        assert _detect_languages(["src/foo.py", "bar.pyw"]) == {"python"}

    def test_javascript_files(self):
        assert _detect_languages(["app.js", "index.mjs"]) == {"javascript"}

    def test_typescript_files(self):
        assert _detect_languages(["app.ts", "comp.tsx"]) == {"typescript"}

    def test_go_files(self):
        assert _detect_languages(["main.go"]) == {"go"}

    def test_rust_files(self):
        assert _detect_languages(["lib.rs"]) == {"rust"}

    def test_mixed_languages(self):
        langs = _detect_languages(["main.go", "script.py", "app.ts"])
        assert langs == {"go", "python", "typescript"}

    def test_unknown_extensions(self):
        assert _detect_languages(["README.md", "Makefile", ".env"]) == set()

    def test_empty_list(self):
        assert _detect_languages([]) == set()

    def test_case_insensitive_extension(self):
        # .PY and .py should both detect python
        assert _detect_languages(["Script.PY"]) == {"python"}


class TestBuildLanguageHints:
    def test_python_hints_included(self):
        hints = _build_language_hints(["app.py"])
        assert "Python" in hints
        assert "Mutable default" in hints

    def test_go_hints_included(self):
        hints = _build_language_hints(["main.go"])
        assert "Go" in hints
        assert "defer" in hints

    def test_multiple_languages(self):
        hints = _build_language_hints(["app.py", "handler.go"])
        assert "Python" in hints
        assert "Go" in hints

    def test_no_hints_for_unknown_files(self):
        hints = _build_language_hints(["README.md", "Makefile"])
        assert hints == ""

    def test_empty_files(self):
        hints = _build_language_hints([])
        assert hints == ""

    def test_typescript_hints_included(self):
        hints = _build_language_hints(["component.tsx"])
        assert "Typescript" in hints
        assert "any" in hints

    def test_rust_hints_included(self):
        hints = _build_language_hints(["lib.rs"])
        assert "Rust" in hints
        assert "unwrap" in hints


class TestBuildSystemPrompt:
    def test_contains_focus(self):
        prompt = _build_system_prompt("security")
        assert "security" in prompt.lower()

    def test_all_focus(self):
        prompt = _build_system_prompt("all")
        assert "security" in prompt.lower()
        assert "performance" in prompt.lower()

    def test_unknown_focus_falls_back_to_all(self):
        prompt = _build_system_prompt("unknown_focus")
        assert len(prompt) > 100  # still generates a prompt


class TestBuildUserPrompt:
    def test_contains_diff(self):
        prompt = _build_user_prompt(SAMPLE_DIFF)
        assert "src/auth.py" in prompt
        assert "+    sql = f" in prompt

    def test_contains_stats(self):
        prompt = _build_user_prompt(SAMPLE_DIFF)
        assert "+2" in prompt
        assert "-1" in prompt

    def test_with_context(self):
        prompt = _build_user_prompt(SAMPLE_DIFF, context="Security-critical module")
        assert "Security-critical module" in prompt

    def test_without_context(self):
        prompt = _build_user_prompt(SAMPLE_DIFF, context=None)
        assert "Context" not in prompt


class TestParseSeverity:
    def test_critical(self):
        assert _parse_severity("CRITICAL") == Severity.CRITICAL

    def test_warning(self):
        assert _parse_severity("WARNING") == Severity.WARNING

    def test_info(self):
        assert _parse_severity("INFO") == Severity.INFO

    def test_suggestion(self):
        assert _parse_severity("SUGGESTION") == Severity.SUGGESTION

    def test_unknown_defaults_info(self):
        assert _parse_severity("UNKNOWN") == Severity.INFO


class TestParseReview:
    def test_parses_summary(self):
        result = _parse_review(SAMPLE_REVIEW_RESPONSE, "claude/default")
        assert "SQL injection" in result.summary

    def test_parses_rating(self):
        result = _parse_review(SAMPLE_REVIEW_RESPONSE, "claude/default")
        assert result.overall_rating == "🚨 Needs work"

    def test_parses_lgtm(self):
        response = "## Summary\nLooks good.\n## Rating\n✅ LGTM\n## Findings\nNo significant issues found."
        result = _parse_review(response, "claude/default")
        assert result.overall_rating == "✅ LGTM"

    def test_parses_findings_count(self):
        result = _parse_review(SAMPLE_REVIEW_RESPONSE, "claude/default")
        assert len(result.comments) == 2

    def test_parses_critical_finding(self):
        result = _parse_review(SAMPLE_REVIEW_RESPONSE, "claude/default")
        critical = [c for c in result.comments if c.severity == Severity.CRITICAL]
        assert len(critical) == 1
        assert "SQL Injection" in critical[0].title
        assert critical[0].file == "src/auth.py"
        assert critical[0].category == "security"

    def test_parses_warning_finding(self):
        result = _parse_review(SAMPLE_REVIEW_RESPONSE, "claude/default")
        warnings = [c for c in result.comments if c.severity == Severity.WARNING]
        assert len(warnings) == 1
        assert "Removed" in warnings[0].title

    def test_model_label_stored(self):
        result = _parse_review(SAMPLE_REVIEW_RESPONSE, "claude/opus")
        assert result.provider_model == "claude/opus"

    def test_empty_findings(self):
        response = "## Summary\nLooks good.\n## Rating\n✅ LGTM\n## Findings\nNo significant issues found."
        result = _parse_review(response, "model")
        assert result.comments == []


class TestReviewDiff:
    def test_calls_provider_and_parses(self):
        mock_provider = MagicMock()
        mock_provider.complete.return_value = SAMPLE_REVIEW_RESPONSE

        result = review_diff(
            diff=SAMPLE_DIFF,
            provider=mock_provider,
            focus="security",
            model_label="test/model",
        )

        assert isinstance(result, ReviewResult)
        mock_provider.complete.assert_called_once()
        call_args = mock_provider.complete.call_args
        system_prompt = call_args[0][0]
        assert "security" in system_prompt.lower()

    def test_passes_context_to_prompt(self):
        mock_provider = MagicMock()
        mock_provider.complete.return_value = SAMPLE_REVIEW_RESPONSE

        review_diff(
            diff=SAMPLE_DIFF,
            provider=mock_provider,
            context="Auth module — security critical",
        )

        user_prompt = mock_provider.complete.call_args[0][1]
        assert "Auth module" in user_prompt

    def test_injects_python_language_hints(self):
        """review_diff should inject Python-specific hints for .py files."""
        mock_provider = MagicMock()
        mock_provider.complete.return_value = SAMPLE_REVIEW_RESPONSE

        py_diff = DiffResult(
            diff="diff --git a/main.py b/main.py\n+def f(x=[]):\n+    pass\n",
            files_changed=["main.py"],
            insertions=2,
            deletions=0,
            is_empty=False,
        )

        review_diff(diff=py_diff, provider=mock_provider)

        system_prompt = mock_provider.complete.call_args[0][0]
        assert "Python" in system_prompt
        assert "Mutable default" in system_prompt

    def test_no_language_hints_for_unknown_files(self):
        """review_diff should not inject hints for files with unknown extensions."""
        mock_provider = MagicMock()
        mock_provider.complete.return_value = SAMPLE_REVIEW_RESPONSE

        unknown_diff = DiffResult(
            diff="diff --git a/config.yaml b/config.yaml\n+key: value\n",
            files_changed=["config.yaml"],
            insertions=1,
            deletions=0,
            is_empty=False,
        )

        review_diff(diff=unknown_diff, provider=mock_provider)

        system_prompt = mock_provider.complete.call_args[0][0]
        assert "Language-specific" not in system_prompt
