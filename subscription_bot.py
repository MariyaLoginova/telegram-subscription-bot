"""
A Telegram bot that checks whether a user is subscribed to a specific channel
before delivering a piece of material.  If the user is subscribed, the bot
responds by sending the requested material; otherwise it asks the user to
subscribe.  The bot uses python‑telegram‑bot's asynchronous API (v20+).  To
run this bot you need a Telegram bot token, the target channel or group ID
and optionally a file or message to send as the material.  These values can
be supplied via environment variables or a .env file.

Required environment variables
-----------------------------

```
TELEGRAM_BOT_TOKEN   # Bot token from BotFather
TARGET_CHAT_ID       # ID of the channel or group to check membership against
MATERIAL_TEXT        # (optional) Text to send when the user is subscribed
MATERIAL_FILE_PATH   # (optional) Path to a file to send when subscribed
CHANNEL_INVITE_LINK  # (optional) URL to invite users to subscribe
```

Only one of ``MATERIAL_TEXT`` or ``MATERIAL_FILE_PATH`` is required.  If
``MATERIAL_FILE_PATH`` points to a local file, it will be read and sent
using ``send_document``.  If ``MATERIAL_TEXT`` is provided, it will be sent
as a plain text message.  ``CHANNEL_INVITE_LINK`` should be a t.me link or
username of your channel to direct users who aren’t subscribed.

Example usage
-------------

Create a file ``.env`` alongside this script with the following contents:

```
TELEGRAM_BOT_TOKEN=123456:ABCDEF…
TARGET_CHAT_ID=-1001234567890
MATERIAL_TEXT=Thanks for subscribing! Here is your material: …
CHANNEL_INVITE_LINK=https://t.me/your_channel
```

Then install dependencies and run the bot:

```sh
pip install python-telegram-bot python-dotenv
python subscription_bot.py
```

The bot will respond to the ``/start`` command with a greeting and to the
``/get`` command by checking the user’s subscription status and sending the
material if appropriate.  If the user is not subscribed, a prompt will be
sent with your channel’s invite link.
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatMemberStatus, ParseMode
from telegram.ext import (Application, ApplicationBuilder, CommandHandler,
                          ContextTypes)


# Configure basic logging so that important information is printed to the
# console.  This is helpful for debugging and monitoring the bot’s
# behaviour.  You can adjust the log level to logging.INFO or DEBUG for
# more verbose output.
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)



def load_config() -> dict:
    """Load configuration from environment variables and return them as a dict.

    If a .env file exists in the current directory, python-dotenv will load
    variables from it into os.environ.  Required variables must be
    present; optional variables may be None.

    Returns
    -------
    dict
        A dictionary containing configuration values.
    """
    # Load variables from .env if present.  This call silently does nothing
    # if there is no .env file.
    load_dotenv()

    config = {
        "token": os.getenv("TELEGRAM_BOT_TOKEN"),
        "target_chat_id": os.getenv("TARGET_CHAT_ID"),
        "material_text": os.getenv("MATERIAL_TEXT"),
        "material_file_path": os.getenv("MATERIAL_FILE_PATH"),
        "channel_invite_link": os.getenv("CHANNEL_INVITE_LINK"),
    }

    if not config["token"]:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN must be set as an environment variable or in .env"
        )
    if not config["target_chat_id"]:
        raise RuntimeError(
            "TARGET_CHAT_ID must be set as an environment variable or in .env"
        )
    if not (config["material_text"] or config["material_file_path"]):
        raise RuntimeError(
            "Either MATERIAL_TEXT or MATERIAL_FILE_PATH must be set to deliver material"
        )

    # Convert target chat ID to int if it looks like an integer.  Telegram
    # channel IDs are often large negative numbers (e.g. -1001234567890).
    try:
        config["target_chat_id"] = int(config["target_chat_id"])
    except ValueError:
        # It may be a string like "@channel_username", which the API will
        # accept directly.
        pass

    # Normalize file path if provided
    file_path = config["material_file_path"]
    if file_path:
        config["material_file_path"] = Path(file_path).expanduser()

    return config


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a welcome message when the /start command is issued."""
    msg = (
        "Привет! Этот бот проверяет, подписаны ли вы на наш канал, прежде чем "
        "предоставить материалы. Используйте команду /get, чтобы запросить материал."
    )
    await update.message.reply_text(msg)


async def get_material(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check subscription and send the material if the user is subscribed."""
    user_id = update.effective_user.id
    config = context.application.bot_data.get("config")
    target_chat_id = config["target_chat_id"]
    material_text: Optional[str] = config.get("material_text")
    material_file_path: Optional[Path] = config.get("material_file_path")
    channel_invite_link: Optional[str] = config.get("channel_invite_link")

    try:
        # get_chat_member returns a ChatMember instance.  The status property
        # indicates the user’s relationship to the chat: member, administrator,
        # owner, left, banned, restricted, etc.
        chat_member = await context.bot.get_chat_member(target_chat_id, user_id)
        status = chat_member.status
        logger.debug(
            "User %s has status '%s' in chat %s",
            user_id,
            status,
            target_chat_id,
        )

        if status in [
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
            ChatMemberStatus.CREATOR if hasattr(ChatMemberStatus, "CREATOR") else None,
        ]:
            # The user is subscribed (member or admin or owner)
            if material_file_path and material_file_path.exists():
                # Send the file.  Open as binary and ensure closing after use.
                try:
                    with material_file_path.open("rb") as fh:
                        await context.bot.send_document(
                            chat_id=user_id,
                            document=fh,
                            filename=material_file_path.name,
                            caption=material_text or None,
                        )
                except Exception as e:
                    logger.exception("Failed to send document: %s", e)
                    await context.bot.send_message(
                        chat_id=user_id,
                        text="Произошла ошибка при отправке файла. Попробуйте позже.",
                    )
                return
            # Otherwise send text
            await context.bot.send_message(
                chat_id=user_id,
                text=material_text or "Спасибо за подписку! Вот ваш материал.",
            )
        else:
            # Not subscribed: inform the user.  Optionally provide invite link.
            reply = (
                "Чтобы получить материал, пожалуйста, подпишитесь на канал."
            )
            if channel_invite_link:
                reply += f"\n{channel_invite_link}"
            await context.bot.send_message(
                chat_id=user_id,
                text=reply,
                parse_mode=ParseMode.HTML,
            )
    except Exception as exc:
        # If get_chat_member raises an error (user not found), treat as not subscribed.
        logger.warning("Error while checking membership for user %s: %s", user_id, exc)
        reply = (
            "Не удалось проверить вашу подписку. Возможно, вы не подписаны на канал."
        )
        if channel_invite_link:
            reply += f"\n{channel_invite_link}"
        await context.bot.send_message(
            chat_id=user_id,
            text=reply,
        )


async def main() -> None:
    """Entry point: set up the bot and start polling."""
    config = load_config()
    application: Application = (
        ApplicationBuilder().token(config["token"]).build()
    )

    # Store configuration in application.bot_data so handlers can access it
    application.bot_data["config"] = config

    # Register command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("get", get_material))

    logger.info("Bot started. Waiting for commands…")
    await application.run_polling()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped")
