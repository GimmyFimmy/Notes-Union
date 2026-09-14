"""Fixed subject list and subject <-> forum-thread mapping.

Edit SUBJECTS to match the topics that exist in your Telegram forum group.
Each entry must match (after normalization — see utils/normalize.py) the
name of a topic in the target group, or the bot will not be able to find
where to post the generated PDF.
"""
from __future__ import annotations

import logging
from typing import Dict

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from utils.normalize import normalize_topic_name

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# EDIT THIS LIST to match your real subjects / forum topics.
# ---------------------------------------------------------------------------
SUBJECTS: list[str] = [
    "ОП (основы программирования)",
    "ОРГ (основы российской государственности)",
]

UNKNOWN_SUBJECT = "unknown"

# Runtime cache: thread_id -> normalized topic name, populated as topics are
# observed (via forum_topic_created / forum_topic_edited updates).
_topic_cache: Dict[int, str] = {}


def register_topic(thread_id: int, name: str) -> None:
    """Record/update a known forum topic's name.

    Called from handlers/topics.py whenever Telegram tells us a topic was
    created or renamed.
    """
    _topic_cache[thread_id] = name
    logger.info("Registered topic thread_id=%s name=%r", thread_id, name)


def get_known_topics() -> Dict[int, str]:
    """Return a copy of the current thread_id -> raw name cache."""
    return dict(_topic_cache)


async def get_subject_thread_map(bot: Bot, group_id: int) -> Dict[str, int]:
    """Build a mapping of {subject_name: thread_id} for the target group.

    Telegram's Bot API does not expose a generic "list all forum topics"
    call, so this function works with whatever topics have been observed
    so far via `forum_topic_created` / `forum_topic_edited` service
    messages (see handlers/topics.py), which are captured continuously
    while the bot is running and stored in `_topic_cache`.

    On startup this may therefore be empty/partial until each topic has
    produced at least one service message since the bot went online, or
    until someone posts in it. This is a known Bot API limitation.
    """
    mapping: Dict[str, int] = {}

    # Sanity-check bot has access to the group (also warms up caches).
    try:
        await bot.get_chat(group_id)
    except TelegramAPIError as exc:
        logger.error("Could not access target group %s: %s", group_id, exc)
        return mapping

    normalized_subjects = {normalize_topic_name(s): s for s in SUBJECTS}

    for thread_id, raw_name in _topic_cache.items():
        norm = normalize_topic_name(raw_name)
        if norm in normalized_subjects:
            subject = normalized_subjects[norm]
            mapping[subject] = thread_id

    logger.info(
        "Built subject->thread map: %s (from %d known topics)",
        mapping,
        len(_topic_cache),
    )
    return mapping


def find_thread_id(subject: str, subject_thread_map: Dict[str, int]) -> int | None:
    """Look up a thread id for a subject, tolerating minor name drift."""
    if subject in subject_thread_map:
        return subject_thread_map[subject]

    norm_subject = normalize_topic_name(subject)
    for known_subject, thread_id in subject_thread_map.items():
        if normalize_topic_name(known_subject) == norm_subject:
            return thread_id
    return None
