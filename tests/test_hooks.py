"""Tests for critiq.hooks module."""
from __future__ import annotations

import stat
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from critiq.hooks import install, uninstall, _find_git_dir, _install_hook


# ── _find_git_dir ─────────────────────────────────────────────────────────────


def test_find_git_dir_found(tmp_path):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    with patch("critiq.hooks.Path.cwd", return_value=tmp_path):
        result = _find_git_dir()
    assert result == git_dir


def test_find_git_dir_not_found(tmp_path):
    # tmp_path has no .git
    with patch("critiq.hooks.Path.cwd", return_value=tmp_path):
        result = _find_git_dir()
    assert result is None


# ── _install_hook ─────────────────────────────────────────────────────────────


def test_install_hook_creates_new(tmp_path):
    hooks_dir = tmp_path / "hooks"
    hooks_dir.mkdir()
    _install_hook(hooks_dir, "pre-commit", "#!/bin/sh\ncritiq\n", "# critiq", force=False)
    hook = hooks_dir / "pre-commit"
    assert hook.exists()
    assert "critiq" in hook.read_text()
    # Check executable bit
    assert hook.stat().st_mode & stat.S_IXUSR


def test_install_hook_appends_to_existing(tmp_path):
    hooks_dir = tmp_path / "hooks"
    hooks_dir.mkdir()
    existing_hook = hooks_dir / "pre-commit"
    existing_hook.write_text("#!/bin/sh\nnpm test\n")
    _install_hook(hooks_dir, "pre-commit", "# critiq\ncritiq --staged\n", "# critiq", force=False)
    content = existing_hook.read_text()
    assert "npm test" in content
    assert "critiq --staged" in content


def test_install_hook_skips_if_already_installed(tmp_path):
    hooks_dir = tmp_path / "hooks"
    hooks_dir.mkdir()
    existing_hook = hooks_dir / "pre-commit"
    existing_hook.write_text("#!/bin/sh\n# critiq pre-commit hook\ncritiq --staged\n")
    _install_hook(hooks_dir, "pre-commit", "# critiq\nnew content\n", "# critiq", force=False)
    # Should not overwrite
    content = existing_hook.read_text()
    assert "new content" not in content


def test_install_hook_force_overwrites(tmp_path):
    hooks_dir = tmp_path / "hooks"
    hooks_dir.mkdir()
    existing_hook = hooks_dir / "pre-commit"
    existing_hook.write_text("#!/bin/sh\n# critiq pre-commit hook\nold content\n")
    _install_hook(hooks_dir, "pre-commit", "#!/bin/sh\nnew content\n", "# critiq", force=True)
    content = existing_hook.read_text()
    assert "new content" in content
    assert "old content" not in content


# ── CLI: install ──────────────────────────────────────────────────────────────


def test_install_command_no_git(tmp_path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # No .git directory
        with patch("critiq.hooks._find_git_dir", return_value=None):
            result = runner.invoke(install, [])
    assert result.exit_code == 1
    assert "git repository" in result.output.lower() or "Error" in result.output


def test_install_command_creates_pre_commit(tmp_path):
    runner = CliRunner()
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    with patch("critiq.hooks._find_git_dir", return_value=git_dir):
        result = runner.invoke(install, [])
    assert result.exit_code == 0
    hook = git_dir / "hooks" / "pre-commit"
    assert hook.exists()
    assert "✅" in result.output


def test_install_command_creates_pre_push(tmp_path):
    runner = CliRunner()
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    with patch("critiq.hooks._find_git_dir", return_value=git_dir):
        result = runner.invoke(install, ["--pre-push"])
    assert result.exit_code == 0
    hook = git_dir / "hooks" / "pre-push"
    assert hook.exists()


# ── CLI: uninstall ─────────────────────────────────────────────────────────────


def test_uninstall_command_no_hook(tmp_path):
    runner = CliRunner()
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "hooks").mkdir()
    with patch("critiq.hooks._find_git_dir", return_value=git_dir):
        result = runner.invoke(uninstall, [])
    assert result.exit_code == 0
    assert "No pre-commit hook found" in result.output


def test_uninstall_removes_hook(tmp_path):
    runner = CliRunner()
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir()
    hook = hooks_dir / "pre-commit"
    hook.write_text("#!/bin/sh\n# critiq pre-commit hook\ncritiq --staged\n")
    with patch("critiq.hooks._find_git_dir", return_value=git_dir):
        result = runner.invoke(uninstall, [])
    assert result.exit_code == 0
    # Hook deleted since nothing else left
    assert not hook.exists() or hook.read_text().strip() == "#!/bin/sh"


def test_uninstall_preserves_existing_hook(tmp_path):
    runner = CliRunner()
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir()
    hook = hooks_dir / "pre-commit"
    hook.write_text("#!/bin/sh\nnpm test\n\n# critiq pre-commit hook\ncritiq --staged\n")
    with patch("critiq.hooks._find_git_dir", return_value=git_dir):
        result = runner.invoke(uninstall, [])
    assert result.exit_code == 0
    assert hook.exists()
    content = hook.read_text()
    assert "npm test" in content
    assert "critiq" not in content
