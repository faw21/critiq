"""AI-powered fix generation for critiq findings."""

from __future__ import annotations

import difflib
import shutil
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.rule import Rule
from rich.syntax import Syntax
from rich.text import Text

from .providers import LLMProvider
from .reviewer import ReviewComment, ReviewResult, Severity


_SEVERITY_ORDER = [Severity.CRITICAL, Severity.WARNING, Severity.INFO, Severity.SUGGESTION]
_FIXABLE_SEVERITIES = {Severity.CRITICAL, Severity.WARNING}


@dataclass
class FixResult:
    """Result of applying a fix to a file."""

    file_path: str
    issues_fixed: int
    applied: bool
    backup_path: str = ""


def _severity_label(s: Severity) -> str:
    labels = {
        Severity.CRITICAL: "[bold red]🚨 CRITICAL[/bold red]",
        Severity.WARNING: "[bold yellow]⚠️  WARNING[/bold yellow]",
        Severity.INFO: "[bold blue]ℹ️  INFO[/bold blue]",
        Severity.SUGGESTION: "[dim cyan]💡 SUGGESTION[/dim cyan]",
    }
    return labels[s]


def _build_fix_system_prompt() -> str:
    return (
        "You are an expert software engineer tasked with fixing code issues. "
        "You will receive a file's current content and a list of specific issues found by a code reviewer. "
        "Your job is to fix ALL the listed issues in the file.\n\n"
        "Rules:\n"
        "1. Output ONLY the complete fixed file content — no explanations, no markdown fences\n"
        "2. Fix all listed issues while preserving the overall structure and logic\n"
        "3. Keep changes minimal — only modify what's needed to fix the issues\n"
        "4. Do not add features or refactor beyond what's needed to fix the issues\n"
        "5. Preserve indentation, whitespace style, and comments\n"
        "6. If an issue is in a specific function, only modify that function unless a broader fix is required"
    )


def _build_fix_user_prompt(file_path: str, file_content: str, issues: list[ReviewComment]) -> str:
    issue_list = []
    for i, issue in enumerate(issues, 1):
        parts = [f"{i}. [{issue.severity.value.upper()}] {issue.title}"]
        if issue.line:
            parts.append(f"   Location: {issue.line}")
        if issue.body:
            for line in issue.body.strip().splitlines()[:4]:
                parts.append(f"   {line}")
        issue_list.append("\n".join(parts))

    issues_text = "\n\n".join(issue_list)

    return (
        f"File: {file_path}\n\n"
        f"Issues to fix:\n{issues_text}\n\n"
        f"Current file content:\n"
        f"```\n{file_content}\n```\n\n"
        "Output the complete fixed file content (no markdown, no explanations):"
    )


def _show_diff(original: str, fixed: str, filename: str, console: Console) -> int:
    """Show a colorized unified diff. Returns number of changed lines."""
    original_lines = original.splitlines(keepends=True)
    fixed_lines = fixed.splitlines(keepends=True)

    diff_lines = list(difflib.unified_diff(
        original_lines,
        fixed_lines,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
        lineterm="",
    ))

    if not diff_lines:
        console.print("[yellow]  No changes generated.[/yellow]")
        return 0

    # Build colored diff text
    diff_text = Text()
    changed_count = 0
    for line in diff_lines:
        if line.startswith("---") or line.startswith("+++"):
            diff_text.append(line + "\n", style="bold dim")
        elif line.startswith("@@"):
            diff_text.append(line + "\n", style="cyan dim")
        elif line.startswith("+"):
            diff_text.append(line + "\n", style="bold green")
            changed_count += 1
        elif line.startswith("-"):
            diff_text.append(line + "\n", style="bold red")
            changed_count += 1
        else:
            diff_text.append(line + "\n", style="dim")

    console.print(Panel(
        diff_text,
        title=f"[bold]Changes to {filename}[/bold]",
        border_style="blue",
        padding=(0, 1),
    ))
    return changed_count


def _backup_file(file_path: Path) -> str:
    """Create a .bak copy of the file before modifying it."""
    backup = file_path.with_suffix(file_path.suffix + ".critiq.bak")
    shutil.copy2(file_path, backup)
    return str(backup)


def _group_issues_by_file(issues: list[ReviewComment]) -> dict[str, list[ReviewComment]]:
    """Group review comments by their file path."""
    grouped: dict[str, list[ReviewComment]] = {}
    for issue in issues:
        if issue.file:
            grouped.setdefault(issue.file, []).append(issue)
    return grouped


def _read_file(file_path: str) -> str | None:
    """Read file content, return None if not readable."""
    try:
        return Path(file_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def generate_fix(
    file_path: str,
    file_content: str,
    issues: list[ReviewComment],
    provider: LLMProvider,
) -> str:
    """Ask the LLM to generate a fixed version of the file."""
    system = _build_fix_system_prompt()
    user = _build_fix_user_prompt(file_path, file_content, issues)
    fixed = provider.complete(system, user)

    # Strip only markdown fences — preserve trailing newlines to avoid false diffs
    import re
    # Remove opening fence: ```python\n or ``` at the very start
    fixed = re.sub(r"^```[a-z]*\n", "", fixed.lstrip("\n"))
    # Remove closing fence: ``` at the very end
    fixed = re.sub(r"\n?```\s*$", "", fixed)

    # Preserve the original file's trailing newline convention
    if file_content.endswith("\n") and not fixed.endswith("\n"):
        fixed += "\n"

    return fixed


def interactive_fix(
    result: ReviewResult,
    provider: LLMProvider,
    console: Console,
    fix_all: bool = False,
    severity_filter: set[Severity] | None = None,
) -> list[FixResult]:
    """
    Interactively fix issues from a ReviewResult.

    Args:
        result: The review result containing issues to fix.
        provider: LLM provider to use for generating fixes.
        console: Rich console for output.
        fix_all: If True, apply all fixes without prompting.
        severity_filter: Only fix issues at these severities (default: CRITICAL + WARNING).

    Returns:
        List of FixResult objects for each file processed.
    """
    filter_set = severity_filter or _FIXABLE_SEVERITIES
    fixable = [c for c in result.comments if c.severity in filter_set and c.file]

    if not fixable:
        console.print("[dim]No fixable issues found.[/dim]")
        return []

    console.print()
    console.print(Rule("[bold]critiq --fix[/bold]", style="dim"))
    console.print(
        f"[dim]{len(fixable)} issue(s) eligible for auto-fix "
        f"in {len({c.file for c in fixable})} file(s)[/dim]"
    )
    console.print()

    fix_results: list[FixResult] = []
    grouped = _group_issues_by_file(fixable)

    for file_path, issues in grouped.items():
        # Show issues for this file
        console.print(f"[bold cyan]📄 {file_path}[/bold cyan]  "
                      f"[dim]({len(issues)} issue(s))[/dim]")

        for issue in issues:
            icon_label = _severity_label(issue.severity)
            loc = f"  [dim]{issue.line}[/dim]" if issue.line else ""
            console.print(f"  {icon_label}{loc}  {issue.title}")

        console.print()

        # Check if file exists
        file_content = _read_file(file_path)
        if file_content is None:
            console.print(f"  [yellow]⚠ Cannot read {file_path}, skipping.[/yellow]")
            console.print()
            fix_results.append(FixResult(file_path=file_path, issues_fixed=0, applied=False))
            continue

        # Ask what to fix (unless --fix-all)
        if fix_all:
            selected_issues = issues
        else:
            choice = Prompt.ask(
                f"  Fix [bold]{len(issues)}[/bold] issue(s) in this file?",
                choices=["a", "s", "n"],
                default="a",
                show_choices=False,
                console=console,
            )
            # Show choices inline
            console.print(
                "  [dim]([bold]a[/bold]=fix all  "
                "[bold]s[/bold]=select individually  "
                "[bold]n[/bold]=skip)[/dim]",
                end="",
            )
            console.print()

            if choice == "n":
                console.print("  [dim]Skipped.[/dim]")
                console.print()
                fix_results.append(FixResult(file_path=file_path, issues_fixed=0, applied=False))
                continue
            elif choice == "s":
                selected_issues = _select_issues_interactively(issues, console)
                if not selected_issues:
                    console.print("  [dim]No issues selected, skipping.[/dim]")
                    console.print()
                    fix_results.append(FixResult(file_path=file_path, issues_fixed=0, applied=False))
                    continue
            else:
                selected_issues = issues

        # Generate fix
        console.print(f"  [dim]Generating fix for {len(selected_issues)} issue(s)...[/dim]", end="")
        try:
            fixed_content = generate_fix(file_path, file_content, selected_issues, provider)
            console.print(" [green]✓[/green]")
        except Exception as e:
            console.print(f" [red]failed[/red]")
            console.print(f"  [red]Error: {e}[/red]")
            console.print()
            fix_results.append(FixResult(file_path=file_path, issues_fixed=0, applied=False))
            continue

        console.print()

        # Show diff
        changed_lines = _show_diff(file_content, fixed_content, file_path, console)

        if changed_lines == 0:
            console.print("  [yellow]No changes in generated fix — the code may already be correct.[/yellow]")
            console.print()
            fix_results.append(FixResult(file_path=file_path, issues_fixed=0, applied=False))
            continue

        # Confirm apply
        if fix_all:
            do_apply = True
        else:
            do_apply = Confirm.ask("  Apply this fix?", default=True, console=console)

        if do_apply:
            backup_path = _backup_file(Path(file_path))
            Path(file_path).write_text(fixed_content, encoding="utf-8")
            console.print(
                f"  [bold green]✅ Applied[/bold green]  "
                f"[dim](backup: {backup_path})[/dim]"
            )
            fix_results.append(FixResult(
                file_path=file_path,
                issues_fixed=len(selected_issues),
                applied=True,
                backup_path=backup_path,
            ))
        else:
            console.print("  [dim]Skipped.[/dim]")
            fix_results.append(FixResult(file_path=file_path, issues_fixed=0, applied=False))

        console.print()

    # Summary
    total_fixed = sum(r.issues_fixed for r in fix_results)
    files_fixed = sum(1 for r in fix_results if r.applied)

    if total_fixed > 0:
        console.print(Rule(style="dim"))
        console.print(
            f"[bold green]✅ Fixed {total_fixed} issue(s) in {files_fixed} file(s)[/bold green]"
        )
        backups = [r.backup_path for r in fix_results if r.backup_path]
        if backups:
            console.print(
                f"[dim]Backups saved (.critiq.bak). "
                f"Run 'git diff' to review changes before committing.[/dim]"
            )
        console.print()

    return fix_results


def _select_issues_interactively(
    issues: list[ReviewComment], console: Console
) -> list[ReviewComment]:
    """Let the user select which issues to fix individually."""
    selected = []
    for i, issue in enumerate(issues, 1):
        icon_label = _severity_label(issue.severity)
        loc = f" {issue.line}" if issue.line else ""
        console.print(f"  [{i}] {icon_label}{loc}  {issue.title}")
        do_fix = Confirm.ask(f"      Fix this issue?", default=True, console=console)
        if do_fix:
            selected.append(issue)
    return selected
