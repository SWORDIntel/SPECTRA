from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from tgarchive.core.sync import logger
from tgarchive.core.config_models import Config
from tgarchive.db import SpectraDB
from tgarchive.osint.caas.discovery_fingerprint import ChannelFingerprintEngine
from tgarchive.osint.caas.schema import ensure_schema, upsert_channel_profile
from tgarchive.utils.discovery import SpectraCrawlerManager


async def _triage_entity(manager: SpectraCrawlerManager, db_path: Path, entity_ref: Any, sample_limit: int = 100) -> dict[str, Any] | None:
    client = manager.group_manager.active_client
    if client is None:
        return None

    try:
        entity = await client.get_entity(entity_ref)
    except Exception as exc:
        logger.warning("Failed to resolve entity %s for CAAS triage: %s", entity_ref, exc)
        return None

    engine = ChannelFingerprintEngine()
    sample_msgs: list[dict[str, Any]] = []
    try:
        async for message in client.iter_messages(entity, limit=sample_limit):
            text = getattr(message, "text", None) or getattr(message, "message", None)
            if not text:
                continue
            sample_msgs.append(
                {
                    "text": text,
                    "sender_username": getattr(getattr(message, "sender", None), "username", None),
                    "sender_id": getattr(message, "sender_id", None),
                }
            )
    except Exception as exc:
        logger.warning("Failed to sample messages for %s: %s", entity_ref, exc)
        return None

    result = engine.score_batch(sample_msgs)
    db = SpectraDB(db_path)
    ensure_schema(db)
    upsert_channel_profile(
        db,
        channel_id=getattr(entity, "id", None),
        channel_link=(f"@{entity.username}" if getattr(entity, "username", None) else None),
        title=getattr(entity, "title", None),
        triage_result=result,
    )
    return result


async def discover_with_caas(
    *,
    config_path: str | Path,
    db_path: str | Path,
    data_dir: str | Path,
    seed: str,
    depth: int = 1,
    max_messages: int = 1000,
    triage_sample: int = 100,
) -> dict[str, Any]:
    cfg = Config(Path(config_path))
    manager = SpectraCrawlerManager(config=cfg, data_dir=Path(data_dir), db_path=Path(db_path))

    if not await manager.initialize():
        raise RuntimeError("failed to initialize crawler manager")

    try:
        discovered = await manager.discover_from_seed(seed, depth=depth, max_messages=max_messages)
        seed_triage = await _triage_entity(manager, Path(db_path), seed, sample_limit=triage_sample)
        high_interest: list[dict[str, Any]] = []
        for entity_ref in list(discovered)[:25]:
            triage = await _triage_entity(manager, Path(db_path), entity_ref, sample_limit=min(50, triage_sample))
            if triage and (triage.get("critical_alert_score", 0.0) >= 0.50 or triage.get("caas_likelihood", 0.0) >= 0.60):
                high_interest.append({
                    "entity": entity_ref,
                    "caas_likelihood": triage.get("caas_likelihood", 0.0),
                    "critical_alert_score": triage.get("critical_alert_score", 0.0),
                    "categories": triage.get("criminal_categories", []),
                })

        return {
            "seed": seed,
            "discovered_count": len(discovered),
            "seed_triage": seed_triage,
            "high_interest": sorted(high_interest, key=lambda x: (x["critical_alert_score"], x["caas_likelihood"]), reverse=True),
        }
    finally:
        await manager.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CAAS-aware semantic discovery wrapper")
    parser.add_argument("--config", default="spectra_config.json")
    parser.add_argument("--db", default="spectra.db")
    parser.add_argument("--data-dir", default="spectra_data")
    parser.add_argument("--seed", required=True)
    parser.add_argument("--depth", type=int, default=1)
    parser.add_argument("--messages", type=int, default=1000)
    parser.add_argument("--triage-sample", type=int, default=100)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = asyncio.run(
            discover_with_caas(
                config_path=args.config,
                db_path=args.db,
                data_dir=args.data_dir,
                seed=args.seed,
                depth=args.depth,
                max_messages=args.messages,
                triage_sample=args.triage_sample,
            )
        )
        print(json.dumps(result, indent=2))
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        logger.exception("CAAS-aware discovery failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
