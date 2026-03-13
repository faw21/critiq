"""Git diff and file utilities for critiq."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DiffResult:
    """Represents the result of a git diff operation."""

    diff: str
    files_changed: list[str]
    insertions: int
    deletions: int
    is_empty: bool


def _run_git(args: list[str], cwd: Path | None = None) -> str:
    """Run a git command and return stdout, raising on error."""
    result = subprocess.run(
        ["git"] + args,
        capture_output=True,
        text=True,
        cwd=cwd or Path.cwd(),
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def get_staged_diff(cwd: Path | None = None) -> DiffResult:
    """Get the diff of staged changes (git diff --cached)."""
    try:
        diff = _run_git(["diff", "--cached"], cwd=cwd)
        files = _get_changed_files(["diff", "--cached", "--name-only"], cwd)
        insertions, deletions = _count_lines(diff)
        return DiffResult(
            diff=diff,
            files_changed=files,
            insertions=insertions,
            deletions=deletions,
            is_empty=not diff.strip(),
        )
    except RuntimeError as e:
        raise RuntimeError(f"Failed to get staged diff: {e}") from e


def get_branch_diff(base: str = "main", cwd: Path | None = None) -> DiffResult:
    """Get the diff between current branch and base branch."""
    # Try base branch, fall back to origin/base
    for ref in [base, f"origin/{base}"]:
        try:
            diff = _run_git(["diff", ref, "HEAD"], cwd=cwd)
            files = _get_changed_files(["diff", ref, "HEAD", "--name-only"], cwd)
            insertions, deletions = _count_lines(diff)
            return DiffResult(
                diff=diff,
                files_changed=files,
                insertions=insertions,
                deletions=deletions,
                is_empty=not diff.strip(),
            )
        except RuntimeError:
            continue
    raise RuntimeError(
        f"Could not diff against '{base}'. "
        f"Make sure the branch exists (tried '{base}' and 'origin/{base}')."
    )


def get_file_diff(file_path: str, base: str | None = None, cwd: Path | None = None) -> DiffResult:
    """Get the diff for a specific file."""
    if base:
        args = ["diff", base, "HEAD", "--", file_path]
    else:
        # Staged + unstaged for this file
        staged = _safe_run_git(["diff", "--cached", "--", file_path], cwd) or ""
        unstaged = _safe_run_git(["diff", "--", file_path], cwd) or ""
        diff = staged + unstaged
        files = [file_path] if diff.strip() else []
        insertions, deletions = _count_lines(diff)
        return DiffResult(
            diff=diff,
            files_changed=files,
            insertions=insertions,
            deletions=deletions,
            is_empty=not diff.strip(),
        )

    try:
        diff = _run_git(args, cwd=cwd)
        files = [file_path] if diff.strip() else []
        insertions, deletions = _count_lines(diff)
        return DiffResult(
            diff=diff,
            files_changed=files,
            insertions=insertions,
            deletions=deletions,
            is_empty=not diff.strip(),
        )
    except RuntimeError as e:
        raise RuntimeError(f"Failed to get diff for {file_path}: {e}") from e


def get_current_branch(cwd: Path | None = None) -> str:
    """Return the current git branch name."""
    try:
        return _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd).strip()
    except RuntimeError:
        return "unknown"


def is_git_repo(path: Path | None = None) -> bool:
    """Return True if the path is inside a git repository."""
    try:
        _run_git(["rev-parse", "--git-dir"], cwd=path or Path.cwd())
        return True
    except RuntimeError:
        return False


def _get_changed_files(args: list[str], cwd: Path | None) -> list[str]:
    """Run git command and return list of file paths."""
    try:
        output = _run_git(args, cwd=cwd)
        return [f for f in output.strip().splitlines() if f]
    except RuntimeError:
        return []


def _safe_run_git(args: list[str], cwd: Path | None) -> str:
    """Run git command, return empty string on failure."""
    try:
        return _run_git(args, cwd=cwd)
    except RuntimeError:
        return ""


def _count_lines(diff: str) -> tuple[int, int]:
    """Count insertions and deletions from a unified diff string."""
    insertions = 0
    deletions = 0
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            insertions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1
    return insertions, deletions
