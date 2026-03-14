"""critiq-report — AI code quality trend report for git repositories."""

from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.table import Table
from rich.text import Text

from . import __version__
from .git_utils import is_git_repo
from .providers import get_provider
from .report import (
    CACHE_DIR_NAME,
    CommitReview,
    FullReport,
    build_report,
    get_commit_history,
    review_commit,
)

console = Console()

TREND_LABELS = {
    "improving": "📈 Improving",
    "degrading": "📉 Degrading",
    "stable": "📊 Stable",
}
TREND_STYLES = {
    "improving": "green",
    "degrading": "red",
    "stable": "yellow",
}
_SPARK_BLOCKS = " ▁▂▃▄▅▆▇█"


def _sparkline(values: list[float], max_val: float) -> str:
    """Create a Unicode sparkline from a list of values."""
    if max_val == 0:
        return "─" * len(values)
    result = []
    for v in values:
        idx = int(v / max_val * (len(_SPARK_BLOCKS) - 1))
        result.append(_SPARK_BLOCKS[idx])
    return "".join(result)


def _print_report(report: FullReport) -> None:
    """Render the full report to the console."""
    non_skipped = [r for r in report.commit_reviews if not r.skipped]

    # ── Header ──────────────────────────────────────────────────────
    trend_label = TREND_LABELS.get(report.trend, "📊 Stable")
    trend_style = TREND_STYLES.get(report.trend, "yellow")

    header = Text()
    header.append(f"Analyzed {report.total_commits} commits  ", style="dim")
    header.append(f"Total issues: {report.total_issues}  ", style="bold")
    header.append(f"Trend: {trend_label}", style=f"bold {trend_style}")

    console.print(
        Panel(header, title="[bold]🔍 critiq report[/bold]", padding=(0, 1))
    )
    console.print()

    # ── Per-commit table ─────────────────────────────────────────────
    table = Table(
        title="Issues per Commit",
        show_header=True,
        header_style="bold",
        box=None,
        padding=(0, 1),
        show_lines=False,
    )
    table.add_column("Commit", style="dim", width=8)
    table.add_column("Message", width=42)
    table.add_column("Author", style="dim", width=14)
    table.add_column("🔴C", justify="right", width=4)
    table.add_column("🟡W", justify="right", width=4)
    table.add_column("🔵I", justify="right", width=4)
    table.add_column("💡S", justify="right", width=4)

    # Display chronological order (oldest first)
    for review in reversed(report.commit_reviews):
        msg = review.commit.message
        if len(msg) > 40:
            msg = msg[:39] + "…"
        author = review.commit.author
        if len(author) > 12:
            author = author[:11] + "…"

        if review.skipped:
            table.add_row(
                review.commit.short_hash,
                f"[dim]{msg}[/dim]",
                f"[dim]{author}[/dim]",
                "[dim]·[/dim]",
                "[dim]·[/dim]",
                "[dim]·[/dim]",
                "[dim]·[/dim]",
            )
        else:
            def _fmt(val: int, style: str) -> str:
                return f"[{style}]{val}[/{style}]" if val else "[dim]·[/dim]"

            table.add_row(
                review.commit.short_hash,
                msg,
                author,
                _fmt(review.critical, "bold red"),
                _fmt(review.warning, "bold yellow"),
                _fmt(review.info, "cyan"),
                _fmt(review.suggestion, "blue"),
            )

    console.print(table)

    # ── Trend sparkline ──────────────────────────────────────────────
    if non_skipped:
        console.print()
        chron = list(reversed(non_skipped))
        # Weighted score per commit (for sparkline height)
        scores = [
            r.critical * 4.0 + r.warning * 2.0 + r.info * 1.0 + r.suggestion * 0.5
            for r in chron
        ]
        max_score = max(scores) if scores else 0.0
        spark = _sparkline(scores, max_score)
        trend_style = TREND_STYLES.get(report.trend, "yellow")
        console.print(
            f"  Issue trend (oldest → newest): [{trend_style}]{spark}[/{trend_style}]"
        )

    # ── Hotspot files ────────────────────────────────────────────────
    if report.hotspot_files:
        console.print()
        hotspot_table = Table(
            title="🔥 Hotspot Files (repeatedly flagged)",
            show_header=True,
            header_style="bold",
            box=None,
            padding=(0, 1),
        )
        hotspot_table.add_column("File", style="cyan")
        hotspot_table.add_column("Times flagged", justify="right", style="yellow")

        max_count = report.hotspot_files[0][1] if report.hotspot_files else 1
        for file_path, count in report.hotspot_files[:8]:
            bar_len = max(1, round(count / max_count * 8))
            bar = "█" * bar_len
            hotspot_table.add_row(file_path, f"{count}  [dim]{bar}[/dim]")

        console.print(hotspot_table)

    # ── Footer ───────────────────────────────────────────────────────
    console.print()
    console.print(
        f"[dim]Legend: C=Critical W=Warning I=Info S=Suggestion · "
        f"Cache: {CACHE_DIR_NAME}/[/dim]"
    )


def _save_markdown(report: FullReport, output: Path) -> None:
    """Save report as a Markdown file."""
    trend_label = TREND_LABELS.get(report.trend, "📊 Stable")
    lines = [
        "# critiq Code Quality Report",
        "",
        f"**Generated:** {report.generated_at[:10]}  ",
        f"**Commits analyzed:** {report.total_commits}  ",
        f"**Total issues:** {report.total_issues}  ",
        f"**Trend:** {trend_label}",
        "",
        "## Issues per Commit",
        "",
        "| Commit | Message | Critical | Warning | Info | Suggestion |",
        "|--------|---------|:--------:|:-------:|:----:|:----------:|",
    ]
    for review in reversed(report.commit_reviews):
        msg = review.commit.message[:50]
        if review.skipped:
            lines.append(
                f"| `{review.commit.short_hash}` | {msg} | — | — | — | — |"
            )
        else:
            lines.append(
                f"| `{review.commit.short_hash}` | {msg} "
                f"| {review.critical or '·'} "
                f"| {review.warning or '·'} "
                f"| {review.info or '·'} "
                f"| {review.suggestion or '·'} |"
            )

    if report.hotspot_files:
        lines += [
            "",
            "## 🔥 Hotspot Files",
            "",
            "| File | Times Flagged |",
            "|------|:-------------:|",
        ]
        for file_path, count in report.hotspot_files:
            lines.append(f"| `{file_path}` | {count} |")

    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


@click.command()
@click.version_option(__version__, prog_name="critiq-report")
@click.option(
    "--commits",
    "-n",
    type=int,
    default=10,
    show_default=True,
    help="Number of recent commits to analyze",
)
@click.option(
    "--since",
    metavar="REF",
    default=None,
    help="Analyze commits since this tag/branch/hash (e.g. v1.0.0)",
)
@click.option(
    "--provider",
    type=click.Choice(["claude", "openai", "ollama"], case_sensitive=False),
    default="ollama",
    show_default=True,
    envvar="CRITIQ_PROVIDER",
    help="LLM provider (ollama is free/local, good for batch reviews)",
)
@click.option(
    "--model",
    default=None,
    envvar="CRITIQ_MODEL",
    help="Model name (uses provider default if not set)",
)
@click.option(
    "--no-cache",
    is_flag=True,
    default=False,
    help="Disable result caching (re-review every commit)",
)
@click.option(
    "--output",
    metavar="FILE",
    default=None,
    help="Save report as Markdown to FILE (e.g. report.md)",
)
def main(
    commits: int,
    since: str | None,
    provider: str,
    model: str | None,
    no_cache: bool,
    output: str | None,
) -> None:
    """AI code quality trend report — analyze your commit history.

    Reviews the last N commits and shows how code quality trends over time.
    Identifies hotspot files that repeatedly have issues.

    Results are cached in .critiq-report/ so re-running is fast and cheap.
    Use --provider ollama for free local reviews (no API key required).

    Examples:

      critiq-report                       # last 10 commits, free (ollama)
      critiq-report --commits 20          # last 20 commits
      critiq-report --since v1.0.0        # all commits since v1.0.0
      critiq-report --provider claude     # higher-quality reviews
      critiq-report --no-cache            # force re-review all commits
      critiq-report --output report.md    # also save as Markdown

    \b
    Tip: Add .critiq-report/ to your .gitignore.
    """
    if not is_git_repo():
        console.print("[bold red]Error:[/bold red] Not inside a git repository.")
        sys.exit(1)

    # Get commit history
    if since:
        console.print(f"[dim]Fetching commits since [bold]{since}[/bold]...[/dim]")
    else:
        console.print(f"[dim]Fetching last [bold]{commits}[/bold] commits...[/dim]")

    history = get_commit_history(n=commits, since=since)
    if not history:
        if since:
            console.print(f"[yellow]No commits found since '{since}'.[/yellow]")
        else:
            console.print("[yellow]No commits found in this repository.[/yellow]")
        sys.exit(0)

    console.print(f"[dim]Found [bold]{len(history)}[/bold] commits to review[/dim]")

    # Get LLM provider
    try:
        llm = get_provider(provider, model=model)
    except ValueError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        sys.exit(1)

    # Review commits with progress bar
    reviews: list[CommitReview] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task(
            f"[cyan]Reviewing {len(history)} commits...[/cyan]",
            total=len(history),
        )

        for commit in history:
            progress.update(
                task,
                description=(
                    f"[cyan]Reviewing [bold]{commit.short_hash}[/bold] "
                    f"{commit.message[:35]}...[/cyan]"
                ),
            )
            review = review_commit(
                commit=commit,
                provider=llm,
                use_cache=not no_cache,
            )
            reviews.append(review)
            progress.advance(task)

    # Build and display report
    report = build_report(reviews)
    _print_report(report)

    # Optionally save to Markdown
    if output:
        out_path = Path(output)
        _save_markdown(report, out_path)
        console.print(f"\n[dim]Report saved to [bold]{output}[/bold][/dim]")
