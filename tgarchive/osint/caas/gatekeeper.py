import asyncio
import logging
import re
import math
from telethon import TelegramClient, events
from telethon.tl.types import KeyboardButtonCallback
from telethon.tl.functions.messages import GetBotCallbackAnswerRequest

logger = logging.getLogger(__name__)

async def solve_gatekeeper_challenge(client: TelegramClient, chat_id: int, timeout: int = 15):
    """
    Listens for gatekeeper challenges after joining a chat and attempts to solve them.
    Supports inline callback buttons (like "Click here to verify") and simple math captchas.
    """
    logger.info(f"Listening for gatekeeper challenges in chat {chat_id}...")
    
    challenge_solved = asyncio.Event()

    @client.on(events.NewMessage(chats=chat_id, incoming=True))
    async def handler(event):
        msg = event.message
        
        # Check if it's a captcha bot or mentions verify/click/human
        text = (msg.text or "").lower()
        if any(kw in text for kw in ["verify", "human", "click", "captcha", "prove"]):
            logger.info(f"Potential gatekeeper challenge detected from {msg.sender_id}: {text}")
            
            # Check for inline keyboard buttons
            if msg.reply_markup and hasattr(msg.reply_markup, 'rows'):
                for row in msg.reply_markup.rows:
                    for button in row.buttons:
                        if isinstance(button, KeyboardButtonCallback):
                            logger.info(f"Clicking inline callback button: {button.text}")
                            try:
                                await client(GetBotCallbackAnswerRequest(
                                    peer=chat_id,
                                    msg_id=msg.id,
                                    data=button.data
                                ))
                                logger.info("Callback button clicked successfully.")
                                challenge_solved.set()
                                return
                            except Exception as e:
                                logger.error(f"Failed to click callback button: {e}")
                                
            # Check for math captcha in text (e.g. "What is 5 + 3?")
            math_match = re.search(r"what is\s+(\d+)\s*([\+\-\*])\s*(\d+)", text)
            if math_match:
                op1 = int(math_match.group(1))
                op = math_match.group(2)
                op2 = int(math_match.group(3))
                
                if op == "+":
                    ans = op1 + op2
                elif op == "-":
                    ans = op1 - op2
                elif op == "*":
                    ans = op1 * op2
                
                logger.info(f"Math captcha detected: {op1} {op} {op2}. Replying with {ans}")
                await msg.reply(str(ans))
                challenge_solved.set()
                return

    try:
        # Wait for a challenge and solve it, but don't hang if there isn't one
        await asyncio.wait_for(challenge_solved.wait(), timeout=timeout)
        logger.info("Gatekeeper challenge solved!")
    except asyncio.TimeoutError:
        logger.info("No gatekeeper challenge detected or timed out waiting.")
    finally:
        client.remove_event_handler(handler)

