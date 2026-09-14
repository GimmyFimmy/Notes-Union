"""Capture forum topic create/edit service messages in the target group.

Telegram sends `forum_topic_created` / `forum_topic_edited` as special
fields on a regular Message when a topic is created or renamed inside a
forum-mode supergroup. We listen for these to keep our thread_id -> name
cache (in services/subjects.py) up to date, since the Bot API has no
generic "list topics" endpoint.
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import Message

from config import settings
from services.subjects import register_topic

logger = logging.getLogger(__name__)

router = Router(name="topics")


def _in_target_group(message: Message) -> bool:
    return message.chat.id == settings.TARGET_GROUP_ID


@router.message(F.forum_topic_created, _in_target_group)
async def on_topic_created(message: Message) -> None:
    topic = message.forum_topic_created
    thread_id = message.message_thread_id
    if thread_id is None or topic is None:
        return
    register_topic(thread_id, topic.name)
    logger.info("Topic created: thread_id=%s name=%r", thread_id, topic.name)


@router.message(F.forum_topic_edited, _in_target_group)
async def on_topic_edited(message: Message) -> None:
    topic = message.forum_topic_edited
    thread_id = message.message_thread_id
    if thread_id is None or topic is None or topic.name is None:
        return
    register_topic(thread_id, topic.name)
    logger.info("Topic edited: thread_id=%s new name=%r", thread_id, topic.name)
