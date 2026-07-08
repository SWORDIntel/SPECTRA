import asyncio
import logging
from pathlib import Path

from telethon import TelegramClient, functions, types
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.errors import UserAlreadyParticipantError, InviteHashExpiredError

from tgarchive.db import SpectraDB
from tgarchive.osint.caas.schema import ensure_schema
from tgarchive.core.sync_canonical import CanonicalDBHandler, archive_messages

logger = logging.getLogger(__name__)

async def join_chat(client: TelegramClient, link: str) -> types.TypeChat | None:
    """Join a chat given an invite hash or username/public channel."""
    try:
        if link.startswith("joinchat/") or link.startswith("+"):
            hash_str = link.replace("joinchat/", "").replace("+", "")
            logger.info("Attempting to join via invite hash: %s", hash_str)
            updates = await client(ImportChatInviteRequest(hash_str))
            return updates.chats[0] if updates.chats else None
        else:
            logger.info("Attempting to join via username/ID: %s", link)
            entity = await client.get_entity(link)
            await client(JoinChannelRequest(entity))
            return entity
    except UserAlreadyParticipantError:
        logger.info("Already a participant of %s", link)
        return await client.get_entity(link)
    except InviteHashExpiredError:
        logger.warning("Invite link expired: %s", link)
        return None
    except Exception as e:
        logger.error("Failed to join %s: %s", link, e)
        return None

async def spider_loop(
    client_pool: list[TelegramClient],
    db_path: Path,
    limit_per_chat: int = 1000,
):
    """Infinitely pulls from caas_invite_list and archives new channels to spider out."""
    db = SpectraDB(db_path)
    ensure_schema(db)
    
    from tgarchive.osint.caas.discovery_fingerprint import ChannelFingerprintEngine
    from telethon.errors import FloodWaitError
    engine = ChannelFingerprintEngine()
    
    logger.info("Starting CAAS spidering loop with %d sessions...", len(client_pool))
    
    current_client_idx = 0
    
    while True:
        client = client_pool[current_client_idx]
        
        # Get unvisited invites
        rows = db.conn.execute(
            """
            SELECT id, source_invite
            FROM caas_invite_list
            WHERE updated_at = created_at AND flagged = 0
            ORDER BY id ASC
            LIMIT 1
            """
        ).fetchall()
        
        if not rows:
            logger.info("No new invites to spider. Waiting...")
            await asyncio.sleep(10)
            continue
            
        invite_id, source_invite = rows[0]
        
        # Mark as visited (updated_at != created_at)
        db.conn.execute("UPDATE caas_invite_list SET updated_at = datetime('now') WHERE id = ?", (invite_id,))
        db.conn.commit()
        
        # Parse link
        link = source_invite.replace("https://t.me/", "").strip()
        logger.info("Spidering out to new chat: %s", link)
        
        try:
            chat = await join_chat(client, link)
            if not chat:
                continue
                
            # Evade Gatekeepers (Anti-Bot Challenges)
            from tgarchive.osint.caas.gatekeeper import solve_gatekeeper_challenge
            # Give the bot 5 seconds to solve any immediate captchas
            await solve_gatekeeper_challenge(client, chat.id, timeout=5)
                
            # Dynamic Triage: Sample recent messages before committing to full archive
            logger.info("Triaging %s to determine relevance...", chat.title)
            sample_msgs = []
            async for msg in client.iter_messages(chat, limit=50):
                text = getattr(msg, "text", None) or getattr(msg, "message", None)
                if text:
                    sample_msgs.append({
                        "text": text,
                        "sender_username": getattr(getattr(msg, "sender", None), "username", None)
                    })
            
            triage_result = engine.score_batch(sample_msgs)
            
            # If it doesn't meet minimum CAAS or critical alert threshold, abandon it.
            if triage_result.get("caas_likelihood", 0.0) < 0.2 and triage_result.get("critical_alert_score", 0.0) < 0.1:
                logger.info("Chat %s failed triage (caas_likelihood=%.2f). Skipping full archive and leaving.", chat.title, triage_result.get("caas_likelihood", 0.0))
                from telethon.tl.functions.channels import LeaveChannelRequest
                try:
                    await client(LeaveChannelRequest(chat))
                except Exception:
                    pass
                continue
            
            logger.info("Chat %s passed triage. Proceeding with full archive.", chat.title)
                
            # Archive it so queue worker gets messages to profile!
            with CanonicalDBHandler(db_path) as db_handler:
                try:
                    logger.info("Archiving messages from %s to extract POIs and new invites...", chat.title)
                    await archive_messages(client, chat, db_handler, limit=limit_per_chat)
                except Exception as e:
                    logger.error("Failed to archive chat %s: %s", chat.title, e)

        except FloodWaitError as e:
            logger.warning("Rate limit hit on session %d! Sleeping for %s seconds and rotating session...", current_client_idx, e.seconds)
            current_client_idx = (current_client_idx + 1) % len(client_pool)
            logger.info("Rotated to session %d", current_client_idx)
            # Revert the visit so the new session can try it
            db.conn.execute("UPDATE caas_invite_list SET updated_at = created_at WHERE id = ?", (invite_id,))
            db.conn.commit()
            await asyncio.sleep(min(e.seconds, 300)) # Cap rotation wait
        except Exception as e:
            logger.error("Unexpected error in spider loop: %s", e)

