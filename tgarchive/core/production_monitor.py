"""
SPECTRA Production Monitoring & Health Check Module
====================================================
Comprehensive monitoring, health checks, and resource management for production deployment.

Features:
- Real-time health checks
- Resource monitoring (CPU, memory, disk)
- Performance metrics collection
- Graceful shutdown handlers
- System status reporting
- Alerting thresholds
"""
from __future__ import annotations

import asyncio
import logging
import os
import platform
import psutil  # type: ignore
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set
import json

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """Health check status levels."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    CRITICAL = "critical"


class ResourceType(Enum):
    """System resource types."""
    CPU = "cpu"
    MEMORY = "memory"
    DISK = "disk"
    NETWORK = "network"
    DATABASE = "database"


@dataclass
class HealthCheckResult:
    """Result of a health check operation."""
    component: str
    status: HealthStatus
    message: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metrics: Dict[str, Any] = field(default_factory=dict)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "component": self.component,
            "status": self.status.value,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "metrics": self.metrics,
            "details": self.details,
        }


@dataclass
class ResourceMetrics:
    """System resource metrics."""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    memory_used_mb: float = 0.0
    memory_available_mb: float = 0.0
    disk_percent: float = 0.0
    disk_free_gb: float = 0.0
    network_sent_mb: float = 0.0
    network_recv_mb: float = 0.0
    process_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "cpu_percent": round(self.cpu_percent, 2),
            "memory_percent": round(self.memory_percent, 2),
            "memory_used_mb": round(self.memory_used_mb, 2),
            "memory_available_mb": round(self.memory_available_mb, 2),
            "disk_percent": round(self.disk_percent, 2),
            "disk_free_gb": round(self.disk_free_gb, 2),
            "network_sent_mb": round(self.network_sent_mb, 2),
            "network_recv_mb": round(self.network_recv_mb, 2),
            "process_count": self.process_count,
        }


@dataclass
class AlertThresholds:
    """Configurable alert thresholds for resource monitoring."""
    cpu_warning: float = 70.0  # %
    cpu_critical: float = 90.0  # %
    memory_warning: float = 75.0  # %
    memory_critical: float = 90.0  # %
    disk_warning: float = 80.0  # %
    disk_critical: float = 95.0  # %
    disk_free_warning_gb: float = 5.0  # GB
    disk_free_critical_gb: float = 1.0  # GB


class ResourceMonitor:
    """
    Monitor system resources and provide health status.
    Implements resource limit enforcement and alerting.
    """

    def __init__(
        self,
        thresholds: Optional[AlertThresholds] = None,
        data_directory: Optional[Path] = None,
    ):
        self.thresholds = thresholds or AlertThresholds()
        self.data_directory = data_directory or Path.cwd()

        self.process = psutil.Process()
        self.metrics_history: List[ResourceMetrics] = []
        self.max_history_size = 1000

        # Network baseline for delta calculations
        self._net_io_baseline = psutil.net_io_counters()
        self._baseline_time = time.time()

    def collect_metrics(self) -> ResourceMetrics:
        """Collect current resource metrics."""
        try:
            # CPU metrics
            cpu_percent = psutil.cpu_percent(interval=0.1)

            # Memory metrics
            mem = psutil.virtual_memory()
            memory_percent = mem.percent
            memory_used_mb = mem.used / (1024 * 1024)
            memory_available_mb = mem.available / (1024 * 1024)

            # Disk metrics for data directory
            disk = psutil.disk_usage(str(self.data_directory))
            disk_percent = disk.percent
            disk_free_gb = disk.free / (1024 * 1024 * 1024)

            # Network metrics (delta since baseline)
            net_io = psutil.net_io_counters()
            time_delta = time.time() - self._baseline_time

            network_sent_mb = (net_io.bytes_sent - self._net_io_baseline.bytes_sent) / (1024 * 1024)
            network_recv_mb = (net_io.bytes_recv - self._net_io_baseline.bytes_recv) / (1024 * 1024)

            # Process count
            process_count = len(psutil.pids())

            metrics = ResourceMetrics(
                cpu_percent=cpu_percent,
                memory_percent=memory_percent,
                memory_used_mb=memory_used_mb,
                memory_available_mb=memory_available_mb,
                disk_percent=disk_percent,
                disk_free_gb=disk_free_gb,
                network_sent_mb=network_sent_mb,
                network_recv_mb=network_recv_mb,
                process_count=process_count,
            )

            # Store in history
            self.metrics_history.append(metrics)
            if len(self.metrics_history) > self.max_history_size:
                self.metrics_history.pop(0)

            return metrics

        except Exception as e:
            logger.error(f"Error collecting metrics: {e}")
            return ResourceMetrics()

    def check_resource_health(self) -> List[HealthCheckResult]:
        """Check resource health against thresholds."""
        metrics = self.collect_metrics()
        results = []

        # CPU health
        if metrics.cpu_percent >= self.thresholds.cpu_critical:
            results.append(HealthCheckResult(
                component="cpu",
                status=HealthStatus.CRITICAL,
                message=f"CPU usage critical: {metrics.cpu_percent}%",
                metrics={"cpu_percent": metrics.cpu_percent}
            ))
        elif metrics.cpu_percent >= self.thresholds.cpu_warning:
            results.append(HealthCheckResult(
                component="cpu",
                status=HealthStatus.DEGRADED,
                message=f"CPU usage high: {metrics.cpu_percent}%",
                metrics={"cpu_percent": metrics.cpu_percent}
            ))
        else:
            results.append(HealthCheckResult(
                component="cpu",
                status=HealthStatus.HEALTHY,
                message=f"CPU usage normal: {metrics.cpu_percent}%",
                metrics={"cpu_percent": metrics.cpu_percent}
            ))

        # Memory health
        if metrics.memory_percent >= self.thresholds.memory_critical:
            results.append(HealthCheckResult(
                component="memory",
                status=HealthStatus.CRITICAL,
                message=f"Memory usage critical: {metrics.memory_percent}%",
                metrics={
                    "memory_percent": metrics.memory_percent,
                    "memory_used_mb": metrics.memory_used_mb,
                    "memory_available_mb": metrics.memory_available_mb,
                }
            ))
        elif metrics.memory_percent >= self.thresholds.memory_warning:
            results.append(HealthCheckResult(
                component="memory",
                status=HealthStatus.DEGRADED,
                message=f"Memory usage high: {metrics.memory_percent}%",
                metrics={
                    "memory_percent": metrics.memory_percent,
                    "memory_available_mb": metrics.memory_available_mb,
                }
            ))
        else:
            results.append(HealthCheckResult(
                component="memory",
                status=HealthStatus.HEALTHY,
                message=f"Memory usage normal: {metrics.memory_percent}%",
                metrics={"memory_percent": metrics.memory_percent}
            ))

        # Disk health
        if metrics.disk_free_gb < self.thresholds.disk_free_critical_gb:
            results.append(HealthCheckResult(
                component="disk",
                status=HealthStatus.CRITICAL,
                message=f"Disk space critical: {metrics.disk_free_gb:.2f}GB free",
                metrics={
                    "disk_percent": metrics.disk_percent,
                    "disk_free_gb": metrics.disk_free_gb,
                }
            ))
        elif (metrics.disk_free_gb < self.thresholds.disk_free_warning_gb or
              metrics.disk_percent >= self.thresholds.disk_warning):
            results.append(HealthCheckResult(
                component="disk",
                status=HealthStatus.DEGRADED,
                message=f"Disk space low: {metrics.disk_free_gb:.2f}GB free ({metrics.disk_percent}% used)",
                metrics={
                    "disk_percent": metrics.disk_percent,
                    "disk_free_gb": metrics.disk_free_gb,
                }
            ))
        else:
            results.append(HealthCheckResult(
                component="disk",
                status=HealthStatus.HEALTHY,
                message=f"Disk space adequate: {metrics.disk_free_gb:.2f}GB free",
                metrics={"disk_free_gb": metrics.disk_free_gb}
            ))

        return results

    def get_metrics_summary(self, last_n_minutes: int = 5) -> Dict[str, Any]:
        """Get summary statistics for recent metrics."""
        if not self.metrics_history:
            return {}

        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=last_n_minutes)
        recent_metrics = [m for m in self.metrics_history if m.timestamp >= cutoff_time]

        if not recent_metrics:
            recent_metrics = self.metrics_history[-10:]  # Last 10 if none in time window

        cpu_values = [m.cpu_percent for m in recent_metrics]
        memory_values = [m.memory_percent for m in recent_metrics]
        disk_values = [m.disk_percent for m in recent_metrics]

        return {
            "time_window_minutes": last_n_minutes,
            "sample_count": len(recent_metrics),
            "cpu": {
                "current": cpu_values[-1] if cpu_values else 0,
                "average": sum(cpu_values) / len(cpu_values) if cpu_values else 0,
                "max": max(cpu_values) if cpu_values else 0,
                "min": min(cpu_values) if cpu_values else 0,
            },
            "memory": {
                "current": memory_values[-1] if memory_values else 0,
                "average": sum(memory_values) / len(memory_values) if memory_values else 0,
                "max": max(memory_values) if memory_values else 0,
            },
            "disk": {
                "current": disk_values[-1] if disk_values else 0,
            },
        }

    def should_throttle_operations(self) -> tuple[bool, str]:
        """
        Determine if operations should be throttled based on resource usage.

        Returns:
            (should_throttle: bool, reason: str)
        """
        metrics = self.collect_metrics()

        if metrics.memory_percent >= self.thresholds.memory_critical:
            return True, f"Memory critical: {metrics.memory_percent}%"

        if metrics.disk_free_gb < self.thresholds.disk_free_critical_gb:
            return True, f"Disk space critical: {metrics.disk_free_gb:.2f}GB"

        if metrics.cpu_percent >= self.thresholds.cpu_critical:
            return True, f"CPU critical: {metrics.cpu_percent}%"

        return False, ""


class HealthCheckManager:
    """
    Comprehensive health check manager for production monitoring.
    Orchestrates multiple health check components.
    """

    def __init__(
        self,
        resource_monitor: Optional[ResourceMonitor] = None,
        enable_auto_checks: bool = True,
        check_interval_seconds: int = 60,
    ):
        self.resource_monitor = resource_monitor or ResourceMonitor()
        self.enable_auto_checks = enable_auto_checks
        self.check_interval_seconds = check_interval_seconds

        self.last_check_time: Optional[datetime] = None
        self.last_check_results: List[HealthCheckResult] = []
        self.custom_checks: Dict[str, Callable] = {}

        self._auto_check_task: Optional[asyncio.Task] = None
        self._is_running = False

    def register_custom_check(self, name: str, check_func: Callable) -> None:
        """
        Register a custom health check function.

        Args:
            name: Unique name for the check
            check_func: Async function that returns HealthCheckResult
        """
        self.custom_checks[name] = check_func
        logger.info(f"Registered custom health check: {name}")

    async def run_all_checks(self) -> List[HealthCheckResult]:
        """Run all health checks and return results."""
        results = []

        # System resource checks
        resource_results = self.resource_monitor.check_resource_health()
        results.extend(resource_results)

        # Custom checks
        for name, check_func in self.custom_checks.items():
            try:
                result = await check_func()
                if isinstance(result, HealthCheckResult):
                    results.append(result)
                else:
                    logger.warning(f"Custom check {name} returned invalid result")
            except Exception as e:
                logger.error(f"Error in custom check {name}: {e}")
                results.append(HealthCheckResult(
                    component=name,
                    status=HealthStatus.UNHEALTHY,
                    message=f"Check failed: {str(e)}"
                ))

        self.last_check_time = datetime.now(timezone.utc)
        self.last_check_results = results

        return results

    async def get_overall_status(self) -> HealthCheckResult:
        """Get overall system health status."""
        results = await self.run_all_checks()

        # Determine overall status (worst status wins)
        status_priority = {
            HealthStatus.HEALTHY: 0,
            HealthStatus.DEGRADED: 1,
            HealthStatus.UNHEALTHY: 2,
            HealthStatus.CRITICAL: 3,
        }

        overall_status = HealthStatus.HEALTHY
        for result in results:
            if status_priority[result.status] > status_priority[overall_status]:
                overall_status = result.status

        # Count components by status
        status_counts = {}
        for result in results:
            status_counts[result.status.value] = status_counts.get(result.status.value, 0) + 1

        message_parts = []
        for status, count in status_counts.items():
            message_parts.append(f"{count} {status}")

        return HealthCheckResult(
            component="system",
            status=overall_status,
            message=f"Overall: {overall_status.value} ({', '.join(message_parts)})",
            details={
                "component_count": len(results),
                "status_breakdown": status_counts,
                "check_results": [r.to_dict() for r in results],
            }
        )

    async def _auto_check_loop(self) -> None:
        """Background task for periodic health checks."""
        logger.info(f"Starting auto health checks (interval: {self.check_interval_seconds}s)")

        while self._is_running:
            try:
                await self.run_all_checks()

                # Log if any issues found
                critical_results = [r for r in self.last_check_results
                                   if r.status in (HealthStatus.CRITICAL, HealthStatus.UNHEALTHY)]
                if critical_results:
                    for result in critical_results:
                        logger.warning(f"Health check alert: {result.component} - {result.message}")

                await asyncio.sleep(self.check_interval_seconds)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in auto health check loop: {e}")
                await asyncio.sleep(self.check_interval_seconds)

    async def start_monitoring(self) -> None:
        """Start automatic health monitoring."""
        if not self.enable_auto_checks:
            logger.info("Auto health checks disabled")
            return

        if self._is_running:
            logger.warning("Health monitoring already running")
            return

        self._is_running = True
        self._auto_check_task = asyncio.create_task(self._auto_check_loop())
        logger.info("Health monitoring started")

    async def stop_monitoring(self) -> None:
        """Stop automatic health monitoring."""
        self._is_running = False

        if self._auto_check_task:
            self._auto_check_task.cancel()
            try:
                await self._auto_check_task
            except asyncio.CancelledError:
                pass

        logger.info("Health monitoring stopped")

    def export_status_json(self, output_file: Path) -> None:
        """Export current health status to JSON file."""
        try:
            status_data = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "last_check_time": self.last_check_time.isoformat() if self.last_check_time else None,
                "results": [r.to_dict() for r in self.last_check_results],
                "metrics": self.resource_monitor.get_metrics_summary(),
                "system_info": {
                    "platform": platform.platform(),
                    "python_version": sys.version,
                    "hostname": platform.node(),
                },
            }

            output_file.write_text(json.dumps(status_data, indent=2))
            logger.debug(f"Health status exported to {output_file}")

        except Exception as e:
            logger.error(f"Error exporting health status: {e}")


class GracefulShutdownManager:
    """
    Manages graceful shutdown of the application.
    Ensures proper cleanup and resource release.
    """

    def __init__(self):
        self.shutdown_callbacks: List[Callable] = []
        self.is_shutting_down = False
        self._shutdown_event = asyncio.Event()

        # Register signal handlers
        self._register_signal_handlers()

    def _register_signal_handlers(self) -> None:
        """Register handlers for shutdown signals."""
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, initiating graceful shutdown")
            asyncio.create_task(self.shutdown())

        # Handle common shutdown signals
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, signal_handler)
            except (ValueError, OSError) as e:
                logger.warning(f"Could not register handler for signal {sig}: {e}")

    def register_shutdown_callback(self, callback: Callable) -> None:
        """
        Register a callback to be called during shutdown.

        Args:
            callback: Async or sync function to call on shutdown
        """
        self.shutdown_callbacks.append(callback)
        logger.debug(f"Registered shutdown callback: {callback.__name__}")

    async def shutdown(self) -> None:
        """Execute graceful shutdown sequence."""
        if self.is_shutting_down:
            logger.warning("Shutdown already in progress")
            return

        self.is_shutting_down = True
        logger.info("Beginning graceful shutdown...")

        # Execute all shutdown callbacks
        for callback in self.shutdown_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback()
                else:
                    callback()
                logger.debug(f"Executed shutdown callback: {callback.__name__}")
            except Exception as e:
                logger.error(f"Error in shutdown callback {callback.__name__}: {e}")

        self._shutdown_event.set()
        logger.info("Graceful shutdown complete")

    async def wait_for_shutdown(self) -> None:
        """Wait for shutdown signal."""
        await self._shutdown_event.wait()

    @property
    def should_shutdown(self) -> bool:
        """Check if shutdown is in progress."""
        return self.is_shutting_down


__all__ = [
    "HealthStatus",
    "ResourceType",
    "HealthCheckResult",
    "ResourceMetrics",
    "AlertThresholds",
    "ResourceMonitor",
    "HealthCheckManager",
    "GracefulShutdownManager",
]
