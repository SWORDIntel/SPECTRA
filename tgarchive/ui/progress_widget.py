"""
TUI Progress Widget for SPECTRA
=================================

npyscreen widget for displaying real-time progress bars in TUI forms.
Integrates with existing ProgressTracker and ProgressReporter.
"""

import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import npyscreen
    HAS_NPYSCREEN = True
except ImportError:
    HAS_NPYSCREEN = False
    logger.warning("npyscreen not available - TUI progress widget disabled")

if HAS_NPYSCREEN:
    from ..utils.progress import ProgressReporter, ProgressStats


if HAS_NPYSCREEN:
    try:
        class TUIProgressWidget(npyscreen.BoxTitle):
        """
        Progress bar widget for npyscreen forms.
        
        Displays real-time progress with bar, percentage, ETA, and rate.
        """
        
        _contained_widget = npyscreen.FixedText
        
        def __init__(self, *args, **keywords):
            super().__init__(*args, **keywords)
            self.progress_reporter: Optional[ProgressReporter] = None
            self.total = 0
            self.completed = 0
            self.failed = 0
            self.description = ""
            self.start_time = None
            self.update_thread: Optional[threading.Thread] = None
            self._stop_update = False
        
        def set_progress_reporter(self, reporter: ProgressReporter):
            """Set the progress reporter to display"""
            self.progress_reporter = reporter
            self.total = reporter.total
            self.description = "Processing"
            self.start_time = time.time()
            self._stop_update = False
            
            # Start update thread
            self.update_thread = threading.Thread(target=self._update_loop, daemon=True)
            self.update_thread.start()
        
        def _update_loop(self):
            """Background thread to update progress display"""
            while not self._stop_update and self.progress_reporter:
                stats = self.progress_reporter._get_stats()
                self._update_display(stats)
                time.sleep(0.5)  # Update every 500ms
        
        def _update_display(self, stats: ProgressStats):
            """Update the progress display"""
            try:
                # Calculate progress percentage
                percent = (stats.completed / stats.total * 100) if stats.total > 0 else 0
                
                # Build progress bar
                bar_width = 30
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
                
                # Build progress line
                progress_line = (
                    f"{self.description}: [{bar}] {percent:.1f}% "
                    f"({stats.completed}/{stats.total}) | "
                    f"{timing_info} | {rate_info}{success_info}"
                )
                
                # Update widget value
                self.value = progress_line
                self.display()
                
            except Exception as e:
                logger.debug(f"Error updating progress display: {e}")
        
        @staticmethod
        def _format_time(seconds: float) -> str:
            """Format time in human-readable format"""
            if seconds < 60:
                return f"{seconds:.0f}s"
            elif seconds < 3600:
                minutes = seconds / 60
                return f"{minutes:.1f}m"
            else:
                hours = seconds / 3600
                return f"{hours:.1f}h"
        
        def stop(self):
            """Stop the update thread"""
            self._stop_update = True
            if self.update_thread:
                self.update_thread.join(timeout=1.0)
        
        def __del__(self):
            """Cleanup on deletion"""
            self.stop()
    except (AttributeError, TypeError):
        # npyscreen not fully available
        TUIProgressWidget = None


if HAS_NPYSCREEN:
    try:
        class BackgroundJobNotification:
        """
        Manages background job notifications in TUI.
        
        Shows notifications when background operations complete.
        """
        
        def __init__(self, status_widget):
            """
            Initialize background job notification system.
            
            Args:
                status_widget: StatusMessages widget to display notifications
            """
            self.status_widget = status_widget
            self.active_jobs = {}
        
        def register_job(self, job_id: str, description: str):
            """Register a new background job"""
            self.active_jobs[job_id] = {
                'description': description,
                'start_time': time.time(),
                'status': 'running',
            }
            self.status_widget.add_message(f"Background job started: {description}", "INFO")
        
        def update_job(self, job_id: str, status: str, message: Optional[str] = None):
            """Update job status"""
            if job_id in self.active_jobs:
                job = self.active_jobs[job_id]
                job['status'] = status
                execution_time = time.time() - job['start_time']
                
                if status == 'completed':
                    self.status_widget.add_message(
                        f"✓ {job['description']} completed in {execution_time:.1f}s",
                        "SUCCESS"
                    )
                elif status == 'failed':
                    error_msg = f"✗ {job['description']} failed"
                    if message:
                        error_msg += f": {message}"
                    self.status_widget.add_message(error_msg, "ERROR")
                elif status == 'cancelled':
                    self.status_widget.add_message(
                        f"⊘ {job['description']} cancelled",
                        "WARNING"
                    )
                
                if status in ('completed', 'failed', 'cancelled'):
                    del self.active_jobs[job_id]
        
        def get_active_jobs(self) -> dict:
            """Get list of active jobs"""
            return self.active_jobs.copy()

    except (AttributeError, TypeError):
        BackgroundJobNotification = None
else:
    # Dummy classes if npyscreen not available
    TUIProgressWidget = None
    BackgroundJobNotification = None
