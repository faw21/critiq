"""Tests for critiq.report — code quality trend reporting."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from critiq.report import (
    CACHE_DIR_NAME,
    CommitInfo,
    CommitReview,
    FullReport,
    _determine_trend,
    _load_cache,
    _save_cache,
    build_report,
    get_commit_diff,
    get_commit_history,
    review_commit,
)
from critiq.report_cli import _save_markdown, _sparkline, main
from critiq.reviewer import ReviewComment, ReviewResult, Severity


# ── Fixtures ────────────────────────────────────────────────────────────────


def _commit(i: int, full_hash: str | None = None) -> CommitInfo:
    h = full_hash or f"abc{i:04d}ffff0000"
    return CommitInfo(
        full_hash=h,
        short_hash=h[:7],
        author=f"dev{i}",
        date="2026-03-13T10:00:00",
        message=f"feat: change {i}",
    )


def _review(
    commit: CommitInfo,
    critical: int = 0,
    warning: int = 0,
    info: int = 0,
    suggestion: int = 0,
    skipped: bool = False,
    files: list[str] | None = None,
) -> CommitReview:
    return CommitReview(
        commit=commit,
        critical=critical,
        warning=warning,
        info=info,
        suggestion=suggestion,
        files_with_issues=files or [],
        summary="Test summary.",
        skipped=skipped,
    )


# ── get_commit_history ───────────────────────────────────────────────────────


def test_get_commit_history_parses_output():
    raw = (
        "abc1234ffffffff|abc1234|Alice Dev|2026-03-13T10:00:00|feat: add login\n"
        "def5678ffffffff|def5678|Bob Dev|2026-03-12T09:00:00|fix: null check\n"
    )
    with patch("critiq.report._run_git", return_value=raw):
        history = get_commit_history(n=2)

    assert len(history) == 2
    assert history[0].short_hash == "abc1234"
    assert history[0].message == "feat: add login"
    assert history[1].author == "Bob Dev"


def test_get_commit_history_returns_empty_on_error():
    with patch("critiq.report._run_git", side_effect=RuntimeError("no repo")):
        result = get_commit_history()
    assert result == []


def test_get_commit_history_since_flag():
    with patch("critiq.report._run_git", return_value="") as mock_git:
        get_commit_history(since="v1.0.0")

    args_passed = mock_git.call_args[0][0]
    assert "v1.0.0..HEAD" in args_passed


def test_get_commit_history_skips_malformed_lines():
    raw = "no-pipes-here\nabc|def|Alice|2026-03-13|good commit\n"
    with patch("critiq.report._run_git", return_value=raw):
        history = get_commit_history()
    # Only the well-formed line should be parsed
    assert len(history) == 1
    assert history[0].short_hash == "def"


# ── get_commit_diff ──────────────────────────────────────────────────────────


def test_get_commit_diff_normal():
    fake_diff = "diff --git a/foo.py b/foo.py\n+new line\n-old line\n"
    with (
        patch("critiq.report._run_git", side_effect=[fake_diff, "foo.py\n"]),
    ):
        result = get_commit_diff("abc1234")

    assert result.diff == fake_diff
    assert result.files_changed == ["foo.py"]
    assert result.insertions == 1
    assert result.deletions == 1
    assert not result.is_empty


def test_get_commit_diff_first_commit_fallback():
    """First commit has no parent — falls back to git show."""
    fake_diff = "diff --git a/init.py b/init.py\n+created\n"
    with patch(
        "critiq.report._run_git",
        side_effect=[
            RuntimeError("bad revision '^'"),  # diff ^ fails
            fake_diff,                          # git show fallback
            "init.py\n",                        # name-only
        ],
    ):
        result = get_commit_diff("abc1234")

    assert not result.is_empty
    assert "created" in result.diff


def test_get_commit_diff_empty_on_total_failure():
    with patch("critiq.report._run_git", side_effect=RuntimeError("fail")):
        result = get_commit_diff("abc1234")
    assert result.is_empty


# ── Cache helpers ─────────────────────────────────────────────────────────────


def test_cache_round_trip():
    commit = _commit(1, full_hash="aabbccddee1122334455667788990011")
    review = _review(commit, critical=2, warning=1, files=["auth.py"])

    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = Path(tmpdir) / CACHE_DIR_NAME

        # Nothing cached yet
        assert _load_cache(cache_dir, commit.full_hash) is None

        _save_cache(cache_dir, review)
        loaded = _load_cache(cache_dir, commit.full_hash)

    assert loaded is not None
    assert loaded.critical == 2
    assert loaded.warning == 1
    assert loaded.files_with_issues == ["auth.py"]
    assert loaded.commit.message == commit.message


def test_load_cache_returns_none_on_corrupt_json():
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = Path(tmpdir)
        corrupt = cache_dir / "aabbccddee11.json"
        corrupt.write_text("not valid json")
        result = _load_cache(cache_dir, "aabbccddee111234")
    assert result is None


# ── review_commit ─────────────────────────────────────────────────────────────


def test_review_commit_uses_cache():
    commit = _commit(1, full_hash="cached_hash_" + "0" * 12)
    cached_review = _review(commit, critical=1)

    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = Path(tmpdir) / CACHE_DIR_NAME
        _save_cache(cache_dir, cached_review)

        mock_provider = MagicMock()
        result = review_commit(
            commit=commit,
            provider=mock_provider,
            cache_dir=cache_dir,
            use_cache=True,
        )

    # Provider should NOT have been called
    mock_provider.complete.assert_not_called()
    assert result.critical == 1


def test_review_commit_skips_empty_diff():
    from critiq.git_utils import DiffResult

    commit = _commit(2)
    empty_diff = DiffResult(diff="", files_changed=[], insertions=0, deletions=0, is_empty=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = Path(tmpdir)
        with patch("critiq.report.get_commit_diff", return_value=empty_diff):
            mock_provider = MagicMock()
            result = review_commit(
                commit=commit,
                provider=mock_provider,
                use_cache=False,
                cache_dir=cache_dir,
            )

    assert result.skipped is True
    mock_provider.complete.assert_not_called()


def test_review_commit_truncates_large_diff():
    from critiq.git_utils import DiffResult
    from critiq.report import MAX_DIFF_CHARS

    big_diff = "+" + "x" * (MAX_DIFF_CHARS + 500)
    commit = _commit(3)
    big_diff_result = DiffResult(
        diff=big_diff,
        files_changed=["big.py"],
        insertions=1,
        deletions=0,
        is_empty=False,
    )

    captured_diff: list[DiffResult] = []

    def fake_review_diff(diff: DiffResult, **kwargs: object) -> ReviewResult:
        captured_diff.append(diff)
        return ReviewResult(comments=[], summary="ok", overall_rating="✅ LGTM", provider_model="x")

    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = Path(tmpdir)
        with (
            patch("critiq.report.get_commit_diff", return_value=big_diff_result),
            patch("critiq.report.review_diff", side_effect=fake_review_diff),
        ):
            review_commit(
                commit=commit,
                provider=MagicMock(),
                use_cache=False,
                cache_dir=cache_dir,
            )

    assert len(captured_diff[0].diff) <= MAX_DIFF_CHARS + 60  # small overhead for truncation msg


def test_review_commit_handles_provider_error():
    from critiq.git_utils import DiffResult

    commit = _commit(4)
    diff_result = DiffResult(
        diff="diff --git a/x.py b/x.py\n+line\n",
        files_changed=["x.py"],
        insertions=1,
        deletions=0,
        is_empty=False,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = Path(tmpdir)
        with (
            patch("critiq.report.get_commit_diff", return_value=diff_result),
            patch("critiq.report.review_diff", side_effect=RuntimeError("API error")),
        ):
            result = review_commit(
                commit=commit,
                provider=MagicMock(),
                use_cache=False,
                cache_dir=cache_dir,
            )

    assert result.skipped is True


# ── _determine_trend ──────────────────────────────────────────────────────────


def test_determine_trend_improving():
    # Older commits (end of list) have many issues; newer (start) have fewer
    reviews = [
        _review(_commit(i), critical=0, warning=0) for i in range(3)  # new: clean
    ] + [
        _review(_commit(i + 3), critical=5, warning=3) for i in range(3)  # old: messy
    ]
    assert _determine_trend(reviews) == "improving"


def test_determine_trend_degrading():
    reviews = [
        _review(_commit(i), critical=4, warning=3) for i in range(3)  # new: messy
    ] + [
        _review(_commit(i + 3), critical=0, warning=0) for i in range(3)  # old: clean
    ]
    assert _determine_trend(reviews) == "degrading"


def test_determine_trend_stable():
    reviews = [_review(_commit(i), critical=1, warning=1) for i in range(6)]
    assert _determine_trend(reviews) == "stable"


def test_determine_trend_too_few_reviews():
    reviews = [_review(_commit(i), critical=5) for i in range(2)]
    assert _determine_trend(reviews) == "stable"


def test_determine_trend_skips_skipped():
    reviews = (
        [_review(_commit(i), skipped=True) for i in range(4)]
        + [_review(_commit(4), critical=0)]
        + [_review(_commit(5), critical=0)]
    )
    # Less than 3 non-skipped → stable
    assert _determine_trend(reviews) == "stable"


# ── build_report ──────────────────────────────────────────────────────────────


def test_build_report_counts_issues_and_hotspots():
    reviews = [
        _review(_commit(1), critical=1, warning=2, files=["auth.py", "api.py"]),
        _review(_commit(2), critical=0, warning=1, files=["auth.py"]),
        _review(_commit(3), skipped=True),
    ]
    report = build_report(reviews)

    assert report.total_commits == 3
    assert report.total_issues == 4  # 1+2 + 0+1, not counting skipped
    hotspot_dict = dict(report.hotspot_files)
    assert hotspot_dict["auth.py"] == 2
    assert hotspot_dict["api.py"] == 1
    assert report.trend in ("improving", "degrading", "stable")
    assert report.generated_at  # non-empty timestamp


def test_build_report_empty_reviews():
    report = build_report([])
    assert report.total_commits == 0
    assert report.total_issues == 0
    assert report.hotspot_files == []


# ── _sparkline ────────────────────────────────────────────────────────────────


def test_sparkline_all_zero():
    result = _sparkline([0, 0, 0], 0)
    assert result == "───"


def test_sparkline_values():
    result = _sparkline([0, 5, 10], 10)
    assert len(result) == 3
    # First char should be lowest, last should be highest
    assert result[0] < result[2]


# ── _save_markdown ────────────────────────────────────────────────────────────


def test_save_markdown_creates_file():
    reviews = [
        _review(_commit(1), critical=2, warning=1),
        _review(_commit(2), skipped=True),
    ]
    report = build_report(reviews)

    with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
        out = Path(f.name)

    _save_markdown(report, out)
    content = out.read_text()

    assert "# critiq Code Quality Report" in content
    assert "| Commit |" in content
    out.unlink()


# ── CLI ───────────────────────────────────────────────────────────────────────


def _make_review_list(n: int = 3) -> list[CommitReview]:
    return [_review(_commit(i), warning=i) for i in range(1, n + 1)]


def test_cli_not_in_git_repo():
    runner = CliRunner()
    with patch("critiq.report_cli.is_git_repo", return_value=False):
        result = runner.invoke(main, [])
    assert result.exit_code == 1
    assert "git repository" in result.output.lower()


def test_cli_no_commits_found():
    runner = CliRunner()
    with (
        patch("critiq.report_cli.is_git_repo", return_value=True),
        patch("critiq.report_cli.get_commit_history", return_value=[]),
    ):
        result = runner.invoke(main, [])
    assert result.exit_code == 0
    assert "No commits" in result.output


def test_cli_provider_error():
    runner = CliRunner()
    history = [_commit(1)]
    with (
        patch("critiq.report_cli.is_git_repo", return_value=True),
        patch("critiq.report_cli.get_commit_history", return_value=history),
        patch("critiq.report_cli.get_provider", side_effect=ValueError("no key")),
    ):
        result = runner.invoke(main, ["--provider", "claude"])
    assert result.exit_code == 1
    assert "Error" in result.output


def test_cli_full_run():
    runner = CliRunner()
    history = [_commit(i) for i in range(1, 4)]
    reviews = _make_review_list(3)

    with (
        patch("critiq.report_cli.is_git_repo", return_value=True),
        patch("critiq.report_cli.get_commit_history", return_value=history),
        patch("critiq.report_cli.get_provider", return_value=MagicMock()),
        patch("critiq.report_cli.review_commit", side_effect=reviews),
    ):
        result = runner.invoke(main, ["--commits", "3"])

    assert result.exit_code == 0
    assert "critiq report" in result.output


def test_cli_saves_markdown():
    runner = CliRunner()
    history = [_commit(1)]
    reviews = [_review(_commit(1), critical=1)]

    with (
        patch("critiq.report_cli.is_git_repo", return_value=True),
        patch("critiq.report_cli.get_commit_history", return_value=history),
        patch("critiq.report_cli.get_provider", return_value=MagicMock()),
        patch("critiq.report_cli.review_commit", side_effect=reviews),
        runner.isolated_filesystem(),
    ):
        result = runner.invoke(main, ["--output", "report.md"])

    assert result.exit_code == 0
    assert "saved" in result.output.lower()


def test_cli_version():
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "1.5.0" in result.output
