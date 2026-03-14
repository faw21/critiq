"""Project-level configuration for critiq (.critiq.yaml)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml

    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

CONFIG_FILENAME = ".critiq.yaml"


@dataclass
class CritiqConfig:
    """Project-level preferences for critiq."""

    ignore_patterns: list[str] = field(default_factory=list)
    """Patterns to ignore in reviews (e.g. 'Missing type annotations')."""

    custom_rules: list[str] = field(default_factory=list)
    """Extra rules to always check (e.g. 'Check for SQL injection')."""

    default_focus: str = "all"
    """Default focus area (all/security/performance/readability/correctness/style)."""

    default_provider: str = "claude"
    """Default LLM provider."""

    default_model: str | None = None
    """Default model name."""

    def is_empty(self) -> bool:
        return (
            not self.ignore_patterns
            and not self.custom_rules
            and self.default_focus == "all"
            and self.default_provider == "claude"
            and self.default_model is None
        )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        if self.ignore_patterns:
            d["ignore_patterns"] = self.ignore_patterns
        if self.custom_rules:
            d["custom_rules"] = self.custom_rules
        if self.default_focus != "all":
            d["default_focus"] = self.default_focus
        if self.default_provider != "claude":
            d["default_provider"] = self.default_provider
        if self.default_model is not None:
            d["default_model"] = self.default_model
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CritiqConfig":
        return cls(
            ignore_patterns=d.get("ignore_patterns", []),
            custom_rules=d.get("custom_rules", []),
            default_focus=d.get("default_focus", "all"),
            default_provider=d.get("default_provider", "claude"),
            default_model=d.get("default_model"),
        )


def find_config_path(start: Path | None = None) -> Path | None:
    """Walk up directory tree to find .critiq.yaml."""
    current = (start or Path.cwd()).resolve()
    while True:
        candidate = current / CONFIG_FILENAME
        if candidate.exists():
            return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def load_config(path: Path | None = None) -> CritiqConfig:
    """Load config from .critiq.yaml. Returns empty config if not found."""
    if not _HAS_YAML:
        return CritiqConfig()

    config_path = path or find_config_path()
    if config_path is None or not config_path.exists():
        return CritiqConfig()

    try:
        raw = yaml.safe_load(config_path.read_text())
        if not isinstance(raw, dict):
            return CritiqConfig()
        return CritiqConfig.from_dict(raw)
    except Exception:
        return CritiqConfig()


def save_config(config: CritiqConfig, path: Path | None = None) -> Path:
    """Save config to .critiq.yaml. Returns the path written."""
    if not _HAS_YAML:
        raise RuntimeError(
            "pyyaml is required to save config. Install with: pip install pyyaml"
        )

    config_path = path or (Path.cwd() / CONFIG_FILENAME)
    config_path.write_text(
        yaml.dump(config.to_dict(), default_flow_style=False, allow_unicode=True)
    )
    return config_path
