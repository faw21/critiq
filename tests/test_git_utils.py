"""Tests for git_utils module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from critiq.git_utils import (
    DiffResult,
    _count_lines,
    get_branch_diff,
    get_current_branch,
    get_file_diff,
    get_staged_diff,
    is_git_repo,
)


SAMPLE_DIFF = """\
diff --git a/src/auth.py b/src/auth.py
index abc123..def456 100644
--- a/src/auth.py
+++ b/src/auth.py
@@ -10,6 +10,10 @@ def login(user, password):
     if not user:
         return None
+    # Validate password strength
+    if len(password) < 8:
+        raise ValueError("Password too short")
+
     return authenticate(user, password)
-    pass
"""


def test_count_lines_basic():
    assert _count_lines(SAMPLE_DIFF) == (4, 1)


def test_count_lines_empty():
    assert _count_lines("") == (0, 0)


def test_count_lines_no_changes():
    diff = "diff --git a/file b/file\n--- a/file\n+++ b/file\n"
    assert _count_lines(diff) == (0, 0)


class TestGetStagedDiff:
    def test_returns_diff_result(self):
        with patch("critiq.git_utils._run_git") as mock_git:
            mock_git.side_effect = [
                SAMPLE_DIFF,  # diff --cached
                "src/auth.py\n",  # diff --cached --name-only
            ]
            result = get_staged_diff()

        assert isinstance(result, DiffResult)
        assert result.diff == SAMPLE_DIFF
        assert result.files_changed == ["src/auth.py"]
        assert result.insertions == 4
        assert result.deletions == 1
        assert not result.is_empty

    def test_empty_staged(self):
        with patch("critiq.git_utils._run_git") as mock_git:
            mock_git.side_effect = ["", ""]
            result = get_staged_diff()

        assert result.is_empty
        assert result.files_changed == []

    def test_raises_on_git_error(self):
        with patch("critiq.git_utils._run_git") as mock_git:
            mock_git.side_effect = RuntimeError("not a git repo")

        with pytest.raises(RuntimeError, match="Failed to get staged diff"):
            get_staged_diff()


class TestGetBranchDiff:
    def test_returns_diff_result(self):
        with patch("critiq.git_utils._run_git") as mock_git:
            mock_git.side_effect = [
                SAMPLE_DIFF,  # diff main HEAD
                "src/auth.py\n",  # diff --name-only
            ]
            result = get_branch_diff(base="main")

        assert isinstance(result, DiffResult)
        assert not result.is_empty

    def test_falls_back_to_origin(self):
        call_args = []

        def side_effect(args, cwd=None):
            call_args.append(args)
            if "main" in args and "origin" not in str(args):
                raise RuntimeError("unknown revision")
            if "origin/main" in args:
                if "--name-only" in args:
                    return "file.py\n"
                return SAMPLE_DIFF
            raise RuntimeError("fail")

        with patch("critiq.git_utils._run_git", side_effect=side_effect):
            result = get_branch_diff(base="main")

        assert not result.is_empty

    def test_raises_when_all_refs_fail(self):
        with patch("critiq.git_utils._run_git") as mock_git:
            mock_git.side_effect = RuntimeError("fail")

        with pytest.raises(RuntimeError, match="Could not diff against"):
            get_branch_diff(base="nonexistent")


class TestGetFileDiff:
    def test_with_base_branch(self):
        with patch("critiq.git_utils._run_git") as mock_git:
            mock_git.return_value = SAMPLE_DIFF
            result = get_file_diff("src/auth.py", base="main")

        assert not result.is_empty
        assert result.files_changed == ["src/auth.py"]

    def test_without_base_branch(self):
        with patch("critiq.git_utils._safe_run_git") as mock_safe:
            mock_safe.side_effect = [SAMPLE_DIFF, ""]  # staged, unstaged
            result = get_file_diff("src/auth.py")

        assert not result.is_empty

    def test_empty_file_diff(self):
        with patch("critiq.git_utils._run_git") as mock_git:
            mock_git.return_value = ""
            result = get_file_diff("src/auth.py", base="main")

        assert result.is_empty
        assert result.files_changed == []


class TestIsGitRepo:
    def test_returns_true_in_git_repo(self):
        with patch("critiq.git_utils._run_git") as mock_git:
            mock_git.return_value = ".git"
            assert is_git_repo() is True

    def test_returns_false_outside_git_repo(self):
        with patch("critiq.git_utils._run_git") as mock_git:
            mock_git.side_effect = RuntimeError("not a git repo")
            assert is_git_repo() is False


class TestGetCurrentBranch:
    def test_returns_branch_name(self):
        with patch("critiq.git_utils._run_git") as mock_git:
            mock_git.return_value = "feature/my-feature\n"
            assert get_current_branch() == "feature/my-feature"

    def test_returns_unknown_on_error(self):
        with patch("critiq.git_utils._run_git") as mock_git:
            mock_git.side_effect = RuntimeError("fail")
            assert get_current_branch() == "unknown"
