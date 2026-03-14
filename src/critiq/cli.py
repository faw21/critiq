"""CLI entry point for critiq."""

from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console

from . import __version__
from .config import CritiqConfig, load_config
from .fixer import interactive_fix
from .formatter import print_review, print_review_compact
from .git_utils import (
    get_branch_diff,
    get_file_diff,
    get_staged_diff,
    is_git_repo,
)
from .providers import get_provider
from .reviewer import Severity, review_diff

console = Console()


def _abort(message: str) -> None:
    console.print(f"[bold red]Error:[/bold red] {message}")
    sys.exit(1)


def _do_review(
    *,
    base_branch: str | None,
    file_path: str | None,
    focus: str,
    severity: str | None,
    compact: bool,
    fix: bool,
    fix_all: bool,
    fix_severity: str | None,
    provider: str,
    model: str | None,
    context_text: str | None,
    raw: bool,
    project_config: CritiqConfig | None = None,
    fatal_on_error: bool = True,
) -> None:
    """Run a single review cycle (extracted for --watch reuse).

    Args:
        fatal_on_error: If True, call sys.exit(1) on fatal errors.
                        If False, just print and return (for --watch mode).
    """
    def _fail(msg: str) -> None:
        console.print(f"[bold red]Error:[/bold red] {msg}")
        if fatal_on_error:
            sys.exit(1)

    # Determine what to diff
    try:
        if file_path:
            diff = get_file_diff(file_path, base=base_branch)
        elif base_branch:
            diff = get_branch_diff(base=base_branch)
        else:
            diff = get_staged_diff()
    except RuntimeError as e:
        _fail(str(e))
        return

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
        if fatal_on_error:
            sys.exit(0)
        return

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
        _fail(str(e))
        return

    model_label = f"{provider}/{model or 'default'}"

    if raw:
        from .reviewer import _build_language_hints, _build_system_prompt, _build_user_prompt

        language_hints = _build_language_hints(diff.files_changed)
        system = _build_system_prompt(focus, config=project_config, language_hints=language_hints)
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
            config=project_config,
        )
    except Exception as e:
        _fail(f"Review failed: {e}")
        return

    # Filter by severity if requested (immutable: create new ReviewResult)
    if severity:
        from dataclasses import replace as dc_replace

        severity_order = ["critical", "warning", "info", "suggestion"]
        threshold = severity_order.index(severity.lower())
        result = dc_replace(
            result,
            comments=[
                c
                for c in result.comments
                if severity_order.index(c.severity.value) <= threshold
            ],
        )

    # Output
    if compact:
        print_review_compact(result, console=console)
    else:
        print_review(result, console=console)

    # --fix mode: interactively fix issues
    if fix and result.comments:
        severity_filter: set[Severity] | None = None
        if fix_severity:
            severity_order_list = ["critical", "warning", "info", "suggestion"]
            threshold = severity_order_list.index(fix_severity.lower())
            severity_filter = {
                Severity(s) for s in severity_order_list[: threshold + 1]
            }

        try:
            interactive_fix(
                result=result,
                provider=llm,
                console=console,
                fix_all=fix_all,
                severity_filter=severity_filter,
            )
        except KeyboardInterrupt:
            console.print("\n[dim]Fix interrupted.[/dim]")

    # Exit code: non-zero if critical issues found
    has_critical = any(c.severity.value == "critical" for c in result.comments)
    if has_critical:
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
    "--fix",
    is_flag=True,
    default=False,
    help="Interactively fix CRITICAL and WARNING issues after review",
)
@click.option(
    "--fix-all",
    is_flag=True,
    default=False,
    help="Automatically apply all fixes without prompting",
)
@click.option(
    "--fix-severity",
    type=click.Choice(["critical", "warning", "info", "suggestion"], case_sensitive=False),
    default=None,
    help="Minimum severity to fix (default: warning when --fix is used)",
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
    "--watch",
    is_flag=True,
    default=False,
    help="Watch for file changes and re-run review automatically (requires: pip install 'critiq[watch]')",
)
@click.option(
    "--debounce",
    type=float,
    default=2.0,
    show_default=True,
    metavar="SECS",
    help="Seconds to wait after a change before re-running (--watch mode)",
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
    fix: bool,
    fix_all: bool,
    fix_severity: str | None,
    provider: str,
    model: str | None,
    context_text: str | None,
    watch: bool,
    debounce: float,
    raw: bool,
) -> None:
    """AI-powered local code reviewer — catch issues before you push.

    By default, reviews your staged changes. Use --diff BRANCH to review
    all changes vs a branch, or --file PATH to review a specific file.

    Use --fix to interactively fix CRITICAL and WARNING issues after review.
    Use --fix-all to apply all fixes automatically (no prompts).
    Use --watch to continuously watch for changes and auto-review.

    Examples:

      critiq                          # review staged changes
      critiq --fix                    # review then interactively fix issues
      critiq --fix-all                # review and auto-apply all fixes
      critiq --watch                  # watch for changes, auto-review
      critiq --diff main              # review vs main branch
      critiq --diff main --fix        # review vs main, then fix
      critiq --file src/auth.py       # review specific file
      critiq --focus security         # focus on security issues
      critiq --provider ollama        # use local Ollama (no API key)

    Teach critiq your project's preferences:

      critiq-learn ignore "Missing type annotations"
      critiq-learn rule "Always check for SQL injection"
      critiq-learn show
    """
    if not is_git_repo():
        _abort("Not inside a git repository.")

    # Load project config (.critiq.yaml, auto-detected)
    project_config = load_config()
    if not project_config.is_empty():
        console.print("[dim]📋 Project config loaded (.critiq.yaml)[/dim]")

    # Apply config defaults (CLI flags override config)
    if focus == "all" and project_config.default_focus != "all":
        focus = project_config.default_focus
    if provider == "claude" and project_config.default_provider != "claude":
        provider = project_config.default_provider
    if model is None and project_config.default_model is not None:
        model = project_config.default_model

    # --fix-all implies --fix
    if fix_all:
        fix = True

    # --watch mode: delegate to watcher
    if watch:
        from .watcher import watch_and_review

        def _run_review() -> None:
            _do_review(
                base_branch=base_branch,
                file_path=file_path,
                focus=focus,
                severity=severity,
                compact=compact,
                fix=False,  # don't fix in watch mode (interactive is confusing)
                fix_all=False,
                fix_severity=fix_severity,
                provider=provider,
                model=model,
                context_text=context_text,
                raw=raw,
                project_config=project_config,
                fatal_on_error=False,
            )

        try:
            watch_and_review(
                run_review=_run_review,
                console=console,
                debounce=debounce,
            )
        except KeyboardInterrupt:
            console.print("\n[dim]Watch mode stopped.[/dim]")
        return

    # Single-run review
    _do_review(
        base_branch=base_branch,
        file_path=file_path,
        focus=focus,
        severity=severity,
        compact=compact,
        fix=fix,
        fix_all=fix_all,
        fix_severity=fix_severity,
        provider=provider,
        model=model,
        context_text=context_text,
        raw=raw,
        project_config=project_config,
    )
