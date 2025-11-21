"""
Progress Tracking Utilities for SPECTRA
========================================

Provides progress tracking and reporting for long-running operations.
"""
from __future__ import annotations

import sys
import time
from typing import Optional, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class ProgressStats:
    """Statistics for a progress tracker."""
    total: int
    completed: int
    failed: int
    start_time: float
    elapsed_time: float
    estimated_remaining: Optional[float]
    items_per_second: float
    success_rate: float


class ProgressTracker:
    """
    Tracks and reports progress for batch operations.

    Supports both CLI and TUI environments with adaptive formatting.
    """

    def __init__(self, total: int, description: str = "Processing", show_bar: bool = True):
        """
        Initialize progress tracker.

        Args:
            total: Total number of items to process
            description: Description of the operation
            show_bar: Whether to show progress bar (disable for non-TTY)
        """
        self.total = total
        self.description = description
        self.show_bar = show_bar and sys.stdout.isatty()
        self.completed = 0
        self.failed = 0
        self.start_time = time.time()
        self.last_update_time = self.start_time
        self.update_interval = 0.1  # Update at most every 100ms

    def update(self, increment: int = 1, success: bool = True):
        """
        Update progress.

        Args:
            increment: Number of items to increment by
            success: Whether the operation was successful
        """
        self.completed += increment
        if not success:
            self.failed += increment

        # Throttle updates to avoid excessive redraws
        current_time = time.time()
        if current_time - self.last_update_time >= self.update_interval:
            self.render()
            self.last_update_time = current_time

    def render(self):
        """Render the progress display."""
        if not self.show_bar:
            return

        stats = self.get_stats()

        # Calculate progress percentage
        percent = (stats.completed / stats.total * 100) if stats.total > 0 else 0

        # Build progress bar
        bar_width = 40
        filled = int(bar_width * stats.completed / stats.total) if stats.total > 0 else 0
        bar = '█' * filled + '░' * (bar_width - filled)

        # Format timing info
        elapsed_str = self._format_time(stats.elapsed_time)
        if stats.estimated_remaining:
            eta_str = self._format_time(stats.estimated_remaining)
            timing_info = f"{elapsed_str} / ETA: {eta_str}"
        else:
            timing_info = elapsed_str

        # Format rate info
        rate_info = f"{stats.items_per_second:.1f} items/s"
        if stats.failed > 0:
            success_info = f" | Success: {stats.success_rate:.1%}"
        else:
            success_info = ""

        # Build full progress line
        line = (
            f"\r{self.description}: [{bar}] "
            f"{percent:.1f}% "
            f"({stats.completed}/{stats.total}) | "
            f"{timing_info} | {rate_info}{success_info}"
        )

        # Clear to end of line and print
        sys.stdout.write(line + " " * 10)
        sys.stdout.flush()

    def finish(self, message: Optional[str] = None):
        """
        Finish the progress tracking.

        Args:
            message: Optional completion message
        """
        if self.show_bar:
            self.render()
            sys.stdout.write("\n")
            sys.stdout.flush()

        if message:
            print(message)

    def get_stats(self) -> ProgressStats:
        """Get current progress statistics."""
        elapsed = time.time() - self.start_time
        items_per_second = self.completed / elapsed if elapsed > 0 else 0

        # Estimate remaining time
        if items_per_second > 0 and self.completed < self.total:
            remaining_items = self.total - self.completed
            estimated_remaining = remaining_items / items_per_second
        else:
            estimated_remaining = None

        # Calculate success rate
        success_rate = ((self.completed - self.failed) / self.completed) if self.completed > 0 else 1.0

        return ProgressStats(
            total=self.total,
            completed=self.completed,
            failed=self.failed,
            start_time=self.start_time,
            elapsed_time=elapsed,
            estimated_remaining=estimated_remaining,
            items_per_second=items_per_second,
            success_rate=success_rate
        )

    @staticmethod
    def _format_time(seconds: float) -> str:
        """Format time in human-readable format."""
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            minutes = seconds / 60
            return f"{minutes:.1f}m"
        else:
            hours = seconds / 3600
            return f"{hours:.1f}h"


class ProgressReporter:
    """
    Reports progress to a callback function.

    Useful for integration with TUI or web interfaces.
    """

    def __init__(self, total: int, callback: Callable[[ProgressStats], None]):
        """
        Initialize progress reporter.

        Args:
            total: Total number of items to process
            callback: Function to call with progress updates
        """
        self.total = total
        self.callback = callback
        self.completed = 0
        self.failed = 0
        self.start_time = time.time()
        self.last_callback_time = self.start_time
        self.callback_interval = 0.5  # Call callback at most every 500ms

    def update(self, increment: int = 1, success: bool = True):
        """
        Update progress and trigger callback if interval elapsed.

        Args:
            increment: Number of items to increment by
            success: Whether the operation was successful
        """
        self.completed += increment
        if not success:
            self.failed += increment

        # Throttle callbacks
        current_time = time.time()
        if current_time - self.last_callback_time >= self.callback_interval:
            stats = self._get_stats()
            self.callback(stats)
            self.last_callback_time = current_time

    def finish(self):
        """Finish progress tracking and send final callback."""
        stats = self._get_stats()
        self.callback(stats)

    def _get_stats(self) -> ProgressStats:
        """Get current progress statistics."""
        elapsed = time.time() - self.start_time
        items_per_second = self.completed / elapsed if elapsed > 0 else 0

        # Estimate remaining time
        if items_per_second > 0 and self.completed < self.total:
            remaining_items = self.total - self.completed
            estimated_remaining = remaining_items / items_per_second
        else:
            estimated_remaining = None

        # Calculate success rate
        success_rate = ((self.completed - self.failed) / self.completed) if self.completed > 0 else 1.0

        return ProgressStats(
            total=self.total,
            completed=self.completed,
            failed=self.failed,
            start_time=self.start_time,
            elapsed_time=elapsed,
            estimated_remaining=estimated_remaining,
            items_per_second=items_per_second,
            success_rate=success_rate
        )
