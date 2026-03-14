"""Code quality trend reporting for critiq."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .git_utils import DiffResult, _count_lines, _run_git
from .providers import LLMProvider
from .reviewer import Severity, review_diff

MAX_DIFF_CHARS = 4000  # truncate large diffs for cost efficiency
CACHE_DIR_NAME = ".critiq-report"


@dataclass
class CommitInfo:
    """Metadata about a single commit."""

    full_hash: str
    short_hash: str
    author: str
    date: str  # ISO format
    message: str


@dataclass
class CommitReview:
    """Review results for a single commit."""

    commit: CommitInfo
    critical: int
    warning: int
    info: int
    suggestion: int
    files_with_issues: list[str]
    summary: str
    skipped: bool = False  # True if diff was empty


@dataclass
class FullReport:
    """The complete code quality trend report."""

    commit_reviews: list[CommitReview]
    total_commits: int
    total_issues: int
    hotspot_files: list[tuple[str, int]]  # (file, issue_count)
    trend: str  # "improving", "degrading", "stable"
    generated_at: str


def get_commit_history(
    n: int = 10,
    since: str | None = None,
    cwd: Path | None = None,
) -> list[CommitInfo]:
    """Get list of recent commits with metadata."""
    args = ["log", "--format=%H|%h|%an|%ai|%s"]
    if since:
        args += [f"{since}..HEAD"]
    else:
        args += [f"-{n}"]

    try:
        output = _run_git(args, cwd=cwd)
    except RuntimeError:
        return []

    commits = []
    for line in output.strip().splitlines():
        if "|" not in line:
            continue
        parts = line.split("|", 4)
        if len(parts) < 5:
            continue
        full_hash, short_hash, author, date, message = parts
        commits.append(
            CommitInfo(
                full_hash=full_hash.strip(),
                short_hash=short_hash.strip(),
                author=author.strip(),
                date=date.strip(),
                message=message.strip(),
            )
        )
    return commits


def get_commit_diff(
    full_hash: str,
    cwd: Path | None = None,
) -> DiffResult:
    """Get diff for a single commit vs its parent."""
    try:
        diff = _run_git(["diff", f"{full_hash}^", full_hash], cwd=cwd)
        files_output = _run_git(
            ["diff", "--name-only", f"{full_hash}^", full_hash], cwd=cwd
        )
    except RuntimeError:
        # First commit (no parent) — use git show
        try:
            diff = _run_git(
                ["show", "--format=", "--patch", full_hash], cwd=cwd
            )
            files_output = _run_git(
                ["show", "--format=", "--name-only", full_hash], cwd=cwd
            )
        except RuntimeError:
            return DiffResult(
                diff="",
                files_changed=[],
                insertions=0,
                deletions=0,
                is_empty=True,
            )

    files = [f for f in files_output.strip().splitlines() if f]
    insertions, deletions = _count_lines(diff)
    return DiffResult(
        diff=diff,
        files_changed=files,
        insertions=insertions,
        deletions=deletions,
        is_empty=not diff.strip(),
    )


def _load_cache(cache_dir: Path, commit_hash: str) -> CommitReview | None:
    """Load cached review for a commit."""
    cache_file = cache_dir / f"{commit_hash[:12]}.json"
    if not cache_file.exists():
        return None
    try:
        data = json.loads(cache_file.read_text())
        commit = CommitInfo(**data["commit"])
        return CommitReview(
            commit=commit,
            critical=data["critical"],
            warning=data["warning"],
            info=data["info"],
            suggestion=data["suggestion"],
            files_with_issues=data["files_with_issues"],
            summary=data["summary"],
            skipped=data.get("skipped", False),
        )
    except (KeyError, json.JSONDecodeError, TypeError):
        return None


def _save_cache(cache_dir: Path, review: CommitReview) -> None:
    """Save commit review to cache."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{review.commit.full_hash[:12]}.json"
    data = {
        "commit": asdict(review.commit),
        "critical": review.critical,
        "warning": review.warning,
        "info": review.info,
        "suggestion": review.suggestion,
        "files_with_issues": review.files_with_issues,
        "summary": review.summary,
        "skipped": review.skipped,
    }
    cache_file.write_text(json.dumps(data, indent=2))


def review_commit(
    commit: CommitInfo,
    provider: LLMProvider,
    cwd: Path | None = None,
    use_cache: bool = True,
    cache_dir: Path | None = None,
) -> CommitReview:
    """Review a single commit's diff."""
    resolved_cache = cache_dir or (Path(cwd or Path.cwd()) / CACHE_DIR_NAME)

    if use_cache:
        cached = _load_cache(resolved_cache, commit.full_hash)
        if cached is not None:
            return cached

    diff_result = get_commit_diff(commit.full_hash, cwd=cwd)

    if diff_result.is_empty:
        review = CommitReview(
            commit=commit,
            critical=0,
            warning=0,
            info=0,
            suggestion=0,
            files_with_issues=[],
            summary="No changes in this commit.",
            skipped=True,
        )
        if use_cache:
            _save_cache(resolved_cache, review)
        return review

    # Truncate large diffs for cost efficiency
    diff_text = diff_result.diff
    truncated = len(diff_text) > MAX_DIFF_CHARS
    if truncated:
        diff_text = diff_text[:MAX_DIFF_CHARS] + "\n... (truncated for cost efficiency)"
        diff_result = DiffResult(
            diff=diff_text,
            files_changed=diff_result.files_changed,
            insertions=diff_result.insertions,
            deletions=diff_result.deletions,
            is_empty=False,
        )

    try:
        result = review_diff(
            diff=diff_result,
            provider=provider,
            focus="all",
            context=f"Commit: {commit.message}",
            model_label="report",
        )
    except Exception:
        review = CommitReview(
            commit=commit,
            critical=0,
            warning=0,
            info=0,
            suggestion=0,
            files_with_issues=[],
            summary="Review failed.",
            skipped=True,
        )
        if use_cache:
            _save_cache(resolved_cache, review)
        return review

    severity_counts = {s.value: 0 for s in Severity}
    files_with_issues: set[str] = set()
    for comment in result.comments:
        severity_counts[comment.severity.value] += 1
        if comment.file:
            files_with_issues.add(comment.file)

    review = CommitReview(
        commit=commit,
        critical=severity_counts["critical"],
        warning=severity_counts["warning"],
        info=severity_counts["info"],
        suggestion=severity_counts["suggestion"],
        files_with_issues=sorted(files_with_issues),
        summary=result.summary,
        skipped=False,
    )

    if use_cache:
        _save_cache(resolved_cache, review)

    return review


def _determine_trend(reviews: list[CommitReview]) -> str:
    """Determine if code quality is improving, degrading, or stable.

    Compares weighted issue density between the first and second half
    of the commit history (chronological order).
    """
    non_skipped = [r for r in reviews if not r.skipped]
    if len(non_skipped) < 3:
        return "stable"

    # Commits list is newest-first; reverse for chronological order
    chronological = list(reversed(non_skipped))
    mid = len(chronological) // 2

    def weighted(r: CommitReview) -> float:
        return r.critical * 4.0 + r.warning * 2.0 + r.info * 1.0 + r.suggestion * 0.5

    first_avg = sum(weighted(r) for r in chronological[:mid]) / mid
    second_len = len(chronological) - mid
    second_avg = sum(weighted(r) for r in chronological[mid:]) / second_len

    if second_avg > first_avg * 1.2:
        return "degrading"
    elif second_avg < first_avg * 0.8:
        return "improving"
    return "stable"


def build_report(reviews: list[CommitReview]) -> FullReport:
    """Build the full report from individual commit reviews."""
    total_issues = sum(
        r.critical + r.warning + r.info + r.suggestion
        for r in reviews
        if not r.skipped
    )

    file_counts: dict[str, int] = {}
    for review in reviews:
        for f in review.files_with_issues:
            file_counts[f] = file_counts.get(f, 0) + 1

    hotspot_files = sorted(file_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    return FullReport(
        commit_reviews=reviews,
        total_commits=len(reviews),
        total_issues=total_issues,
        hotspot_files=hotspot_files,
        trend=_determine_trend(reviews),
        generated_at=datetime.now().isoformat(),
    )
