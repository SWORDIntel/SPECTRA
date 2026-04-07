from __future__ import annotations

import argparse
import sys

from tgarchive.osint.caas.queue_worker import process_queue


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Standalone CAAS queue worker")
    parser.add_argument("command", choices=["process-queue"], help="Command to run")
    parser.add_argument("--db", default="spectra.db", help="Path to SQLite database")
    parser.add_argument("--batch-size", type=int, default=500, help="Queue claim size")
    parser.add_argument("--loop", action="store_true", help="Keep draining until the queue is empty")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "process-queue":
        processed = process_queue(db_path=args.db, batch_size=args.batch_size, once=not args.loop)
        print(f"Processed {processed} queue items")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
