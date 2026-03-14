"""Tests for critiq.watcher module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from critiq.watcher import _get_staged_files, watch_and_review


class TestGetStagedFiles:
    def test_returns_frozenset(self):
        with patch("critiq.watcher.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="a.py\nb.py\n")
            result = _get_staged_files()
        assert result == frozenset({"a.py", "b.py"})

    def test_returns_empty_on_error(self):
        import subprocess
        with patch("critiq.watcher.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "git")
            result = _get_staged_files()
        assert result == frozenset()

    def test_strips_empty_lines(self):
        with patch("critiq.watcher.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="a.py\n\n")
            result = _get_staged_files()
        assert result == frozenset({"a.py"})


class TestWatchAndReview:
    def test_falls_back_to_polling_without_watchfiles(self, tmp_path):
        """When watchfiles is not installed, uses polling mode."""
        run_count = []
        mock_console = MagicMock()

        def _review():
            run_count.append(1)

        # Simulate: initial call, then one staged change, then exit
        staged_calls = [
            frozenset(),       # initial
            frozenset(),       # poll 1: no change
            frozenset({"a.py"}),  # poll 2: change detected
        ]
        poll_iter = iter(staged_calls)

        import time

        with patch("critiq.watcher._HAS_WATCHFILES", False), \
             patch("critiq.watcher._get_staged_files", side_effect=staged_calls), \
             patch("critiq.watcher.time.sleep", side_effect=[None, None, KeyboardInterrupt()]):
            with pytest.raises(KeyboardInterrupt):
                watch_and_review(_review, mock_console, debounce=1.0, path=tmp_path)

        # Initial review always runs, plus one re-run after change detected
        assert len(run_count) >= 1

    def test_watch_calls_review_on_change(self, tmp_path):
        """Core: review is called when staged files change."""
        run_count = []
        mock_console = MagicMock()

        def _review():
            run_count.append(1)

        staged_sequence = [
            frozenset(),              # initial
            frozenset({"file.py"}),   # change on poll 1
        ]

        with patch("critiq.watcher._HAS_WATCHFILES", False), \
             patch("critiq.watcher._get_staged_files", side_effect=staged_sequence), \
             patch("critiq.watcher.time.sleep", side_effect=[None, KeyboardInterrupt()]):
            with pytest.raises(KeyboardInterrupt):
                watch_and_review(_review, mock_console, debounce=0.1, path=tmp_path)

        assert len(run_count) == 2  # initial + one change

    def test_no_rerun_when_staged_unchanged(self, tmp_path):
        """No extra review call when staged files don't change."""
        run_count = []
        mock_console = MagicMock()

        def _review():
            run_count.append(1)

        staged_sequence = [
            frozenset(),   # initial
            frozenset(),   # poll: no change
        ]

        with patch("critiq.watcher._HAS_WATCHFILES", False), \
             patch("critiq.watcher._get_staged_files", side_effect=staged_sequence), \
             patch("critiq.watcher.time.sleep", side_effect=[None, KeyboardInterrupt()]):
            with pytest.raises(KeyboardInterrupt):
                watch_and_review(_review, mock_console, debounce=0.1, path=tmp_path)

        assert len(run_count) == 1  # only initial review

    def test_dispatches_to_watchfiles_when_available(self, tmp_path):
        """When watchfiles IS available, uses watchfiles path."""
        run_count = []
        mock_console = MagicMock()

        def _review():
            run_count.append(1)

        with patch("critiq.watcher._HAS_WATCHFILES", True), \
             patch("critiq.watcher._watch_with_watchfiles") as mock_wf:
            watch_and_review(_review, mock_console, debounce=0.1, path=tmp_path)

        # When watchfiles is available, _watch_with_watchfiles is called
        mock_wf.assert_called_once_with(_review, mock_console, 0.1, tmp_path)
