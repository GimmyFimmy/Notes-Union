"""Global error handler for unhandled exceptions raised inside handlers."""
from __future__ import annotations

import logging

from aiogram import Router
from aiogram.types import ErrorEvent

logger = logging.getLogger(__name__)

router = Router(name="errors")


@router.error()
async def on_error(event: ErrorEvent) -> bool:
    """Log unhandled exceptions and, where possible, notify the user.

    Returning True marks the error as handled so aiogram does not
    re-raise it and crash the polling loop.
    """
    exc = event.exception
    update = event.update
    logger.exception("Unhandled exception while processing update %s: %s", update.update_id, exc)

    message = update.message or (update.callback_query.message if update.callback_query else None)
    if message is not None:
        try:
            await message.answer(
                "⚠️ Something went wrong while processing your request. "
                "Please try again in a moment. If this keeps happening, "
                "contact the bot administrator."
            )
        except Exception:  # noqa: BLE001 - best-effort notification only
            logger.exception("Failed to notify user about the error")

    return True
