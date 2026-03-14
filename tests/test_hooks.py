"""Tests for critiq-install and critiq-uninstall hook management."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
from click.testing import CliRunner

from critiq.hooks import install, uninstall, _CRITIQ_MARKER, _CRITIQ_PUSH_MARKER


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """Create a fake git repo with a .git/hooks directory."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir()
    return tmp_path


# ── Install tests ─────────────────────────────────────────────────────────────

class TestInstall:
    def test_install_precommit_creates_hook(self, fake_repo: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=fake_repo):
            result = runner.invoke(install, [])

        assert result.exit_code == 0
        hook = fake_repo / ".git" / "hooks" / "pre-commit"
        assert hook.exists()
        content = hook.read_text()
        assert _CRITIQ_MARKER in content
        assert "critiq --staged --severity critical --compact" in content

    def test_install_makes_hook_executable(self, fake_repo: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=fake_repo):
            runner.invoke(install, [])

        hook = fake_repo / ".git" / "hooks" / "pre-commit"
        mode = hook.stat().st_mode
        assert mode & stat.S_IXUSR  # owner executable

    def test_install_prepush(self, fake_repo: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=fake_repo):
            result = runner.invoke(install, ["--pre-push"])

        assert result.exit_code == 0
        hook = fake_repo / ".git" / "hooks" / "pre-push"
        assert hook.exists()
        content = hook.read_text()
        assert _CRITIQ_PUSH_MARKER in content
        assert "critiq --diff" in content

    def test_install_idempotent(self, fake_repo: Path) -> None:
        """Running install twice doesn't duplicate the hook."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=fake_repo):
            runner.invoke(install, [])
            result = runner.invoke(install, [])

        assert result.exit_code == 0
        assert "already installed" in result.output
        hook = fake_repo / ".git" / "hooks" / "pre-commit"
        content = hook.read_text()
        assert content.count(_CRITIQ_MARKER) == 1

    def test_install_appends_to_existing_hook(self, fake_repo: Path) -> None:
        """Existing hook gets critiq appended, not overwritten."""
        hooks_dir = fake_repo / ".git" / "hooks"
        existing_hook = hooks_dir / "pre-commit"
        existing_hook.write_text("#!/bin/sh\necho 'existing hook'\n")
        existing_hook.chmod(0o755)

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=fake_repo):
            result = runner.invoke(install, [])

        assert result.exit_code == 0
        content = existing_hook.read_text()
        assert "existing hook" in content
        assert _CRITIQ_MARKER in content

    def test_install_force_overwrites_existing(self, fake_repo: Path) -> None:
        """--force replaces an existing hook entirely."""
        hooks_dir = fake_repo / ".git" / "hooks"
        existing_hook = hooks_dir / "pre-commit"
        existing_hook.write_text("#!/bin/sh\necho 'existing hook'\n")

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=fake_repo):
            runner.invoke(install, ["--force"])

        content = existing_hook.read_text()
        assert "existing hook" not in content
        assert _CRITIQ_MARKER in content

    def test_install_fails_outside_git_repo(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(install, [])

        assert result.exit_code == 1
        assert "Not inside a git repository" in result.output

    def test_install_success_message(self, fake_repo: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=fake_repo):
            result = runner.invoke(install, [])

        assert "✅" in result.output
        assert "pre-commit hook installed" in result.output

    def test_install_prepush_success_message(self, fake_repo: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=fake_repo):
            result = runner.invoke(install, ["--pre-push"])

        assert "pre-push hook installed" in result.output


# ── Uninstall tests ───────────────────────────────────────────────────────────

class TestUninstall:
    def test_uninstall_removes_critiq_only_hook(self, fake_repo: Path) -> None:
        """If hook only has critiq content, the file is deleted."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=fake_repo):
            runner.invoke(install, [])
            result = runner.invoke(uninstall, [])

        assert result.exit_code == 0
        hook = fake_repo / ".git" / "hooks" / "pre-commit"
        assert not hook.exists()

    def test_uninstall_strips_from_mixed_hook(self, fake_repo: Path) -> None:
        """Critiq block is removed; rest of the hook survives."""
        hooks_dir = fake_repo / ".git" / "hooks"
        existing_hook = hooks_dir / "pre-commit"
        existing_hook.write_text("#!/bin/sh\necho 'other hook'\n")
        existing_hook.chmod(0o755)

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=fake_repo):
            runner.invoke(install, [])
            result = runner.invoke(uninstall, [])

        assert result.exit_code == 0
        assert existing_hook.exists()
        content = existing_hook.read_text()
        assert "other hook" in content
        assert _CRITIQ_MARKER not in content

    def test_uninstall_no_hook(self, fake_repo: Path) -> None:
        """Uninstalling when no hook exists is a no-op."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=fake_repo):
            result = runner.invoke(uninstall, [])

        assert result.exit_code == 0
        assert "No pre-commit hook found" in result.output

    def test_uninstall_hook_without_critiq(self, fake_repo: Path) -> None:
        """Uninstalling when critiq isn't in the hook says nothing to remove."""
        hooks_dir = fake_repo / ".git" / "hooks"
        existing_hook = hooks_dir / "pre-commit"
        existing_hook.write_text("#!/bin/sh\necho 'other'\n")

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=fake_repo):
            result = runner.invoke(uninstall, [])

        assert result.exit_code == 0
        assert "Nothing to remove" in result.output

    def test_uninstall_prepush(self, fake_repo: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=fake_repo):
            runner.invoke(install, ["--pre-push"])
            result = runner.invoke(uninstall, ["--pre-push"])

        assert result.exit_code == 0
        hook = fake_repo / ".git" / "hooks" / "pre-push"
        assert not hook.exists()

    def test_uninstall_fails_outside_git_repo(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(uninstall, [])

        assert result.exit_code == 1
        assert "Not inside a git repository" in result.output
