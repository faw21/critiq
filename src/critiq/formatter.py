"""Rich terminal output formatter for critiq review results."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from .reviewer import ReviewComment, ReviewResult, Severity


SEVERITY_COLORS = {
    Severity.CRITICAL: "bold red",
    Severity.WARNING: "bold yellow",
    Severity.INFO: "bold blue",
    Severity.SUGGESTION: "dim cyan",
}

SEVERITY_ICONS = {
    Severity.CRITICAL: "🚨",
    Severity.WARNING: "⚠️ ",
    Severity.INFO: "ℹ️ ",
    Severity.SUGGESTION: "💡",
}

RATING_COLORS = {
    "✅ LGTM": "bold green",
    "⚠️ Minor issues": "bold yellow",
    "🚨 Needs work": "bold red",
}


def _severity_badge(severity: Severity) -> Text:
    label = f" {severity.value.upper()} "
    color = SEVERITY_COLORS[severity]
    t = Text()
    t.append(label, style=f"{color} on default")
    return t


def print_review(result: ReviewResult, console: Console | None = None) -> None:
    """Print a ReviewResult to the terminal with Rich formatting."""
    c = console or Console()

    # Header
    c.print()
    c.print(Rule("[bold]critiq — AI Code Review[/bold]", style="dim"))
    c.print()

    # Model info
    c.print(f"[dim]Model: {result.provider_model}[/dim]")
    c.print()

    # Summary panel
    rating_color = RATING_COLORS.get(result.overall_rating, "bold white")
    c.print(Panel(
        f"[{rating_color}]{result.overall_rating}[/{rating_color}]\n\n{result.summary}",
        title="[bold]Summary[/bold]",
        border_style="dim",
    ))
    c.print()

    if not result.comments:
        c.print("[bold green]✅ No issues found — looks good to push![/bold green]")
        c.print()
        return

    # Stats table
    severity_counts: dict[Severity, int] = {}
    for comment in result.comments:
        severity_counts[comment.severity] = severity_counts.get(comment.severity, 0) + 1

    stats = Table(show_header=False, box=None, padding=(0, 1))
    for severity in [Severity.CRITICAL, Severity.WARNING, Severity.INFO, Severity.SUGGESTION]:
        count = severity_counts.get(severity, 0)
        if count:
            icon = SEVERITY_ICONS[severity]
            color = SEVERITY_COLORS[severity]
            stats.add_row(
                f"{icon} [{color}]{severity.value.upper()}[/{color}]",
                f"[bold]{count}[/bold]",
            )

    c.print(Panel(stats, title="[bold]Findings Overview[/bold]", border_style="dim"))
    c.print()

    # Individual findings
    for i, comment in enumerate(result.comments, 1):
        icon = SEVERITY_ICONS[comment.severity]
        color = SEVERITY_COLORS[comment.severity]

        title_text = Text()
        title_text.append(f"{icon} ", style=color)
        title_text.append(f"[{comment.severity.value.upper()}] ", style=color)
        title_text.append(comment.title)

        meta_parts = []
        if comment.file:
            meta_parts.append(f"[bold cyan]{comment.file}[/bold cyan]")
        if comment.line:
            meta_parts.append(f"[dim]{comment.line}[/dim]")
        if comment.category:
            meta_parts.append(f"[dim italic]{comment.category}[/dim italic]")

        meta = "  ".join(meta_parts) if meta_parts else ""

        body = comment.body.strip()

        content_parts = []
        if meta:
            content_parts.append(meta)
        if body:
            content_parts.append("")
            content_parts.append(body)

        panel_content = "\n".join(content_parts) if content_parts else body

        c.print(Panel(
            panel_content,
            title=title_text,
            border_style=color.replace("bold ", ""),
            title_align="left",
        ))

    c.print()
    c.print(Rule(style="dim"))
    c.print(
        f"[dim]critiq | {len(result.comments)} finding(s) | "
        f"pip install critiq | github.com/faw21/critiq[/dim]"
    )
    c.print()


def print_review_compact(result: ReviewResult, console: Console | None = None) -> None:
    """Print a compact (no panels) summary."""
    c = console or Console()

    c.print()
    rating_color = RATING_COLORS.get(result.overall_rating, "bold white")
    c.print(f"[{rating_color}]{result.overall_rating}[/{rating_color}]  {result.summary}")
    c.print()

    for comment in result.comments:
        icon = SEVERITY_ICONS[comment.severity]
        color = SEVERITY_COLORS[comment.severity]
        file_info = f"[cyan]{comment.file}[/cyan]" if comment.file else ""
        line_info = f"[dim]:{comment.line}[/dim]" if comment.line else ""
        c.print(
            f"{icon} [{color}]{comment.severity.value.upper():<10}[/{color}] "
            f"{file_info}{line_info}  {comment.title}"
        )
        if comment.body:
            for line in comment.body.strip().splitlines()[:2]:
                c.print(f"  [dim]{line}[/dim]")

    c.print()
