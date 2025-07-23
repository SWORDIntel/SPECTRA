"""
Scheduler Service for SPECTRA
=============================

This module contains the SchedulerDaemon class for managing scheduled tasks.
"""

import time
import threading
import json
import asyncio
from croniter import croniter
from datetime import datetime
import pytz
from http.server import HTTPServer, BaseHTTPRequestHandler
from .forwarding import AttachmentForwarder
from .db import SpectraDB
from .notifications import NotificationManager

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'OK')

class SchedulerDaemon:
    """
    A daemon for scheduling and running tasks in the background.
    """
    def __init__(self, config_path, state_path):
        self.config_path = config_path
        self.state_path = state_path
        self.config = self.load_config()
        self.timezone = pytz.timezone(self.config.get('scheduler', {}).get('timezone', 'UTC'))
        self.jobs = self.load_jobs()
        self._stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.health_check_server = None
        self.notification_manager = NotificationManager(self.config.get("notifications", {}))

    def load_config(self):
        """
        Loads the main configuration file.
        """
        try:
            with open(self.config_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def load_jobs(self):
        """
        Loads jobs from the state file.
        """
        try:
            with open(self.state_path, 'r') as f:
                state = json.load(f)
                return state.get('jobs', [])
        except FileNotFoundError:
            return []

    def save_jobs(self):
        """
        Saves jobs to the state file.
        """
        with open(self.state_path, 'w') as f:
            json.dump({'jobs': self.jobs}, f, indent=2)

    def run(self):
        """
        The main loop for the scheduler daemon.
        """
        self.start_health_check()
        db = SpectraDB(self.config.get("db", {}).get("path", "spectra.db"))

        while not self._stop_event.is_set():
            now = datetime.now(self.timezone)

            # Execute generic jobs from state file
            for job in self.jobs:
                iter = croniter(job['schedule'], now)
                if iter.get_prev(datetime) == now.replace(second=0, microsecond=0):
                    # This is a placeholder for executing generic commands.
                    # For security, this should be carefully designed.
                    print(f"Executing generic job: {job['name']}")

            # Execute channel forwarding jobs from DB
            schedules = db.get_channel_forward_schedules()
            for schedule_id, channel_id, destination, schedule, last_message_id in schedules:
                iter = croniter(schedule, now)
                if iter.get_prev(datetime) == now.replace(second=0, microsecond=0):
                    self.notification_manager.send(f"Starting channel forward for channel {channel_id}")
                    print(f"Executing channel forward for channel {channel_id}")
                    try:
                        new_last_message_id = asyncio.run(scheduled_channel_forward(
                            self.config_path,
                            db.db_path,
                            channel_id,
                            destination,
                            last_message_id
                        ))
                        if new_last_message_id:
                            db.update_channel_forward_schedule_checkpoint(schedule_id, new_last_message_id)
                        self.notification_manager.send(f"Successfully finished channel forward for channel {channel_id}")
                    except Exception as e:
                        print(f"Error executing channel forward for channel {channel_id}: {e}")
                        self.notification_manager.send(f"Error executing channel forward for channel {channel_id}: {e}")


            time.sleep(60)  # Check every minute
        self.stop_health_check()

    def start_health_check(self):
        """
        Starts the health check server in a new thread.
        """
        host = self.config.get('scheduler', {}).get('health_check_host', 'localhost')
        port = self.config.get('scheduler', {}).get('health_check_port', 8080)
        self.health_check_server = HTTPServer((host, port), HealthCheckHandler)
        self.health_check_thread = threading.Thread(target=self.health_check_server.serve_forever)
        self.health_check_thread.daemon = True
        self.health_check_thread.start()

    def stop_health_check(self):
        """
        Stops the health check server.
        """
        if self.health_check_server:
            self.health_check_server.shutdown()
            self.health_check_server.server_close()

    def start(self):
        """
        Starts the scheduler daemon in a new thread.
        """
        self.thread.start()

    def stop(self):
        """
        Stops the scheduler daemon.
        """
        self._stop_event.set()
        self.thread.join()

async def scheduled_channel_forward(config_path, db_path, schedule_id, channel_id, destination, last_message_id):
    """
    Forwards messages from a channel to a destination, starting after the last_message_id.
    """
    with open(config_path, 'r') as f:
        config = json.load(f)

    db = SpectraDB(db_path)
    forwarder = AttachmentForwarder(config=config, db=db)

    started_at = datetime.now().isoformat()
    status = "success"
    messages_forwarded = 0
    files_forwarded = 0
    bytes_forwarded = 0

    try:
        new_last_message_id, stats = await forwarder.forward_messages(
            origin_id=channel_id,
            destination_id=destination,
            start_message_id=last_message_id
        )
        messages_forwarded = stats.get("messages_forwarded", 0)
        files_forwarded = stats.get("files_forwarded", 0)
        bytes_forwarded = stats.get("bytes_forwarded", 0)
        return new_last_message_id
    except Exception as e:
        status = f"error: {e}"
        raise
    finally:
        finished_at = datetime.now().isoformat()
        db.add_channel_forward_stats(schedule_id, messages_forwarded, files_forwarded, bytes_forwarded, started_at, finished_at, status)
        await forwarder.close()
