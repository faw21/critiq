"""critiq-learn — teach critiq your project's preferences."""

from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import (
    CONFIG_FILENAME,
    CritiqConfig,
    find_config_path,
    load_config,
    save_config,
)

console = Console()

VALID_FOCUS = ["all", "security", "performance", "readability", "correctness", "style"]
VALID_PROVIDERS = ["claude", "openai", "ollama"]


def _abort(msg: str) -> None:
    console.print(f"[bold red]Error:[/bold red] {msg}")
    sys.exit(1)


def _check_yaml() -> None:
    try:
        import yaml  # noqa: F401
    except ImportError:
        _abort("pyyaml is required. Install with: pip install pyyaml")


@click.group()
@click.version_option(prog_name="critiq-learn")
def main() -> None:
    """Teach critiq your project's code review preferences.

    Preferences are saved in .critiq.yaml in your project root.
    critiq automatically loads this file when reviewing your code.

    Examples:

      critiq-learn ignore "Missing type annotations"
      critiq-learn ignore "No docstrings on private methods"
      critiq-learn rule "Always check for SQL injection in ORM calls"
      critiq-learn set focus security
      critiq-learn show
      critiq-learn reset
    """


@main.command("show")
def show_cmd() -> None:
    """Show current project preferences."""
    config_path = find_config_path()
    config = load_config(config_path)

    if config_path:
        console.print(f"[dim]Config: {config_path}[/dim]\n")
    else:
        console.print(
            f"[dim]No {CONFIG_FILENAME} found — using defaults. "
            f"Run commands below to create one.[/dim]\n"
        )

    # Build table
    table = Table(show_header=True, header_style="bold", expand=False)
    table.add_column("Setting", style="cyan", min_width=20)
    table.add_column("Value")

    table.add_row("Default focus", config.default_focus)
    table.add_row("Default provider", config.default_provider)
    table.add_row(
        "Default model", config.default_model or "[dim]provider default[/dim]"
    )

    if config.ignore_patterns:
        for i, p in enumerate(config.ignore_patterns):
            label = "Ignore patterns" if i == 0 else ""
            table.add_row(label, f"[yellow]{p}[/yellow]")
    else:
        table.add_row("Ignore patterns", "[dim]none[/dim]")

    if config.custom_rules:
        for i, r in enumerate(config.custom_rules):
            label = "Custom rules" if i == 0 else ""
            table.add_row(label, f"[green]{r}[/green]")
    else:
        table.add_row("Custom rules", "[dim]none[/dim]")

    console.print(Panel(table, title="critiq project config", border_style="blue"))


@main.command("ignore")
@click.argument("pattern")
def ignore_cmd(pattern: str) -> None:
    """Add a pattern to ignore during reviews.

    PATTERN is a short description of what to ignore.

    Examples:

      critiq-learn ignore "Missing type annotations"
      critiq-learn ignore "No docstrings on private methods"
      critiq-learn ignore "TODO comments"
    """
    _check_yaml()
    config_path = find_config_path() or (Path.cwd() / CONFIG_FILENAME)
    config = load_config(config_path if config_path.exists() else None)

    if pattern in config.ignore_patterns:
        console.print(f"[yellow]Already ignoring:[/yellow] {pattern}")
        return

    new_config = CritiqConfig(
        ignore_patterns=[*config.ignore_patterns, pattern],
        custom_rules=config.custom_rules,
        default_focus=config.default_focus,
        default_provider=config.default_provider,
        default_model=config.default_model,
    )
    saved_path = save_config(new_config, Path.cwd() / CONFIG_FILENAME)
    console.print(
        f"[green]✓[/green] Added ignore pattern: [yellow]{pattern}[/yellow]\n"
        f"[dim]Saved to {saved_path}[/dim]"
    )


@main.command("rule")
@click.argument("rule_text")
def rule_cmd(rule_text: str) -> None:
    """Add a custom rule that critiq always checks.

    RULE_TEXT is a short description of the rule.

    Examples:

      critiq-learn rule "Always check for SQL injection in ORM calls"
      critiq-learn rule "Ensure all API endpoints have rate limiting"
      critiq-learn rule "No hardcoded secrets or API keys"
    """
    _check_yaml()
    config_path = find_config_path() or (Path.cwd() / CONFIG_FILENAME)
    config = load_config(config_path if config_path.exists() else None)

    if rule_text in config.custom_rules:
        console.print(f"[yellow]Rule already exists:[/yellow] {rule_text}")
        return

    new_config = CritiqConfig(
        ignore_patterns=config.ignore_patterns,
        custom_rules=[*config.custom_rules, rule_text],
        default_focus=config.default_focus,
        default_provider=config.default_provider,
        default_model=config.default_model,
    )
    saved_path = save_config(new_config, Path.cwd() / CONFIG_FILENAME)
    console.print(
        f"[green]✓[/green] Added custom rule: [green]{rule_text}[/green]\n"
        f"[dim]Saved to {saved_path}[/dim]"
    )


@main.group("set")
def set_group() -> None:
    """Set default values for critiq options."""


@set_group.command("focus")
@click.argument(
    "focus",
    type=click.Choice(VALID_FOCUS, case_sensitive=False),
)
def set_focus(focus: str) -> None:
    """Set the default focus area for reviews."""
    _check_yaml()
    config_path = find_config_path() or (Path.cwd() / CONFIG_FILENAME)
    config = load_config(config_path if config_path.exists() else None)

    new_config = CritiqConfig(
        ignore_patterns=config.ignore_patterns,
        custom_rules=config.custom_rules,
        default_focus=focus,
        default_provider=config.default_provider,
        default_model=config.default_model,
    )
    saved_path = save_config(new_config, Path.cwd() / CONFIG_FILENAME)
    console.print(
        f"[green]✓[/green] Default focus set to: [cyan]{focus}[/cyan]\n"
        f"[dim]Saved to {saved_path}[/dim]"
    )


@set_group.command("provider")
@click.argument(
    "provider",
    type=click.Choice(VALID_PROVIDERS, case_sensitive=False),
)
def set_provider(provider: str) -> None:
    """Set the default LLM provider."""
    _check_yaml()
    config_path = find_config_path() or (Path.cwd() / CONFIG_FILENAME)
    config = load_config(config_path if config_path.exists() else None)

    new_config = CritiqConfig(
        ignore_patterns=config.ignore_patterns,
        custom_rules=config.custom_rules,
        default_focus=config.default_focus,
        default_provider=provider,
        default_model=config.default_model,
    )
    saved_path = save_config(new_config, Path.cwd() / CONFIG_FILENAME)
    console.print(
        f"[green]✓[/green] Default provider set to: [cyan]{provider}[/cyan]\n"
        f"[dim]Saved to {saved_path}[/dim]"
    )


@main.command("unignore")
@click.argument("pattern")
def unignore_cmd(pattern: str) -> None:
    """Remove an ignore pattern."""
    _check_yaml()
    config_path = find_config_path()
    if config_path is None:
        console.print("[yellow]No config file found.[/yellow]")
        return

    config = load_config(config_path)
    if pattern not in config.ignore_patterns:
        console.print(f"[yellow]Pattern not found:[/yellow] {pattern}")
        return

    new_config = CritiqConfig(
        ignore_patterns=[p for p in config.ignore_patterns if p != pattern],
        custom_rules=config.custom_rules,
        default_focus=config.default_focus,
        default_provider=config.default_provider,
        default_model=config.default_model,
    )
    save_config(new_config, config_path)
    console.print(f"[green]✓[/green] Removed ignore pattern: [yellow]{pattern}[/yellow]")


@main.command("reset")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt")
def reset_cmd(yes: bool) -> None:
    """Reset all project preferences."""
    config_path = find_config_path()
    if config_path is None:
        console.print("[dim]No config file found — nothing to reset.[/dim]")
        return

    if not yes:
        click.confirm(
            f"Reset all preferences in {config_path}?", abort=True
        )

    config_path.unlink()
    console.print(f"[green]✓[/green] Deleted {config_path}")
