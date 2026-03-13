"""Tests for formatter module."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from critiq.formatter import print_review, print_review_compact
from critiq.reviewer import ReviewComment, ReviewResult, Severity


def _make_console():
    """Return a Console that writes to a string buffer."""
    buf = StringIO()
    return Console(file=buf, highlight=False, markup=True), buf


CLEAN_RESULT = ReviewResult(
    comments=[],
    summary="All good, no issues.",
    overall_rating="✅ LGTM",
    provider_model="claude/default",
)

WARNING_RESULT = ReviewResult(
    comments=[
        ReviewComment(
            severity=Severity.WARNING,
            file="auth.py",
            line="L10",
            title="Missing null check",
            body="**Issue:** May raise TypeError\n**Fix:** Add None check",
            category="correctness",
        ),
        ReviewComment(
            severity=Severity.INFO,
            file="utils.py",
            line="L5-10",
            title="Unused variable",
            body="**Issue:** `tmp` is never used\n**Fix:** Remove it",
            category="style",
        ),
    ],
    summary="Minor issues found.",
    overall_rating="⚠️ Minor issues",
    provider_model="openai/gpt-4o",
)

CRITICAL_RESULT = ReviewResult(
    comments=[
        ReviewComment(
            severity=Severity.CRITICAL,
            file="db.py",
            line="L42",
            title="SQL Injection",
            body="**Issue:** Unsanitized input\n**Fix:** Use parameterized queries",
            category="security",
        )
    ],
    summary="Critical security issue.",
    overall_rating="🚨 Needs work",
    provider_model="claude/opus",
)


class TestPrintReview:
    def test_clean_result_shows_lgtm(self):
        console, buf = _make_console()
        print_review(CLEAN_RESULT, console=console)
        output = buf.getvalue()
        assert "LGTM" in output
        assert "No issues found" in output

    def test_shows_model_info(self):
        console, buf = _make_console()
        print_review(WARNING_RESULT, console=console)
        output = buf.getvalue()
        assert "openai/gpt-4o" in output

    def test_shows_summary(self):
        console, buf = _make_console()
        print_review(WARNING_RESULT, console=console)
        output = buf.getvalue()
        assert "Minor issues found" in output

    def test_shows_finding_titles(self):
        console, buf = _make_console()
        print_review(WARNING_RESULT, console=console)
        output = buf.getvalue()
        assert "Missing null check" in output
        assert "Unused variable" in output

    def test_shows_file_references(self):
        console, buf = _make_console()
        print_review(WARNING_RESULT, console=console)
        output = buf.getvalue()
        assert "auth.py" in output

    def test_shows_severity_counts(self):
        console, buf = _make_console()
        print_review(WARNING_RESULT, console=console)
        output = buf.getvalue()
        assert "WARNING" in output

    def test_critical_shows_needs_work(self):
        console, buf = _make_console()
        print_review(CRITICAL_RESULT, console=console)
        output = buf.getvalue()
        assert "Needs work" in output

    def test_shows_footer(self):
        console, buf = _make_console()
        print_review(CLEAN_RESULT, console=console)
        output = buf.getvalue()
        assert "critiq" in output.lower()


class TestPrintReviewCompact:
    def test_shows_rating(self):
        console, buf = _make_console()
        print_review_compact(CLEAN_RESULT, console=console)
        output = buf.getvalue()
        assert "LGTM" in output

    def test_shows_findings(self):
        console, buf = _make_console()
        print_review_compact(WARNING_RESULT, console=console)
        output = buf.getvalue()
        assert "Missing null check" in output

    def test_compact_is_shorter_than_full(self):
        """Compact output should be shorter than full output."""
        full_console, full_buf = _make_console()
        compact_console, compact_buf = _make_console()

        print_review(WARNING_RESULT, console=full_console)
        print_review_compact(WARNING_RESULT, console=compact_console)

        assert len(compact_buf.getvalue()) < len(full_buf.getvalue())

    def test_shows_severity_labels(self):
        console, buf = _make_console()
        print_review_compact(CRITICAL_RESULT, console=console)
        output = buf.getvalue()
        assert "CRITICAL" in output
