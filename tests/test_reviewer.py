"""Tests for reviewer module."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from critiq.git_utils import DiffResult
from critiq.reviewer import (
    ReviewResult,
    Severity,
    _build_system_prompt,
    _build_user_prompt,
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
