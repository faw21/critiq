"""critiq-scan CLI — audit entire files/directories, not just git diffs.

Usage:
    critiq-scan [PATH...]           # scan files/dirs (default: current dir)
    critiq-scan src/auth.py         # scan one file
    critiq-scan src/ --include "*.py"
    critiq-scan . --focus security --severity critical
    critiq-scan . --json            # machine-readable JSON output
"""

from __future__ import annotations

import fnmatch
import json
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from . import __version__
from .config import load_config
from .formatter import print_review, print_review_compact
from .providers import get_provider
from .reviewer import ReviewResult, Severity, review_file_content, review_result_to_dict

console = Console()

# ── File discovery ─────────────────────────────────────────────────────────────

# File extensions to scan by default (source code only)
DEFAULT_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx",
    ".go", ".rs", ".rb", ".java", ".kt",
    ".c", ".cpp", ".h", ".hpp", ".cs",
    ".php", ".swift", ".scala", ".r",
    ".sh", ".bash", ".zsh",
    ".yaml", ".yml", ".toml", ".json",
    ".tf", ".hcl",
}

# Directories to always skip
SKIP_DIRS = {
    ".git", ".venv", "venv", "env", "__pycache__", ".pytest_cache",
    "node_modules", ".node_modules", "dist", "build", ".build",
    ".tox", "coverage", ".coverage", "htmlcov", ".mypy_cache",
    ".ruff_cache", "target", "vendor", ".vendor",
}

# Max file size to scan (bytes)
MAX_FILE_SIZE = 200_000  # 200 KB


def _collect_files(
    paths: tuple[str, ...],
    include: tuple[str, ...],
    exclude: tuple[str, ...],
    max_files: int,
) -> list[Path]:
    """Collect files from the given paths matching include/exclude patterns."""
    collected: list[Path] = []
    seen: set[Path] = set()

    def _should_include(file: Path) -> bool:
        # Check extension
        if file.suffix.lower() not in DEFAULT_EXTENSIONS:
            return False
        # Check size
        try:
            if file.stat().st_size > MAX_FILE_SIZE:
                return False
        except OSError:
            return False
        # Apply --include patterns
        if include:
            if not any(fnmatch.fnmatch(file.name, pat) for pat in include):
                return False
        # Apply --exclude patterns
        if exclude:
            if any(fnmatch.fnmatch(str(file), pat) or fnmatch.fnmatch(file.name, pat)
                   for pat in exclude):
                return False
        return True

    def _scan_dir(directory: Path) -> None:
        for item in sorted(directory.iterdir()):
            if item.is_dir():
                if item.name not in SKIP_DIRS and not item.name.startswith("."):
                    _scan_dir(item)
            elif item.is_file():
                resolved = item.resolve()
                if resolved not in seen and _should_include(item):
                    seen.add(resolved)
                    collected.append(item)
                    if len(collected) >= max_files:
                        return

    for raw in paths:
        p = Path(raw)
        if not p.exists():
            console.print(f"[yellow]Warning: {raw} does not exist, skipping.[/yellow]")
            continue
        if p.is_file():
            resolved = p.resolve()
            if resolved not in seen and p.suffix.lower() in DEFAULT_EXTENSIONS:
                seen.add(resolved)
                collected.append(p)
        elif p.is_dir():
            _scan_dir(p)
        if len(collected) >= max_files:
            break

    return collected[:max_files]


# ── CLI ────────────────────────────────────────────────────────────────────────

@click.command()
@click.version_option(__version__, prog_name="critiq-scan")
@click.argument("paths", nargs=-1, default=None)
@click.option(
    "--include", "include_patterns", multiple=True, metavar="PATTERN",
    help='Include only files matching PATTERN (e.g. "*.py"). Can be repeated.',
)
@click.option(
    "--exclude", "exclude_patterns", multiple=True, metavar="PATTERN",
    help='Exclude files matching PATTERN (e.g. "tests/*"). Can be repeated.',
)
@click.option(
    "--focus",
    type=click.Choice(["all", "security", "performance", "readability", "correctness", "style"]),
    default="all", show_default=True,
    help="Focus area for the audit.",
)
@click.option(
    "--severity",
    type=click.Choice(["critical", "warning", "info", "suggestion"]),
    default=None,
    help="Minimum severity to show (default: all).",
)
@click.option(
    "--provider",
    type=click.Choice(["claude", "openai", "ollama"]),
    default="claude", show_default=True,
    help="LLM provider.",
)
@click.option("--model", default=None, help="Model name override.")
@click.option(
    "--max-files", default=20, show_default=True,
    help="Maximum number of files to scan.",
)
@click.option("--compact", is_flag=True, help="Compact single-line output per finding.")
@click.option("--json", "json_output", is_flag=True, help="Output results as JSON.")
@click.option(
    "--summary", is_flag=True,
    help="Print only a summary table (no detailed findings).",
)
@click.option(
    "--context", "context_text", default=None,
    help="Extra context for the AI reviewer.",
)
def main(
    paths: tuple[str, ...],
    include_patterns: tuple[str, ...],
    exclude_patterns: tuple[str, ...],
    focus: str,
    severity: str | None,
    provider: str,
    model: str | None,
    max_files: int,
    compact: bool,
    json_output: bool,
    summary: bool,
    context_text: str | None,
) -> None:
    """Audit source files for bugs, security issues, and code quality.

    Unlike 'critiq' (which reviews git diffs), critiq-scan audits complete files.
    Useful for auditing a new codebase, reviewing legacy code, or security audits.

    \b
    Examples:
      critiq-scan                          # scan current directory
      critiq-scan src/ --focus security   # security audit of src/
      critiq-scan auth.py utils.py        # scan specific files
      critiq-scan . --include "*.py" --severity critical
    """
    scan_paths = paths if paths else (".",)

    # Collect files
    files = _collect_files(scan_paths, include_patterns, exclude_patterns, max_files)

    if not files:
        console.print(
            "[yellow]No files found to scan. "
            "Use --include to specify file patterns.[/yellow]"
        )
        sys.exit(0)

    if not json_output:
        console.print(
            f"[bold cyan]critiq-scan[/bold cyan] · "
            f"[dim]{len(files)} file{'s' if len(files) != 1 else ''} to audit[/dim]"
        )

    # Set up provider
    try:
        llm = get_provider(provider, model)
        model_label = f"{provider}/{model or 'default'}"
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        sys.exit(1)

    # Load project config
    config = load_config(Path.cwd())

    # Scan files
    all_results: list[dict] = []  # for JSON output
    all_critical = 0
    summary_rows: list[tuple[str, str, int, int, int]] = []  # (file, rating, crit, warn, info)

    severity_filter = Severity(severity) if severity else None

    for i, file_path in enumerate(files, 1):
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            if not json_output:
                console.print(f"[yellow]Skip {file_path}: {e}[/yellow]")
            continue

        if not json_output:
            console.print(
                f"[dim]({i}/{len(files)})[/dim] "
                f"[cyan]{file_path}[/cyan] "
                f"[dim]{len(content.splitlines())} lines[/dim]",
                end=" … ",
            )

        try:
            result = review_file_content(
                str(file_path),
                content,
                llm,
                focus=focus,
                context=context_text,
                model_label=model_label,
                config=config,
            )
        except Exception as e:
            if not json_output:
                console.print(f"[red]error: {e}[/red]")
            continue

        # Filter by severity
        if severity_filter is not None:
            severity_order = [Severity.CRITICAL, Severity.WARNING, Severity.INFO, Severity.SUGGESTION]
            min_idx = severity_order.index(severity_filter)
            result = ReviewResult(
                comments=[c for c in result.comments
                          if severity_order.index(c.severity) <= min_idx],
                summary=result.summary,
                overall_rating=result.overall_rating,
                provider_model=result.provider_model,
            )

        n_crit = sum(1 for c in result.comments if c.severity == Severity.CRITICAL)
        n_warn = sum(1 for c in result.comments if c.severity == Severity.WARNING)
        n_info = sum(1 for c in result.comments if c.severity == Severity.INFO)
        all_critical += n_crit

        summary_rows.append((str(file_path), result.overall_rating, n_crit, n_warn, n_info))

        if json_output:
            d = review_result_to_dict(result)
            d["file"] = str(file_path)
            all_results.append(d)
        elif summary:
            icon = "🚨" if n_crit else ("⚠️ " if n_warn else "✅")
            console.print(f"{icon} {n_crit} crit · {n_warn} warn · {n_info} info")
        else:
            if result.comments:
                console.print(f"{result.overall_rating}")
                if compact:
                    print_review_compact(result, console=console)
                else:
                    print_review(result, console=console)
            else:
                console.print("[green]✅ Clean[/green]")

    # Final output
    if json_output:
        total_critical = sum(r.get("critical_count", 0) for r in all_results)
        output = {
            "files_scanned": len(files),
            "total_critical": total_critical,
            "results": all_results,
        }
        print(json.dumps(output, indent=2))
        sys.exit(1 if total_critical > 0 else 0)

    if summary and summary_rows:
        _print_summary_table(summary_rows)

    if not json_output:
        total_issues = sum(r[2] + r[3] + r[4] for r in summary_rows)
        console.print(
            f"\n[bold]Scan complete:[/bold] "
            f"{len(summary_rows)} files · "
            f"[{'red' if all_critical else 'green'}]{all_critical} critical[/{'red' if all_critical else 'green'}] · "
            f"{sum(r[3] for r in summary_rows)} warnings · "
            f"{sum(r[4] for r in summary_rows)} info"
        )

    sys.exit(1 if all_critical > 0 else 0)


def _print_summary_table(
    rows: list[tuple[str, str, int, int, int]],
) -> None:
    """Print a summary table of scan results."""
    table = Table(title="Scan Summary", show_header=True, header_style="bold cyan")
    table.add_column("File", style="cyan", no_wrap=False)
    table.add_column("Rating", style="bold")
    table.add_column("CRIT", justify="right", style="red")
    table.add_column("WARN", justify="right", style="yellow")
    table.add_column("INFO", justify="right", style="blue")

    for file_path, rating, crit, warn, info in sorted(
        rows, key=lambda r: (-r[2], -r[3], r[0])
    ):
        style = "red" if crit else ("yellow" if warn else "green")
        table.add_row(
            str(file_path),
            rating,
            str(crit) if crit else "[dim]0[/dim]",
            str(warn) if warn else "[dim]0[/dim]",
            str(info) if info else "[dim]0[/dim]",
            style=style if crit else "",
        )

    console.print(table)
