"""
Scheduler Service for SPECTRA
=============================

This module contains the SchedulerDaemon class for managing scheduled tasks.
"""

import time
import threading
import json
from croniter import croniter
from datetime import datetime
import pytz
from http.server import HTTPServer, BaseHTTPRequestHandler

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
        while not self._stop_event.is_set():
            now = datetime.now(self.timezone)
            for job in self.jobs:
                iter = croniter(job['schedule'], now)
                if iter.get_prev(datetime) == now.replace(second=0, microsecond=0):
                    # TODO: Execute the job
                    print(f"Executing job: {job['name']}")
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
