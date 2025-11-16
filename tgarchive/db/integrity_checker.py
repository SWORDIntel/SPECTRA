"""
SPECTRA Database Integrity Checker
===================================
Validates database schema integrity, checks for corruption, and performs health checks.

Features:
- Schema validation against expected structure
- Foreign key constraint verification
- Index integrity checks
- Data corruption detection
- Performance diagnostics
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


@dataclass
class IntegrityCheckResult:
    """Result of a database integrity check."""
    check_name: str
    passed: bool
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __str__(self) -> str:
        status = "✓ PASS" if self.passed else "✗ FAIL"
        return f"{status} - {self.check_name}: {self.message}"


class DatabaseIntegrityChecker:
    """
    Comprehensive database integrity checker for production environments.
    """

    # Expected schema tables
    EXPECTED_TABLES = {
        "users": ["id", "username", "first_name", "last_name", "tags", "avatar", "last_updated"],
        "media": ["id", "type", "url", "title", "description", "thumb", "checksum"],
        "messages": ["id", "type", "date", "edit_date", "content", "reply_to", "user_id", "media_id", "checksum"],
        "checkpoints": ["id", "last_message_id", "checkpoint_time", "context"],
    }

    # Expected indexes
    EXPECTED_INDEXES = [
        ("idx_users_username", "users"),
        ("idx_media_type", "media"),
        ("idx_messages_date", "messages"),
        ("idx_messages_user", "messages"),
    ]

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.results: List[IntegrityCheckResult] = []

    def run_all_checks(self) -> Tuple[bool, List[IntegrityCheckResult]]:
        """
        Run all integrity checks.

        Returns:
            (all_passed: bool, results: List[IntegrityCheckResult])
        """
        self.results.clear()

        if not self.db_path.exists():
            self.results.append(IntegrityCheckResult(
                check_name="database_exists",
                passed=False,
                message=f"Database file not found: {self.db_path}"
            ))
            return False, self.results

        try:
            conn = sqlite3.connect(self.db_path)

            # Run all checks
            self._check_database_format(conn)
            self._check_schema_tables(conn)
            self._check_schema_columns(conn)
            self._check_indexes(conn)
            self._check_foreign_keys(conn)
            self._check_sqlite_integrity(conn)
            self._check_performance_stats(conn)

            conn.close()

        except sqlite3.Error as e:
            self.results.append(IntegrityCheckResult(
                check_name="database_connection",
                passed=False,
                message=f"Failed to connect to database: {e}"
            ))
            return False, self.results

        # Check if all tests passed
        all_passed = all(r.passed for r in self.results)

        return all_passed, self.results

    def _check_database_format(self, conn: sqlite3.Connection) -> None:
        """Check if the database is a valid SQLite database."""
        try:
            cursor = conn.cursor()

            # Check SQLite version
            cursor.execute("SELECT sqlite_version()")
            version = cursor.fetchone()[0]

            self.results.append(IntegrityCheckResult(
                check_name="database_format",
                passed=True,
                message=f"Valid SQLite database (version {version})",
                details={"sqlite_version": version}
            ))

        except sqlite3.Error as e:
            self.results.append(IntegrityCheckResult(
                check_name="database_format",
                passed=False,
                message=f"Invalid database format: {e}"
            ))

    def _check_schema_tables(self, conn: sqlite3.Connection) -> None:
        """Check if all expected tables exist."""
        try:
            cursor = conn.cursor()

            # Get all tables
            cursor.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
            """)
            actual_tables = set(row[0] for row in cursor.fetchall())

            expected_tables = set(self.EXPECTED_TABLES.keys())
            missing_tables = expected_tables - actual_tables
            extra_tables = actual_tables - expected_tables

            if missing_tables:
                self.results.append(IntegrityCheckResult(
                    check_name="schema_tables",
                    passed=False,
                    message=f"Missing tables: {', '.join(missing_tables)}",
                    details={
                        "expected": list(expected_tables),
                        "actual": list(actual_tables),
                        "missing": list(missing_tables)
                    }
                ))
            else:
                details = {"tables": list(actual_tables)}
                if extra_tables:
                    details["extra_tables"] = list(extra_tables)

                self.results.append(IntegrityCheckResult(
                    check_name="schema_tables",
                    passed=True,
                    message=f"All {len(expected_tables)} expected tables exist",
                    details=details
                ))

        except sqlite3.Error as e:
            self.results.append(IntegrityCheckResult(
                check_name="schema_tables",
                passed=False,
                message=f"Error checking tables: {e}"
            ))

    def _check_schema_columns(self, conn: sqlite3.Connection) -> None:
        """Check if tables have expected columns."""
        try:
            cursor = conn.cursor()

            all_columns_valid = True
            issues = []

            for table_name, expected_columns in self.EXPECTED_TABLES.items():
                # Get table info
                cursor.execute(f"PRAGMA table_info({table_name})")
                columns_info = cursor.fetchall()

                if not columns_info:
                    all_columns_valid = False
                    issues.append(f"Table {table_name} not found")
                    continue

                actual_columns = [col[1] for col in columns_info]  # col[1] is column name
                expected_set = set(expected_columns)
                actual_set = set(actual_columns)

                missing_columns = expected_set - actual_set
                if missing_columns:
                    all_columns_valid = False
                    issues.append(f"Table {table_name} missing columns: {', '.join(missing_columns)}")

            if all_columns_valid:
                self.results.append(IntegrityCheckResult(
                    check_name="schema_columns",
                    passed=True,
                    message="All tables have required columns"
                ))
            else:
                self.results.append(IntegrityCheckResult(
                    check_name="schema_columns",
                    passed=False,
                    message="Column schema issues found",
                    details={"issues": issues}
                ))

        except sqlite3.Error as e:
            self.results.append(IntegrityCheckResult(
                check_name="schema_columns",
                passed=False,
                message=f"Error checking columns: {e}"
            ))

    def _check_indexes(self, conn: sqlite3.Connection) -> None:
        """Check if expected indexes exist."""
        try:
            cursor = conn.cursor()

            # Get all indexes
            cursor.execute("""
                SELECT name, tbl_name FROM sqlite_master
                WHERE type='index' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
            """)
            actual_indexes = {(row[0], row[1]) for row in cursor.fetchall()}

            expected_indexes = set(self.EXPECTED_INDEXES)
            missing_indexes = expected_indexes - actual_indexes

            if missing_indexes:
                missing_list = [f"{idx}({tbl})" for idx, tbl in missing_indexes]
                self.results.append(IntegrityCheckResult(
                    check_name="indexes",
                    passed=False,
                    message=f"Missing indexes: {', '.join(missing_list)}",
                    details={
                        "expected": [f"{idx}({tbl})" for idx, tbl in expected_indexes],
                        "missing": missing_list
                    }
                ))
            else:
                self.results.append(IntegrityCheckResult(
                    check_name="indexes",
                    passed=True,
                    message=f"All {len(expected_indexes)} expected indexes exist",
                    details={"indexes": [f"{idx}({tbl})" for idx, tbl in actual_indexes]}
                ))

        except sqlite3.Error as e:
            self.results.append(IntegrityCheckResult(
                check_name="indexes",
                passed=False,
                message=f"Error checking indexes: {e}"
            ))

    def _check_foreign_keys(self, conn: sqlite3.Connection) -> None:
        """Check if foreign keys are enabled and valid."""
        try:
            cursor = conn.cursor()

            # Check if foreign keys are enabled
            cursor.execute("PRAGMA foreign_keys")
            fk_enabled = cursor.fetchone()[0]

            if not fk_enabled:
                self.results.append(IntegrityCheckResult(
                    check_name="foreign_keys_enabled",
                    passed=False,
                    message="Foreign keys are not enabled (PRAGMA foreign_keys=OFF)"
                ))
                return

            # Check foreign key integrity
            cursor.execute("PRAGMA foreign_key_check")
            violations = cursor.fetchall()

            if violations:
                self.results.append(IntegrityCheckResult(
                    check_name="foreign_key_integrity",
                    passed=False,
                    message=f"Found {len(violations)} foreign key violations",
                    details={"violations": [str(v) for v in violations[:10]]}  # First 10
                ))
            else:
                self.results.append(IntegrityCheckResult(
                    check_name="foreign_key_integrity",
                    passed=True,
                    message="All foreign key constraints are valid"
                ))

        except sqlite3.Error as e:
            self.results.append(IntegrityCheckResult(
                check_name="foreign_keys",
                passed=False,
                message=f"Error checking foreign keys: {e}"
            ))

    def _check_sqlite_integrity(self, conn: sqlite3.Connection) -> None:
        """Run SQLite's built-in integrity check."""
        try:
            cursor = conn.cursor()

            # Run integrity check
            cursor.execute("PRAGMA integrity_check")
            result = cursor.fetchone()

            if result and result[0] == "ok":
                self.results.append(IntegrityCheckResult(
                    check_name="sqlite_integrity",
                    passed=True,
                    message="SQLite integrity check passed"
                ))
            else:
                issues = [result[0]] if result else ["Unknown error"]
                self.results.append(IntegrityCheckResult(
                    check_name="sqlite_integrity",
                    passed=False,
                    message="SQLite integrity check failed",
                    details={"issues": issues}
                ))

        except sqlite3.Error as e:
            self.results.append(IntegrityCheckResult(
                check_name="sqlite_integrity",
                passed=False,
                message=f"Error running integrity check: {e}"
            ))

    def _check_performance_stats(self, conn: sqlite3.Connection) -> None:
        """Collect performance statistics."""
        try:
            cursor = conn.cursor()

            stats = {}

            # Database size
            cursor.execute("SELECT page_count * page_size as size FROM pragma_page_count(), pragma_page_size()")
            db_size = cursor.fetchone()[0]
            stats["database_size_mb"] = round(db_size / (1024 * 1024), 2)

            # Row counts
            for table in self.EXPECTED_TABLES.keys():
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    count = cursor.fetchone()[0]
                    stats[f"{table}_count"] = count
                except sqlite3.Error:
                    stats[f"{table}_count"] = "error"

            # WAL mode check
            cursor.execute("PRAGMA journal_mode")
            journal_mode = cursor.fetchone()[0]
            stats["journal_mode"] = journal_mode

            # Check if analyze has been run
            cursor.execute("SELECT COUNT(*) FROM sqlite_stat1")
            has_stats = cursor.fetchone()[0] > 0
            stats["has_statistics"] = has_stats

            self.results.append(IntegrityCheckResult(
                check_name="performance_stats",
                passed=True,
                message=f"Database: {stats['database_size_mb']}MB, Journal: {journal_mode}",
                details=stats
            ))

        except sqlite3.Error as e:
            self.results.append(IntegrityCheckResult(
                check_name="performance_stats",
                passed=False,
                message=f"Error collecting stats: {e}"
            ))

    def get_summary(self) -> Dict[str, Any]:
        """Get summary of all checks."""
        if not self.results:
            return {"status": "not_run"}

        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        failed = total - passed

        return {
            "total_checks": total,
            "passed": passed,
            "failed": failed,
            "success_rate": round((passed / total) * 100, 2) if total > 0 else 0,
            "all_passed": failed == 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def print_report(self) -> None:
        """Print a formatted report of all checks."""
        print("\n" + "=" * 70)
        print("DATABASE INTEGRITY CHECK REPORT")
        print("=" * 70)

        for result in self.results:
            print(f"\n{result}")
            if result.details:
                for key, value in result.details.items():
                    if isinstance(value, (list, dict)) and len(str(value)) > 100:
                        print(f"  {key}: <{len(value)} items>")
                    else:
                        print(f"  {key}: {value}")

        print("\n" + "-" * 70)
        summary = self.get_summary()
        print(f"SUMMARY: {summary['passed']}/{summary['total_checks']} checks passed "
              f"({summary['success_rate']}%)")
        print("=" * 70 + "\n")


def quick_integrity_check(db_path: Path | str) -> bool:
    """
    Quick integrity check for startup validation.

    Returns:
        True if basic checks pass, False otherwise
    """
    checker = DatabaseIntegrityChecker(db_path)

    if not checker.db_path.exists():
        logger.warning(f"Database not found: {db_path}")
        return True  # Allow creation

    try:
        conn = sqlite3.connect(checker.db_path, timeout=5.0)

        # Quick checks only
        checker._check_database_format(conn)
        checker._check_schema_tables(conn)
        checker._check_sqlite_integrity(conn)

        conn.close()

        # Check if critical checks passed
        critical_checks = ["database_format", "sqlite_integrity"]
        critical_results = [r for r in checker.results if r.check_name in critical_checks]

        return all(r.passed for r in critical_results)

    except sqlite3.Error as e:
        logger.error(f"Database integrity check failed: {e}")
        return False


__all__ = [
    "IntegrityCheckResult",
    "DatabaseIntegrityChecker",
    "quick_integrity_check",
]
