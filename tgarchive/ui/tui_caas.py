from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import npyscreen

from tgarchive.core.config_models import Config
from tgarchive.core.sync import logger
from tgarchive.core.sync_canonical import runner_canonical
from tgarchive.db import SpectraDB
from tgarchive.osint.caas.discovery_ops import discover_with_caas
from tgarchive.osint.caas.queue_worker import process_queue
from tgarchive.osint.caas.schema import ensure_schema

TZ = timezone.utc
TITLE = """
╔══════════════════════════════════════════════════════════════════════╗
║                    SPECTRA CAAS OPERATIONS CONSOLE                  ║
╚══════════════════════════════════════════════════════════════════════╝
"""


class AsyncRunner:
    @staticmethod
    def run_async(coroutine):
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(coroutine)

    @staticmethod
    def run_in_thread(fn: Callable[[], Any], callback: Optional[Callable[[Any], None]] = None, error_callback: Optional[Callable[[Exception], None]] = None):
        def _worker():
            try:
                result = fn()
                if callback:
                    callback(result)
            except Exception as exc:
                logger.exception("Background CAAS TUI task failed")
                if error_callback:
                    error_callback(exc)
        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        return thread


class StatusMessages(npyscreen.BoxTitle):
    _contained_widget = npyscreen.MultiLine

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.messages: list[str] = []
        self.max_messages = 200

    def add_message(self, message: str, level: str = "INFO"):
        ts = datetime.now(TZ).strftime("%H:%M:%S")
        entry = f"[{ts}] {level}: {message}"
        self.messages.insert(0, entry)
        if len(self.messages) > self.max_messages:
            self.messages.pop()
        self.values = self.messages
        self.display()


class CAASBaseForm(npyscreen.Form):
    @property
    def app(self) -> "SpectraCAASApp":
        return self.parentApp  # type: ignore[return-value]

    def get_severity_bar(self, score: float, width: int = 10) -> str:
        filled = int(max(0.0, min(1.0, score)) * width)
        return "[" + "#" * filled + "-" * (width - filled) + "]"

    def get_color_for_severity(self, score: float) -> str:
        if score >= 0.8: return "DANGER"
        if score >= 0.5: return "CAUTION"
        if score >= 0.3: return "IMPORTANT"
        return "SAFE"


class CAASDashboardForm(CAASBaseForm):
    def create(self):
        self.name = "CAAS Dashboard"
        self.add(npyscreen.FixedText, value=TITLE)
        self.add(npyscreen.FixedText, value="Semantic Discovery / Canonical Archive / Queue Intelligence")
        self.add(npyscreen.FixedText, value="")

        self.channel_profiles = self.add(npyscreen.TitleFixedText, name="Channel Profiles:", value="0")
        self.pending_queue = self.add(npyscreen.TitleFixedText, name="Queue Pending:", value="0")
        self.processing_queue = self.add(npyscreen.TitleFixedText, name="Queue Processing:", value="0")
        self.completed_queue = self.add(npyscreen.TitleFixedText, name="Queue Completed:", value="0")
        self.failed_queue = self.add(npyscreen.TitleFixedText, name="Queue Failed:", value="0")
        self.message_profiles = self.add(npyscreen.TitleFixedText, name="Message Profiles:", value="0")
        self.actor_entities = self.add(npyscreen.TitleFixedText, name="Actor Entities:", value="0")
        self.alerts = self.add(npyscreen.TitleFixedText, name="Active Alerts:", value="0")
        self.add(npyscreen.FixedText, value="")

        self.top_channels = self.add(npyscreen.Pager, name="High-Signal Channels (CaaS Triage)", height=8)
        self.add(npyscreen.FixedText, value="")
        self.add(npyscreen.ButtonPress, name="Update Metrics", when_pressed_function=self.refresh_stats)
        self.add(npyscreen.ButtonPress, name="Return to Command Center", when_pressed_function=lambda: self.app.switchForm("MAIN"))
        self.refresh_stats()

    def refresh_stats(self):
        try:
            db = self.app.get_db()
            ensure_schema(db)
            
            pending = self._scalar(db, "SELECT COUNT(*) FROM caas_profile_queue WHERE status = 'pending'")
            failed = self._scalar(db, "SELECT COUNT(*) FROM caas_profile_queue WHERE status = 'failed'")
            alert_count = self._scalar(db, "SELECT COUNT(*) FROM caas_alert")
            
            self.channel_profiles.value = str(self._scalar(db, "SELECT COUNT(*) FROM caas_channel_profile"))
            self.pending_queue.value = str(pending)
            self.pending_queue.label_color = "CAUTION" if pending > 0 else "SAFE"
            
            self.processing_queue.value = str(self._scalar(db, "SELECT COUNT(*) FROM caas_profile_queue WHERE status = 'processing'"))
            self.completed_queue.value = str(self._scalar(db, "SELECT COUNT(*) FROM caas_profile_queue WHERE status = 'completed'"))
            
            self.failed_queue.value = str(failed)
            self.failed_queue.label_color = "DANGER" if failed > 0 else "SAFE"
            
            self.message_profiles.value = str(self._scalar(db, "SELECT COUNT(*) FROM caas_message_profile"))
            self.actor_entities.value = str(self._scalar(db, "SELECT COUNT(*) FROM actor_entity"))
            
            self.alerts.value = str(alert_count)
            self.alerts.label_color = self.get_color_for_severity(0.9 if alert_count > 10 else 0.4 if alert_count > 0 else 0.0)
            rows = db.conn.execute(
                """
                SELECT COALESCE(title, channel_link, CAST(channel_id AS TEXT)),
                       caas_likelihood,
                       critical_alert_score
                FROM caas_channel_profile
                ORDER BY critical_alert_score DESC, caas_likelihood DESC
                LIMIT 10
                """
            ).fetchall()
            if rows:
                self.top_channels.values = [
                    f"{name} | CAAS={caas:.2f} | ALERT={alert:.2f}" for name, caas, alert in rows
                ]
            else:
                self.top_channels.values = ["No channel triage data yet"]
            self.display()
        except Exception as exc:
            npyscreen.notify_confirm(f"Failed to refresh dashboard: {exc}", title="Dashboard Error")

    def _scalar(self, db: SpectraDB, sql: str) -> int:
        row = db.conn.execute(sql).fetchone()
        return int(row[0]) if row and row[0] is not None else 0


class CAASDiscoveryForm(CAASBaseForm):
    def create(self):
        self.name = "CAAS Discovery"
        self.add(npyscreen.FixedText, value=TITLE)
        self.seed = self.add(npyscreen.TitleText, name="Seed Entity:", value="")
        self.depth = self.add(npyscreen.TitleSlider, name="Depth:", out_of=3, value=1)
        self.messages = self.add(npyscreen.TitleSlider, name="Messages:", out_of=2000, step=100, value=1000)
        self.triage_sample = self.add(npyscreen.TitleSlider, name="Triage Sample:", out_of=200, step=10, value=100)
        self.add(npyscreen.ButtonPress, name="Run CAAS Discovery", when_pressed_function=self.start_discovery)
        self.results = self.add(npyscreen.Pager, name="Discovery Results", height=12)
        self.status = self.add(StatusMessages, name="Status", max_height=6)
        self.add(npyscreen.ButtonPress, name="Return to Command Center", when_pressed_function=lambda: self.app.switchForm("MAIN"))
        self.status.add_message("Enter a seed channel and start semantic discovery.")

    def start_discovery(self):
        seed = self.seed.value.strip()
        if not seed:
            self.status.add_message("Seed entity is required.", "ERROR")
            return
        depth = int(self.depth.value)
        messages = int(self.messages.value)
        triage_sample = int(self.triage_sample.value)
        self.status.add_message(f"Starting CAAS discovery from {seed} depth={depth} messages={messages}")

        def _job():
            return AsyncRunner.run_async(
                discover_with_caas(
                    config_path=self.app.config_path,
                    db_path=self.app.db_path,
                    data_dir=self.app.data_dir,
                    seed=seed,
                    depth=depth,
                    max_messages=messages,
                    triage_sample=triage_sample,
                )
            )

        def _done(result: dict[str, Any]):
            lines = [
                f"Seed: {result.get('seed')}",
                f"Discovered Count: {result.get('discovered_count')}",
                "",
                f"Seed Triage: {result.get('seed_triage')}",
                "",
                "High Interest:",
            ]
            for row in result.get("high_interest", [])[:20]:
                lines.append(
                    f"- {row['entity']} | CAAS={row['caas_likelihood']:.2f} | ALERT={row['critical_alert_score']:.2f} | {', '.join(row.get('categories', []))}"
                )
            if len(lines) == 6:
                lines.append("No high-interest channels identified yet")
            self.results.values = lines
            self.results.display()
            self.status.add_message(f"Discovery complete. Found {result.get('discovered_count', 0)} entities.")

        def _error(exc: Exception):
            self.status.add_message(f"Discovery failed: {exc}", "ERROR")

        AsyncRunner.run_in_thread(_job, callback=_done, error_callback=_error)


class CAASArchiveForm(CAASBaseForm):
    def create(self):
        self.name = "Canonical Archive"
        self.add(npyscreen.FixedText, value=TITLE)
        self.entity = self.add(npyscreen.TitleText, name="Entity:", value="")
        self.auto = self.add(npyscreen.Checkbox, name="Auto-select account", value=True)
        self.download_media = self.add(npyscreen.Checkbox, name="Download Media", value=True)
        self.download_avatars = self.add(npyscreen.Checkbox, name="Download Avatars", value=False)
        self.archive_topics = self.add(npyscreen.Checkbox, name="Archive Topics", value=True)
        self.add(npyscreen.ButtonPress, name="Start Canonical Archive", when_pressed_function=self.start_archive)
        self.status = self.add(StatusMessages, name="Status", max_height=8)
        self.add(npyscreen.ButtonPress, name="Return to Command Center", when_pressed_function=lambda: self.app.switchForm("MAIN"))
        self.status.add_message("Canonical archive will enqueue CAAS profiling candidates automatically.")

    def start_archive(self):
        entity = self.entity.value.strip()
        if not entity:
            self.status.add_message("Entity is required.", "ERROR")
            return
        cfg = Config(Path(self.app.config_path))
        cfg.data["entity"] = entity
        cfg.data["db_path"] = self.app.db_path
        cfg.data["download_media"] = bool(self.download_media.value)
        cfg.data["download_avatars"] = bool(self.download_avatars.value)
        cfg.data["archive_topics"] = bool(self.archive_topics.value)
        account = cfg.auto_select_account() if self.auto.value else None
        self.status.add_message(f"Starting canonical archive for {entity}")

        def _job():
            return AsyncRunner.run_async(runner_canonical(cfg, account))

        def _done(_result: Any):
            self.status.add_message(f"Canonical archive complete for {entity}")

        def _error(exc: Exception):
            self.status.add_message(f"Canonical archive failed: {exc}", "ERROR")

        AsyncRunner.run_in_thread(_job, callback=_done, error_callback=_error)


class CAASQueueForm(CAASBaseForm):
    def create(self):
        self.name = "Queue Processor"
        self.add(npyscreen.FixedText, value=TITLE)
        self.batch_size = self.add(npyscreen.TitleSlider, name="Batch Size:", out_of=1000, step=50, value=500)
        self.loop_until_empty = self.add(npyscreen.Checkbox, name="Drain until empty", value=True)
        self.add(npyscreen.ButtonPress, name="Process Queue", when_pressed_function=self.start_processing)
        self.queue_status = self.add(npyscreen.Pager, name="Queue Status", height=10)
        self.status = self.add(StatusMessages, name="Status", max_height=6)
        self.add(npyscreen.ButtonPress, name="Refresh Queue Status", when_pressed_function=self.refresh_status)
        self.add(npyscreen.ButtonPress, name="Return to Command Center", when_pressed_function=lambda: self.app.switchForm("MAIN"))
        self.refresh_status()

    def refresh_status(self):
        try:
            db = self.app.get_db()
            ensure_schema(db)
            rows = db.conn.execute(
                "SELECT status, COUNT(*) FROM caas_profile_queue GROUP BY status ORDER BY status"
            ).fetchall()
            if rows:
                self.queue_status.values = [f"{status}: {count}" for status, count in rows]
            else:
                self.queue_status.values = ["Queue is empty"]
            self.queue_status.display()
        except Exception as exc:
            self.queue_status.values = [f"Queue refresh failed: {exc}"]
            self.queue_status.display()

    def start_processing(self):
        batch_size = int(self.batch_size.value)
        once = not bool(self.loop_until_empty.value)
        self.status.add_message(f"Starting queue worker batch_size={batch_size} once={once}")

        def _job():
            return process_queue(db_path=self.app.db_path, batch_size=batch_size, once=once)

        def _done(processed: int):
            self.status.add_message(f"Queue worker finished. Processed {processed} items.")
            self.refresh_status()

        def _error(exc: Exception):
            self.status.add_message(f"Queue worker failed: {exc}", "ERROR")
            self.refresh_status()

        AsyncRunner.run_in_thread(_job, callback=_done, error_callback=_error)


class CAASSignalsForm(CAASBaseForm):
    def create(self):
        self.name = "Signals & Intelligence"
        self.add(npyscreen.FixedText, value=TITLE)
        
        self.actor_search = self.add(npyscreen.TitleText, name="Actor Search Filter:", value="")
        self.view = self.add(npyscreen.TitleSelectOne, name="Intelligence View:", 
                             values=["1. High-Signal Channels", 
                                     "2. Known Actors", 
                                     "3. Actor Dossiers (In-Depth)", 
                                     "4. Global Market Intelligence", 
                                     "5. Active Alerts", 
                                     "6. Processing Failures"], 
                             max_height=7, value=[0])
        
        self.refresh_button = self.add(npyscreen.ButtonPress, name="Run Analysis / Refresh", when_pressed_function=self.refresh_view)
        self.output = self.add(npyscreen.Pager, name="Intelligence Output", height=14)
        self.add(npyscreen.ButtonPress, name="Return to Command Center", when_pressed_function=lambda: self.app.switchForm("MAIN"))
        self.refresh_view()

    def refresh_view(self):
        try:
            db = self.app.get_db()
            ensure_schema(db)
            choice = self.view.value[0] if self.view.value else 0
            search = self.actor_search.value.strip()
            
            if choice == 0:
                rows = db.conn.execute(
                    """
                    SELECT COALESCE(title, channel_link, CAST(channel_id AS TEXT)),
                           caas_likelihood,
                           bot_shop_likelihood,
                           critical_alert_score
                    FROM caas_channel_profile
                    ORDER BY critical_alert_score DESC, caas_likelihood DESC
                    LIMIT 25
                    """
                ).fetchall()
                self.output.values = [
                    f"{name} | CAAS={caas:.2f} | BOT={bot:.2f} | ALERT={alert:.2f}" for name, caas, bot, alert in rows
                ] or ["No channel profiles"]
            elif choice == 1:
                if search:
                    rows = db.conn.execute(
                        "SELECT canonical_handle, entity_type, bot_likelihood, last_seen FROM actor_entity WHERE canonical_handle LIKE ? ORDER BY last_seen DESC LIMIT 25",
                        (f"%{search}%",)
                    ).fetchall()
                else:
                    rows = db.conn.execute(
                        "SELECT canonical_handle, entity_type, bot_likelihood, last_seen FROM actor_entity ORDER BY last_seen DESC LIMIT 25"
                    ).fetchall()
                self.output.values = [
                    f"{handle} | {etype} | bot={bot:.2f} | last_seen={last_seen}" for handle, etype, bot, last_seen in rows
                ] or ["No actors matching search criteria"]
            elif choice == 2:
                from tgarchive.osint.caas.aggregator import ActorDossierAggregator
                aggregator = ActorDossierAggregator(db)
                dossiers = aggregator.get_top_actors(limit=50 if search else 15)
                if search:
                    dossiers = [d for d in dossiers if search.lower() in d["actor_handle"].lower()]
                
                lines = []
                for d in dossiers:
                    services_str = ", ".join(f"{k}({v})" for k, v in d["top_services"][:3])
                    prices_str = f"{len(d['price_history'])} prices found"
                    sev_bar = self.get_severity_bar(d["caas_severity"])
                    lines.append(f"@{d['actor_handle']} {sev_bar} Sev: {d['caas_severity']:.2f}")
                    lines.append(f"  Services: {services_str or 'None'}")
                    lines.append(f"  Pricing: {prices_str}")
                    lines.append("")
                self.output.values = lines or ["No actor dossiers available matching criteria."]
            elif choice == 3:
                from tgarchive.osint.caas.market_intel import MarketIntelligenceEngine
                engine = MarketIntelligenceEngine(db)
                snapshot = engine.get_market_snapshot()
                shifts = engine.detect_market_shifts()
                
                # PRICE HEATMAP (Distribution across low/mid/high buckets)
                cursor = db.conn.execute("SELECT raw_json FROM caas_message_profile")
                all_prices = []
                for (raw_json_str,) in cursor:
                    try:
                        raw_data = json.loads(raw_json_str or "{}")
                        for p in raw_data.get("prices", []):
                            amount = p.get("amount_min") or p.get("amount_max")
                            if amount:
                                all_prices.append(float(amount))
                    except: continue
                
                lines = [f"GLOBAL MARKET SNAPSHOT (Total Profiles: {snapshot['total_profiles']})", ""]
                
                if all_prices:
                    low = [p for p in all_prices if p < 100]
                    mid = [p for p in all_prices if 100 <= p <= 1000]
                    high = [p for p in all_prices if p > 1000]
                    total = len(all_prices)
                    heatmap = f"PRICE HEATMAP: Low (<$100): {len(low)/total*100:.1f}% | Mid ($100-$1k): {len(mid)/total*100:.1f}% | High (>$1k): {len(high)/total*100:.1f}%"
                    lines.append(heatmap)
                    lines.append("")

                lines.append(f"SUMMARY: {snapshot['summary']}")
                lines.append("-" * 40)
                lines.append(f"{'CATEGORY':<20} | {'AVG PRICE':<10} | {'GMV PROXY':<10} | {'VOLUME'}")
                for s in snapshot["service_rankings"][:10]:
                    lines.append(f"{s['category']:<20} | {s['avg_price']:<10} | {s['estimated_market_value']:<10} | {s['mentions']}")
                
                if shifts:
                    lines.append("")
                    lines.append("MARKET SHIFT ALERTS:")
                    for shift in shifts:
                        lines.append(f"!! [{shift['severity'].upper()}] {shift['description']}")
                
                self.output.values = lines or ["Insufficient data for market intelligence analysis."]
            elif choice == 4:
                rows = db.conn.execute(
                    "SELECT severity, alert_type, score, summary, created_at FROM caas_alert ORDER BY created_at DESC LIMIT 25"
                ).fetchall()
                self.output.values = [
                    f"[{severity.upper()}] {alert_type} | score={score:.2f} | {summary} | {created_at}" for severity, alert_type, score, summary, created_at in rows
                ] or ["No alerts"]
            else:
                rows = db.conn.execute(
                    "SELECT channel_id, message_id, error FROM caas_profile_queue WHERE status = 'failed' ORDER BY id DESC LIMIT 25"
                ).fetchall()
                self.output.values = [
                    f"channel={channel_id} msg={message_id} | {error}" for channel_id, message_id, error in rows
                ] or ["No failed queue items"]
            self.output.display()
        except Exception as exc:
            self.output.values = [f"Failed to refresh view: {exc}"]
            self.output.display()


class CAASMainMenuForm(CAASBaseForm):
    def create(self):
        self.name = "SPECTRA CAAS Console"
        self.add(npyscreen.FixedText, value=TITLE)
        self.add(npyscreen.FixedText, value="1. Dashboard")
        self.add(npyscreen.ButtonPress, name="1. Dashboard", when_pressed_function=lambda: self.app.switchForm("CAAS_DASHBOARD"))
        self.add(npyscreen.ButtonPress, name="2. CAAS Discovery", when_pressed_function=lambda: self.app.switchForm("CAAS_DISCOVERY"))
        self.add(npyscreen.ButtonPress, name="3. Canonical Archive", when_pressed_function=lambda: self.app.switchForm("CAAS_ARCHIVE"))
        self.add(npyscreen.ButtonPress, name="4. Process Queue", when_pressed_function=lambda: self.app.switchForm("CAAS_QUEUE"))
        self.add(npyscreen.ButtonPress, name="5. Signals & Actors", when_pressed_function=lambda: self.app.switchForm("CAAS_SIGNALS"))
        self.add(npyscreen.ButtonPress, name="6. Refresh DB Handle", when_pressed_function=self.refresh_db)
        self.add(npyscreen.ButtonPress, name="7. Exit", when_pressed_function=self.exit_app)
        self.status = self.add(npyscreen.TitleFixedText, name="Status:", value="Ready")

    def refresh_db(self):
        self.app.reset_db()
        self.status.value = f"DB handle refreshed at {datetime.now(TZ).strftime('%H:%M:%S')}"
        self.status.display()

    def exit_app(self):
        self.app.setNextForm(None)
        self.app.switchFormNow()


class SpectraCAASApp(npyscreen.NPSAppManaged):
    def __init__(self, config_path: str, db_path: str, data_dir: str):
        super().__init__()
        self.config_path = config_path
        self.db_path = db_path
        self.data_dir = data_dir
        self._db: Optional[SpectraDB] = None

    def onStart(self):
        self.addForm("MAIN", CAASMainMenuForm, name="SPECTRA CAAS Console")
        self.addForm("CAAS_DASHBOARD", CAASDashboardForm, name="CAAS Dashboard")
        self.addForm("CAAS_DISCOVERY", CAASDiscoveryForm, name="CAAS Discovery")
        self.addForm("CAAS_ARCHIVE", CAASArchiveForm, name="Canonical Archive")
        self.addForm("CAAS_QUEUE", CAASQueueForm, name="Queue Processor")
        self.addForm("CAAS_SIGNALS", CAASSignalsForm, name="Signals & Actors")

    def get_db(self) -> SpectraDB:
        if self._db is None:
            self._db = SpectraDB(Path(self.db_path))
            ensure_schema(self._db)
        return self._db

    def reset_db(self):
        if self._db is not None:
            try:
                self._db.conn.close()
            except Exception:
                pass
        self._db = None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SPECTRA CAAS TUI")
    parser.add_argument("--config", default="spectra_config.json")
    parser.add_argument("--db", default="spectra.db")
    parser.add_argument("--data-dir", default="spectra_data")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        app = SpectraCAASApp(config_path=args.config, db_path=args.db, data_dir=args.data_dir)
        app.run()
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        logger.exception("CAAS TUI failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
