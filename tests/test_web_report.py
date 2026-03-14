"""Tests for critiq.web_report module."""
from __future__ import annotations

from pathlib import Path

import pytest

from critiq.web_report import generate_html, save_html
from critiq.reviewer import ReviewResult, ReviewComment, Severity


def _make_result(comments=None):
    return ReviewResult(
        comments=comments or [],
        summary="Some issues found.",
        overall_rating="⚠️ Minor issues",
        provider_model="test",
    )


def _make_comment(sev=Severity.WARNING, title="Test issue"):
    return ReviewComment(
        severity=sev,
        title=title,
        body="This is a test issue.",
        file="src/foo.py",
        line="10",
        category="general",
    )


# ── generate_html ─────────────────────────────────────────────────────────────


def test_generate_html_no_comments():
    result = _make_result()
    html = generate_html(result)
    assert "<html" in html
    assert "critiq" in html.lower()


def test_generate_html_with_critical():
    comment = _make_comment(sev=Severity.CRITICAL, title="SQL Injection")
    result = _make_result(comments=[comment])
    html = generate_html(result)
    assert "SQL Injection" in html
    assert "CRITICAL" in html.upper()
    assert "src/foo.py" in html


def test_generate_html_escapes_special_chars():
    comment = _make_comment(title="<script>alert('xss')</script>")
    result = _make_result(comments=[comment])
    html = generate_html(result)
    # Script tag should be HTML-escaped
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_generate_html_multiple_severities():
    comments = [
        _make_comment(Severity.CRITICAL, "Critical issue"),
        _make_comment(Severity.WARNING, "Warning issue"),
        _make_comment(Severity.INFO, "Info issue"),
    ]
    result = _make_result(comments=comments)
    html = generate_html(result)
    assert "Critical issue" in html
    assert "Warning issue" in html
    assert "Info issue" in html


def test_generate_html_custom_title():
    result = _make_result()
    html = generate_html(result, title="My PR Review")
    assert "My PR Review" in html


# ── save_html ─────────────────────────────────────────────────────────────────


def test_save_html_creates_file(tmp_path):
    result = _make_result(comments=[_make_comment()])
    dest = save_html(result, str(tmp_path / "report.html"))
    assert Path(dest).exists()
    content = Path(dest).read_text()
    assert "<html" in content


def test_save_html_returns_path(tmp_path):
    result = _make_result()
    dest = save_html(result, tmp_path / "myreport.html")
    assert isinstance(dest, Path)
    assert dest.exists()
