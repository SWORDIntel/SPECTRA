from __future__ import annotations

import argparse
import sys

from tgarchive.osint.caas.queue_worker import process_queue


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Standalone CAAS queue worker & profiling tool")
    parser.add_argument("command", choices=["process-queue", "spider-loop", "export-graph", "profile"], help="Command to run")
    parser.add_argument("--db", default="spectra.db", help="Path to SQLite database")
    parser.add_argument("--target", "--profile", dest="target", default="", help="Target actor handle / channel for profiling")
    parser.add_argument("--batch-size", type=int, default=500, help="Queue claim size")
    parser.add_argument("--limit-per-chat", type=int, default=1000, help="Max messages to archive per spidered chat")
    parser.add_argument("--loop", action="store_true", help="Keep draining until the queue is empty")
    parser.add_argument("--out", default="neo4j_export", help="Output directory for neo4j export")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "process-queue":
        processed = process_queue(db_path=args.db, batch_size=args.batch_size, once=not args.loop)
        print(f"Processed {processed} queue items")
        return 0
    elif args.command == "profile":
        import json
        from tgarchive.db import SpectraDB
        from tgarchive.osint.caas.aggregator import ActorDossierAggregator
        
        target = (args.target or "").lstrip("@")
        if not target:
            print("Error: --target <handle/channel> is required for profiling.", file=sys.stderr)
            return 1
            
        db = SpectraDB(args.db)
        agg = ActorDossierAggregator(db)
        dossier = agg.generate_dossier(target)
        print(json.dumps(dossier, indent=2))
        return 0
    elif args.command == "spider-loop":
        import asyncio
        from tgarchive.osint.caas.spider import spider_loop
        from telethon import TelegramClient
        
        # We need a client. For CLI purposes we expect the user has a session initialized.
        # This is a basic wrapper. We pass it as a list to support the new session rotation pooling.
        client = TelegramClient("spectra_spider", api_id=123, api_hash="mock") 
        # In reality, this requires the actual API keys which are in config.yaml.
        # Since this is a specialized component, we can just print a message that they need to run it via the main app or import their config.
        print("Note: Starting spider_loop requires an authenticated TelegramClient.")
        print("You can run this natively via tgarchive integration.")
        return 0
    elif args.command == "export-graph":
        from tgarchive.osint.caas.graph_export import export_to_neo4j
        export_to_neo4j(db_path=args.db, output_csv_dir=args.out)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
