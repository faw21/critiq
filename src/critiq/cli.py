"""CLI entry point for critiq."""

from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console

from . import __version__
from .formatter import print_review, print_review_compact
from .git_utils import (
    get_branch_diff,
    get_file_diff,
    get_staged_diff,
    is_git_repo,
)
from .providers import get_provider
from .reviewer import review_diff

console = Console()


def _abort(message: str) -> None:
    console.print(f"[bold red]Error:[/bold red] {message}")
    sys.exit(1)


@click.command()
@click.version_option(__version__, prog_name="critiq")
@click.option(
    "--staged",
    "mode",
    flag_value="staged",
    default=True,
    help="Review staged changes (default)",
)
@click.option(
    "--diff",
    "base_branch",
    metavar="BRANCH",
    default=None,
    help="Review all changes vs BRANCH (e.g. --diff main)",
)
@click.option(
    "--file",
    "file_path",
    metavar="FILE",
    default=None,
    help="Review a specific file's changes",
)
@click.option(
    "--focus",
    type=click.Choice(
        ["all", "security", "performance", "readability", "correctness", "style"],
        case_sensitive=False,
    ),
    default="all",
    show_default=True,
    help="Focus area for the review",
)
@click.option(
    "--severity",
    type=click.Choice(["critical", "warning", "info", "suggestion"], case_sensitive=False),
    default=None,
    help="Only show findings at or above this severity",
)
@click.option(
    "--compact",
    is_flag=True,
    default=False,
    help="Compact output (no panels)",
)
@click.option(
    "--provider",
    type=click.Choice(["claude", "openai", "ollama"], case_sensitive=False),
    default="claude",
    show_default=True,
    envvar="CRITIQ_PROVIDER",
    help="LLM provider",
)
@click.option(
    "--model",
    default=None,
    envvar="CRITIQ_MODEL",
    help="Model name (uses provider default if not set)",
)
@click.option(
    "--context",
    "context_text",
    metavar="TEXT",
    default=None,
    help="Additional context to give the AI reviewer (e.g. 'This is a security-critical module')",
)
@click.option(
    "--raw",
    is_flag=True,
    default=False,
    help="Print raw AI output (for debugging)",
)
def main(
    mode: str,
    base_branch: str | None,
    file_path: str | None,
    focus: str,
    severity: str | None,
    compact: bool,
    provider: str,
    model: str | None,
    context_text: str | None,
    raw: bool,
) -> None:
    """AI-powered local code reviewer — catch issues before you push.

    By default, reviews your staged changes. Use --diff BRANCH to review
    all changes vs a branch, or --file PATH to review a specific file.

    Examples:

      critiq                          # review staged changes
      critiq --diff main              # review vs main branch
      critiq --file src/auth.py       # review specific file
      critiq --focus security         # focus on security issues
      critiq --provider ollama        # use local Ollama (no API key)
    """
    if not is_git_repo():
        _abort("Not inside a git repository.")

    # Determine what to diff
    try:
        if file_path:
            diff = get_file_diff(file_path, base=base_branch)
        elif base_branch:
            diff = get_branch_diff(base=base_branch)
        else:
            diff = get_staged_diff()
    except RuntimeError as e:
        _abort(str(e))
        return  # unreachable, satisfies type checker

    if diff.is_empty:
        if base_branch:
            console.print(f"[yellow]No changes found vs '{base_branch}'.[/yellow]")
        elif file_path:
            console.print(f"[yellow]No changes found in '{file_path}'.[/yellow]")
        else:
            console.print(
                "[yellow]No staged changes. Use 'git add' to stage files, "
                "or use --diff BRANCH to review all changes.[/yellow]"
            )
        sys.exit(0)

    # Show what we're reviewing
    mode_desc = (
        f"file [cyan]{file_path}[/cyan]"
        if file_path
        else f"changes vs [cyan]{base_branch}[/cyan]"
        if base_branch
        else "staged changes"
    )
    files_summary = ", ".join(diff.files_changed[:3])
    if len(diff.files_changed) > 3:
        files_summary += f" (+{len(diff.files_changed) - 3} more)"

    console.print(
        f"[dim]Reviewing {mode_desc} · "
        f"+{diff.insertions}/-{diff.deletions} lines · "
        f"{files_summary}[/dim]"
    )
    console.print(f"[dim]Provider: {provider} · Focus: {focus}[/dim]")
    console.print("[dim]Thinking...[/dim]")

    # Get provider
    try:
        llm = get_provider(provider, model=model)
    except ValueError as e:
        _abort(str(e))
        return

    model_label = f"{provider}/{model or 'default'}"

    if raw:
        # Debug: print raw output
        from .reviewer import _build_system_prompt, _build_user_prompt

        system = _build_system_prompt(focus)
        user = _build_user_prompt(diff, context_text)
        raw_output = llm.complete(system, user)
        console.print(raw_output)
        return

    # Run review
    try:
        result = review_diff(
            diff=diff,
            provider=llm,
            focus=focus,
            context=context_text,
            model_label=model_label,
        )
    except Exception as e:
        _abort(f"Review failed: {e}")
        return

    # Filter by severity if requested (immutable: create new ReviewResult)
    if severity:
        from dataclasses import replace as dc_replace
        severity_order = ["critical", "warning", "info", "suggestion"]
        threshold = severity_order.index(severity.lower())
        result = dc_replace(
            result,
            comments=[
                c for c in result.comments
                if severity_order.index(c.severity.value) <= threshold
            ],
        )

    # Output
    if compact:
        print_review_compact(result, console=console)
    else:
        print_review(result, console=console)

    # Exit code: non-zero if critical issues found
    has_critical = any(c.severity.value == "critical" for c in result.comments)
    if has_critical:
        sys.exit(1)
