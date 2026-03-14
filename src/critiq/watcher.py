"""File watcher for critiq --watch mode."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Callable

from rich.console import Console

_HAS_WATCHFILES = False
try:
    from watchfiles import watch as _wf_watch

    _HAS_WATCHFILES = True
except ImportError:
    pass


def _get_staged_files() -> frozenset[str]:
    """Return the set of currently staged files."""
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True,
            text=True,
            check=True,
        )
        return frozenset(result.stdout.strip().splitlines())
    except subprocess.CalledProcessError:
        return frozenset()


def watch_and_review(
    run_review: Callable[[], None],
    console: Console,
    debounce: float = 2.0,
    path: Path | None = None,
) -> None:
    """Watch for file changes and re-run review when staged files change.

    Uses watchfiles if available, falls back to polling.

    Args:
        run_review: Callable that runs a full review cycle.
        console: Rich console for output.
        debounce: Seconds to wait after a change before running review.
        path: Directory to watch (defaults to cwd).
    """
    watch_path = path or Path.cwd()

    if _HAS_WATCHFILES:
        _watch_with_watchfiles(run_review, console, debounce, watch_path)
    else:
        _watch_with_polling(run_review, console, debounce, watch_path)


def _watch_with_watchfiles(
    run_review: Callable[[], None],
    console: Console,
    debounce: float,
    watch_path: Path,
) -> None:
    """Use watchfiles for efficient inotify/FSEvents-based watching."""
    console.print(
        f"[dim]👀 Watching [cyan]{watch_path}[/cyan] for changes... "
        f"(Ctrl+C to stop)[/dim]\n"
    )

    last_staged = _get_staged_files()
    last_run = 0.0

    # Run initial review
    run_review()

    for _changes in _wf_watch(watch_path, ignore_permission_denied=True):
        now = time.monotonic()
        if now - last_run < debounce:
            continue

        staged = _get_staged_files()
        if staged == last_staged:
            continue  # nothing new staged

        last_staged = staged
        last_run = now

        console.print("\n[dim]─" * 40 + "[/dim]")
        console.print(f"[dim]🔄 Changes detected — re-running review...[/dim]\n")
        run_review()


def _watch_with_polling(
    run_review: Callable[[], None],
    console: Console,
    debounce: float,
    watch_path: Path,
) -> None:
    """Poll for staged changes (fallback when watchfiles is not installed)."""
    console.print(
        f"[dim]👀 Polling for staged changes every {debounce:.0f}s... "
        f"(Ctrl+C to stop)[/dim]"
    )
    console.print(
        "[dim]Tip: install watchfiles for faster detection: "
        "pip install 'critiq[watch]'[/dim]\n"
    )

    last_staged = _get_staged_files()

    # Run initial review
    run_review()

    while True:
        time.sleep(debounce)
        staged = _get_staged_files()
        if staged != last_staged:
            last_staged = staged
            console.print("\n[dim]─" * 40 + "[/dim]")
            console.print("[dim]🔄 Staged changes updated — re-running review...[/dim]\n")
            run_review()
