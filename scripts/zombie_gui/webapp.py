#!/usr/bin/env python3

"""Root documentation launcher for the SPECTRA web UI."""

from __future__ import annotations

import argparse
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def wait_for_docs(host: str, port: int, timeout: float = 15.0) -> bool:
    url = f"http://{host}:{port}/docs"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1):
                return True
        except urllib.error.URLError:
            time.sleep(0.2)
    return False


def launch_docs_server(host: str = "127.0.0.1", port: int = 5000, open_browser: bool = True) -> int:
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "spectra_app.spectra_gui_launcher",
            "--host",
            host,
            "--port",
            str(port),
        ],
        cwd=str(ROOT),
    )
    docs_url = f"http://{host}:{port}/docs"

    def shutdown(_signum, _frame):
        if server.poll() is None:
            server.terminate()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        if open_browser and wait_for_docs(host, port):
            webbrowser.open_new_tab(docs_url)
        return server.wait()
    except KeyboardInterrupt:
        shutdown(signal.SIGINT, None)
        return 130


def main() -> int:
    parser = argparse.ArgumentParser(description="SPECTRA documentation launcher")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser tab")
    args = parser.parse_args()
    return launch_docs_server(args.host, args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    raise SystemExit(main())
