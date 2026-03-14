"""critiq-install and critiq-uninstall — manage git hook integration."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import click
from rich.console import Console

console = Console()

# ── Hook script templates ─────────────────────────────────────────────────────

_PRE_COMMIT_HOOK = """\
#!/bin/sh
# critiq pre-commit hook — AI code review before each commit
# Installed by: critiq-install
# Bypass: git commit --no-verify

if ! command -v critiq >/dev/null 2>&1; then
  echo "critiq: not found — skipping AI review. Install with: pip install critiq"
  exit 0
fi

# Run review on staged changes; exit 1 only on CRITICAL issues
critiq --staged --severity critical --compact
exit_code=$?

if [ "$exit_code" -ne 0 ]; then
  echo ""
  echo "critiq: ⛔ Commit blocked — CRITICAL issues found above."
  echo "  Fix the issues or bypass with: git commit --no-verify"
  exit 1
fi

exit 0
"""

_PRE_PUSH_HOOK = """\
#!/bin/sh
# critiq pre-push hook — AI code review before pushing
# Installed by: critiq-install --pre-push
# Bypass: git push --no-verify

if ! command -v critiq >/dev/null 2>&1; then
  echo "critiq: not found — skipping AI review. Install with: pip install critiq"
  exit 0
fi

# Get the default branch to compare against
branch=$(git symbolic-ref --short HEAD 2>/dev/null || echo "HEAD")
base=$(git rev-parse --abbrev-ref --symbolic-full-name @{upstream} 2>/dev/null || echo "main")

echo "critiq: Reviewing changes vs $base..."
critiq --diff "$base" --severity critical --compact
exit_code=$?

if [ "$exit_code" -ne 0 ]; then
  echo ""
  echo "critiq: ⛔ Push blocked — CRITICAL issues found above."
  echo "  Fix the issues or bypass with: git push --no-verify"
  exit 1
fi

exit 0
"""

_CRITIQ_MARKER = "# critiq pre-commit hook"
_CRITIQ_PUSH_MARKER = "# critiq pre-push hook"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _find_git_dir() -> Path | None:
    """Walk up from cwd to find .git directory."""
    current = Path.cwd()
    for candidate in [current, *current.parents]:
        git = candidate / ".git"
        if git.is_dir():
            return git
    return None


def _make_executable(path: Path) -> None:
    """Add executable bit to a file."""
    current_mode = path.stat().st_mode
    path.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _install_hook(
    hooks_dir: Path,
    hook_name: str,
    hook_content: str,
    marker: str,
    force: bool,
) -> None:
    """Write or append a hook to hooks_dir/hook_name."""
    hook_path = hooks_dir / hook_name

    if hook_path.exists():
        existing = hook_path.read_text()
        if marker in existing:
            console.print(
                f"[yellow]critiq hook already installed in {hook_path}[/yellow]"
            )
            return

        if not force:
            console.print(
                f"[yellow]Existing {hook_name} hook found.[/yellow] "
                "critiq will be appended to it."
            )
            # Append to existing hook
            new_content = existing.rstrip() + "\n\n" + hook_content
            hook_path.write_text(new_content)
        else:
            hook_path.write_text(hook_content)
    else:
        hook_path.write_text(hook_content)

    _make_executable(hook_path)


# ── CLI ───────────────────────────────────────────────────────────────────────

@click.command()
@click.option(
    "--pre-push",
    is_flag=True,
    default=False,
    help="Install as pre-push hook instead of pre-commit",
)
@click.option(
    "--force",
    "-f",
    is_flag=True,
    default=False,
    help="Overwrite existing hook (instead of appending)",
)
def install(pre_push: bool, force: bool) -> None:
    """Install critiq as a git hook.

    By default, installs a pre-commit hook that blocks commits with
    CRITICAL issues. Use --pre-push to run on push instead.

    Examples:

      critiq-install                  # block commits with critical issues
      critiq-install --pre-push       # block pushes with critical issues
      critiq-install --force          # overwrite existing hook
    """
    git_dir = _find_git_dir()
    if git_dir is None:
        console.print("[bold red]Error:[/bold red] Not inside a git repository.")
        sys.exit(1)

    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(exist_ok=True)

    if pre_push:
        hook_name = "pre-push"
        hook_content = _PRE_PUSH_HOOK
        marker = _CRITIQ_PUSH_MARKER
    else:
        hook_name = "pre-commit"
        hook_content = _PRE_COMMIT_HOOK
        marker = _CRITIQ_MARKER

    _install_hook(hooks_dir, hook_name, hook_content, marker, force)

    hook_path = hooks_dir / hook_name
    console.print(
        f"[bold green]✅ critiq {hook_name} hook installed![/bold green]\n"
        f"   Path: {hook_path}\n"
    )
    if pre_push:
        console.print(
            "   critiq will now review your changes before every [bold]git push[/bold].\n"
            "   Bypass: [dim]git push --no-verify[/dim]"
        )
    else:
        console.print(
            "   critiq will now review staged changes before every [bold]git commit[/bold].\n"
            "   Bypass: [dim]git commit --no-verify[/dim]"
        )


@click.command()
@click.option(
    "--pre-push",
    is_flag=True,
    default=False,
    help="Remove the pre-push hook instead of pre-commit",
)
def uninstall(pre_push: bool) -> None:
    """Remove the critiq git hook.

    Examples:

      critiq-uninstall                # remove pre-commit hook
      critiq-uninstall --pre-push     # remove pre-push hook
    """
    git_dir = _find_git_dir()
    if git_dir is None:
        console.print("[bold red]Error:[/bold red] Not inside a git repository.")
        sys.exit(1)

    hook_name = "pre-push" if pre_push else "pre-commit"
    marker = _CRITIQ_PUSH_MARKER if pre_push else _CRITIQ_MARKER
    hook_path = git_dir / "hooks" / hook_name

    if not hook_path.exists():
        console.print(f"[yellow]No {hook_name} hook found.[/yellow]")
        return

    existing = hook_path.read_text()

    if marker not in existing:
        console.print(
            f"[yellow]No critiq hook found in {hook_path}.[/yellow] "
            "Nothing to remove."
        )
        return

    # Strip the critiq block from the hook
    lines = existing.split("\n")
    # Find the line with the marker and remove from that point
    # For appended hooks, remove from the blank line before marker
    result_lines: list[str] = []
    skip = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if marker in line:
            skip = True
            # Remove trailing blank line that was added before the block
            if result_lines and result_lines[-1].strip() == "":
                result_lines.pop()
        if not skip:
            result_lines.append(line)
        i += 1

    new_content = "\n".join(result_lines).rstrip() + "\n"

    if new_content.strip() in ("#!/bin/sh", ""):
        # Hook would be empty after removal — delete it
        hook_path.unlink()
        console.print(
            f"[bold green]✅ critiq {hook_name} hook removed.[/bold green]"
        )
    else:
        hook_path.write_text(new_content)
        console.print(
            f"[bold green]✅ critiq block removed from {hook_path}.[/bold green]"
        )
