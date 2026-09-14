"""Entry point: starts the bot in long-polling mode.

Run from inside this directory (`bot/`):

    python main.py
"""
from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import settings
from handlers import errors, start, topics
from services.subjects import get_subject_thread_map


def setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        stream=sys.stdout,
    )
    # Keep noisy third-party libraries at a reasonable level.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)


async def on_startup(bot: Bot) -> None:
    logger = logging.getLogger(__name__)
    settings.ensure_dirs()

    try:
        mapping = await get_subject_thread_map(bot, settings.TARGET_GROUP_ID)
        start.set_subject_thread_map(mapping)
        logger.info("Startup subject->thread mapping: %s", mapping)
        if not mapping:
            logger.warning(
                "No subject->thread mapping could be built yet. This is "
                "expected if the bot has not seen any forum_topic_created/"
                "edited events since it last started. The mapping will be "
                "rebuilt on demand when /generate runs."
            )
    except Exception:  # noqa: BLE001 - startup must not crash on this
        logger.exception("Failed to build initial subject->thread mapping; continuing anyway")

    me = await bot.get_me()
    logger.info("Bot started as @%s (id=%s)", me.username, me.id)


async def main() -> None:
    setup_logging()
    logger = logging.getLogger(__name__)

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(errors.router)
    dp.include_router(topics.router)
    dp.include_router(start.router)

    dp.startup.register(on_startup)

    logger.info("Starting polling…")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.getLogger(__name__).info("Bot stopped.")
