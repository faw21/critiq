"""Tests for critiq-learn CLI (critiq.learn module)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from critiq.config import CONFIG_FILENAME, CritiqConfig, load_config
from critiq.learn import main


def _run(args: list[str], cwd: str | None = None) -> object:
    runner = CliRunner()
    # mix_stderr=False keeps stdout and stderr separate
    return runner.invoke(main, args, catch_exceptions=False)


class TestLearnShow:
    def test_show_with_no_config(self, tmp_path):
        with patch("critiq.learn.find_config_path", return_value=None), \
             patch("critiq.learn.load_config", return_value=CritiqConfig()):
            result = _run(["show"])
        assert result.exit_code == 0
        assert "provider default" in result.output or "all" in result.output

    def test_show_with_config(self, tmp_path):
        config = CritiqConfig(
            ignore_patterns=["No type hints"],
            custom_rules=["Check SQL"],
            default_focus="security",
        )
        with patch("critiq.learn.find_config_path", return_value=tmp_path / CONFIG_FILENAME), \
             patch("critiq.learn.load_config", return_value=config):
            result = _run(["show"])
        assert result.exit_code == 0
        assert "No type hints" in result.output
        assert "Check SQL" in result.output
        assert "security" in result.output


class TestLearnIgnore:
    def test_ignore_adds_pattern(self, tmp_path):
        config_path = tmp_path / CONFIG_FILENAME
        with patch("critiq.learn.find_config_path", return_value=None), \
             patch("critiq.learn.load_config", return_value=CritiqConfig()), \
             patch("critiq.learn.save_config") as mock_save, \
             patch("critiq.learn.Path") as mock_path_cls:
            # Make Path.cwd() / CONFIG_FILENAME point to tmp_path
            mock_path_cls.cwd.return_value = tmp_path
            result = _run(["ignore", "No type hints"])
        assert result.exit_code == 0
        assert "Added ignore pattern" in result.output
        assert "No type hints" in result.output

    def test_ignore_duplicate_skips(self, tmp_path):
        existing = CritiqConfig(ignore_patterns=["No type hints"])
        with patch("critiq.learn.find_config_path", return_value=None), \
             patch("critiq.learn.load_config", return_value=existing), \
             patch("critiq.learn.save_config") as mock_save, \
             patch("critiq.learn.Path") as mock_path_cls:
            mock_path_cls.cwd.return_value = tmp_path
            result = _run(["ignore", "No type hints"])
        assert result.exit_code == 0
        assert "Already ignoring" in result.output
        mock_save.assert_not_called()


class TestLearnRule:
    def test_rule_adds_custom_rule(self, tmp_path):
        with patch("critiq.learn.find_config_path", return_value=None), \
             patch("critiq.learn.load_config", return_value=CritiqConfig()), \
             patch("critiq.learn.save_config") as mock_save, \
             patch("critiq.learn.Path") as mock_path_cls:
            mock_path_cls.cwd.return_value = tmp_path
            result = _run(["rule", "Always check SQL injection"])
        assert result.exit_code == 0
        assert "Added custom rule" in result.output
        assert "Always check SQL injection" in result.output

    def test_rule_duplicate_skips(self, tmp_path):
        existing = CritiqConfig(custom_rules=["Always check SQL injection"])
        with patch("critiq.learn.find_config_path", return_value=None), \
             patch("critiq.learn.load_config", return_value=existing), \
             patch("critiq.learn.save_config") as mock_save, \
             patch("critiq.learn.Path") as mock_path_cls:
            mock_path_cls.cwd.return_value = tmp_path
            result = _run(["rule", "Always check SQL injection"])
        assert result.exit_code == 0
        assert "already exists" in result.output
        mock_save.assert_not_called()


class TestLearnSet:
    def test_set_focus(self, tmp_path):
        with patch("critiq.learn.find_config_path", return_value=None), \
             patch("critiq.learn.load_config", return_value=CritiqConfig()), \
             patch("critiq.learn.save_config") as mock_save, \
             patch("critiq.learn.Path") as mock_path_cls:
            mock_path_cls.cwd.return_value = tmp_path
            result = _run(["set", "focus", "security"])
        assert result.exit_code == 0
        assert "security" in result.output

    def test_set_focus_invalid(self):
        result = _run(["set", "focus", "invalid_focus"])
        assert result.exit_code != 0

    def test_set_provider(self, tmp_path):
        with patch("critiq.learn.find_config_path", return_value=None), \
             patch("critiq.learn.load_config", return_value=CritiqConfig()), \
             patch("critiq.learn.save_config") as mock_save, \
             patch("critiq.learn.Path") as mock_path_cls:
            mock_path_cls.cwd.return_value = tmp_path
            result = _run(["set", "provider", "openai"])
        assert result.exit_code == 0
        assert "openai" in result.output


class TestLearnUnignore:
    def test_unignore_removes_pattern(self, tmp_path):
        config_file = tmp_path / CONFIG_FILENAME
        existing = CritiqConfig(ignore_patterns=["No type hints", "TODO"])
        with patch("critiq.learn.find_config_path", return_value=config_file), \
             patch("critiq.learn.load_config", return_value=existing), \
             patch("critiq.learn.save_config") as mock_save:
            result = _run(["unignore", "No type hints"])
        assert result.exit_code == 0
        assert "Removed ignore pattern" in result.output
        # Verify save was called with pattern removed
        saved_config = mock_save.call_args[0][0]
        assert "No type hints" not in saved_config.ignore_patterns
        assert "TODO" in saved_config.ignore_patterns

    def test_unignore_not_found(self, tmp_path):
        config_file = tmp_path / CONFIG_FILENAME
        existing = CritiqConfig(ignore_patterns=["TODO"])
        with patch("critiq.learn.find_config_path", return_value=config_file), \
             patch("critiq.learn.load_config", return_value=existing):
            result = _run(["unignore", "No type hints"])
        assert result.exit_code == 0
        assert "not found" in result.output

    def test_unignore_no_config(self):
        with patch("critiq.learn.find_config_path", return_value=None):
            result = _run(["unignore", "No type hints"])
        assert result.exit_code == 0
        assert "No config file" in result.output


class TestLearnReset:
    def test_reset_with_yes(self, tmp_path):
        config_file = tmp_path / CONFIG_FILENAME
        config_file.write_text("default_focus: security\n")
        with patch("critiq.learn.find_config_path", return_value=config_file):
            result = _run(["reset", "--yes"])
        assert result.exit_code == 0
        assert not config_file.exists()

    def test_reset_no_config(self):
        with patch("critiq.learn.find_config_path", return_value=None):
            result = _run(["reset"])
        assert result.exit_code == 0
        assert "No config file" in result.output


class TestLearnHelp:
    def test_help(self):
        result = _run(["--help"])
        assert result.exit_code == 0
        assert "ignore" in result.output
        assert "rule" in result.output
        assert "show" in result.output

    def test_ignore_help(self):
        result = _run(["ignore", "--help"])
        assert result.exit_code == 0


class TestCLIWithConfig:
    """Test that critiq CLI loads project config and applies defaults."""

    def test_config_loaded_shown_in_output(self, tmp_path):
        """When .critiq.yaml exists, CLI shows 'Project config loaded'."""
        from unittest.mock import MagicMock
        from critiq.config import CritiqConfig

        non_empty_config = CritiqConfig(default_focus="security")

        with patch("critiq.cli.is_git_repo", return_value=True), \
             patch("critiq.cli.load_config", return_value=non_empty_config), \
             patch("critiq.cli.get_staged_diff") as mock_diff, \
             patch("critiq.cli.get_provider") as mock_prov, \
             patch("critiq.cli.review_diff") as mock_review:
            mock_diff.return_value = MagicMock(
                is_empty=False, files_changed=["a.py"], insertions=1, deletions=0
            )
            mock_review.return_value = MagicMock(
                comments=[], summary="LGTM", overall_rating="✅ LGTM",
                provider_model="claude/default"
            )
            from critiq.cli import main as critiq_main
            from click.testing import CliRunner
            runner = CliRunner()
            result = runner.invoke(critiq_main, [], catch_exceptions=False)
        assert "Project config loaded" in result.output
