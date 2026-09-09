#!/usr/bin/env python3
"""Compatibility entry point for evidence-calibrated corpus analysis."""

import argparse

from corpus_analysis import DEFAULT_DB, DEFAULT_RELATED, DEFAULT_SUBJECT, analyze


def main():
    parser = argparse.ArgumentParser(description="Run evidence-calibrated corpus analysis")
    parser.add_argument("subject_id", type=int, nargs="?", default=DEFAULT_SUBJECT)
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--related-id", type=int, action="append", default=[])
    parser.add_argument("--no-persist", action="store_true")
    args = parser.parse_args()
    related = tuple(args.related_id) if args.related_id else DEFAULT_RELATED
    result = analyze(args.db, args.subject_id, related, persist=not args.no_persist)
    state = "preview" if args.no_persist else ("unchanged" if result["unchanged"] else "stored")
    print(
        f"[corpus-analysis] subject={result['subject_id']} state={state} "
        f"messages={result['message_count']} new={result.get('new_message_count', 0)} "
        f"observations={result['observation_count']} review_priority={result['review_priority']:.2f}"
    )
    print(f"[corpus-analysis] assessment={result['assessment']}")


if __name__ == "__main__":
    main()
