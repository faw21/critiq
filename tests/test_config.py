"""Tests for critiq.config module."""

from __future__ import annotations

import pytest

from critiq.config import (
    CONFIG_FILENAME,
    CritiqConfig,
    find_config_path,
    load_config,
    save_config,
)


class TestCritiqConfig:
    def test_default_values(self):
        cfg = CritiqConfig()
        assert cfg.ignore_patterns == []
        assert cfg.custom_rules == []
        assert cfg.default_focus == "all"
        assert cfg.default_provider == "claude"
        assert cfg.default_model is None

    def test_is_empty_defaults(self):
        assert CritiqConfig().is_empty()

    def test_is_empty_with_ignore(self):
        cfg = CritiqConfig(ignore_patterns=["No type hints"])
        assert not cfg.is_empty()

    def test_is_empty_with_rule(self):
        cfg = CritiqConfig(custom_rules=["Always check SQL injection"])
        assert not cfg.is_empty()

    def test_is_empty_with_focus(self):
        cfg = CritiqConfig(default_focus="security")
        assert not cfg.is_empty()

    def test_to_dict_empty(self):
        assert CritiqConfig().to_dict() == {}

    def test_to_dict_with_values(self):
        cfg = CritiqConfig(
            ignore_patterns=["No type hints"],
            custom_rules=["Check SQL"],
            default_focus="security",
        )
        d = cfg.to_dict()
        assert d["ignore_patterns"] == ["No type hints"]
        assert d["custom_rules"] == ["Check SQL"]
        assert d["default_focus"] == "security"
        assert "default_provider" not in d  # omitted when default

    def test_from_dict_full(self):
        d = {
            "ignore_patterns": ["No type hints"],
            "custom_rules": ["Check SQL"],
            "default_focus": "security",
            "default_provider": "openai",
            "default_model": "gpt-4",
        }
        cfg = CritiqConfig.from_dict(d)
        assert cfg.ignore_patterns == ["No type hints"]
        assert cfg.custom_rules == ["Check SQL"]
        assert cfg.default_focus == "security"
        assert cfg.default_provider == "openai"
        assert cfg.default_model == "gpt-4"

    def test_from_dict_partial(self):
        cfg = CritiqConfig.from_dict({"default_focus": "performance"})
        assert cfg.default_focus == "performance"
        assert cfg.ignore_patterns == []

    def test_from_dict_empty(self):
        cfg = CritiqConfig.from_dict({})
        assert cfg.is_empty()

    def test_immutability(self):
        """Ensure original is not modified when creating new config."""
        original = CritiqConfig(ignore_patterns=["A"])
        new_patterns = [*original.ignore_patterns, "B"]
        new_cfg = CritiqConfig(
            ignore_patterns=new_patterns,
            custom_rules=original.custom_rules,
            default_focus=original.default_focus,
            default_provider=original.default_provider,
            default_model=original.default_model,
        )
        assert original.ignore_patterns == ["A"]
        assert new_cfg.ignore_patterns == ["A", "B"]


class TestFindConfigPath:
    def test_finds_config_in_cwd(self, tmp_path):
        config_file = tmp_path / CONFIG_FILENAME
        config_file.write_text("default_focus: security\n")
        found = find_config_path(tmp_path)
        assert found == config_file

    def test_finds_config_in_parent(self, tmp_path):
        config_file = tmp_path / CONFIG_FILENAME
        config_file.write_text("default_focus: security\n")
        subdir = tmp_path / "src" / "module"
        subdir.mkdir(parents=True)
        found = find_config_path(subdir)
        assert found == config_file

    def test_returns_none_when_not_found(self, tmp_path):
        found = find_config_path(tmp_path)
        assert found is None


class TestLoadConfig:
    def test_returns_empty_when_no_file(self, tmp_path):
        config = load_config()
        # If no .critiq.yaml in current or any parent, returns empty
        assert isinstance(config, CritiqConfig)

    def test_loads_from_explicit_path(self, tmp_path):
        config_file = tmp_path / CONFIG_FILENAME
        config_file.write_text(
            "ignore_patterns:\n  - No type hints\ndefault_focus: security\n"
        )
        config = load_config(config_file)
        assert config.ignore_patterns == ["No type hints"]
        assert config.default_focus == "security"

    def test_returns_empty_on_invalid_yaml(self, tmp_path):
        config_file = tmp_path / CONFIG_FILENAME
        config_file.write_text("not: valid: yaml: [[[")
        config = load_config(config_file)
        assert config.is_empty()

    def test_returns_empty_on_non_dict_yaml(self, tmp_path):
        config_file = tmp_path / CONFIG_FILENAME
        config_file.write_text("- just a list\n")
        config = load_config(config_file)
        assert config.is_empty()


class TestSaveConfig:
    def test_saves_and_loads_roundtrip(self, tmp_path):
        config = CritiqConfig(
            ignore_patterns=["No type hints", "TODO comments"],
            custom_rules=["Always check SQL injection"],
            default_focus="security",
        )
        path = tmp_path / CONFIG_FILENAME
        saved = save_config(config, path)
        assert saved == path
        assert path.exists()

        loaded = load_config(path)
        assert loaded.ignore_patterns == ["No type hints", "TODO comments"]
        assert loaded.custom_rules == ["Always check SQL injection"]
        assert loaded.default_focus == "security"

    def test_saves_empty_config(self, tmp_path):
        config = CritiqConfig()
        path = tmp_path / CONFIG_FILENAME
        save_config(config, path)
        assert path.exists()
        loaded = load_config(path)
        assert loaded.is_empty()
