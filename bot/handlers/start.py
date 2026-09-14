"""Core user-facing handlers: /start, /clear, /generate, and receiving
photos / text documents to be cached for the next /generate run.
"""
from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Document, Message, PhotoSize

from config import settings
from services.ai_agent import AIAgentError, classify_subject, extract_work_type, generate_notes_pdf
from services.cache import CacheLimitExceeded, material_cache
from services.subjects import UNKNOWN_SUBJECT, find_thread_id, get_subject_thread_map

logger = logging.getLogger(__name__)

router = Router(name="start")

ALLOWED_TEXT_SUFFIXES = {".txt", ".md"}

# Populated on bot startup by main.py and refreshed lazily if empty.
_subject_thread_map: dict[str, int] = {}


def set_subject_thread_map(mapping: dict[str, int]) -> None:
    global _subject_thread_map
    _subject_thread_map = mapping


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "👋 Hi! I turn your lecture materials into a clean PDF summary.\n\n"
        "How to use me:\n"
        "1. Send me photos (of slides, whiteboards, notes) and/or .txt/.md files.\n"
        "2. Send as many as you like — I'll cache them for you.\n"
        "3. Run /generate when you're done — I'll figure out the subject, "
        "build a structured PDF summary, and post it to the right topic "
        "in the class group.\n\n"
        "Other commands:\n"
        "/clear — clear your cached materials\n"
        "/generate — generate and post the summary"
    )


@router.message(Command("clear"))
async def cmd_clear(message: Message) -> None:
    material_cache.clear(message.from_user.id)
    await message.answer("🗑 Your cached materials have been cleared.")


@router.message(F.photo)
async def on_photo(message: Message, bot) -> None:
    user_id = message.from_user.id
    largest: PhotoSize = message.photo[-1]

    try:
        file = await bot.get_file(largest.file_id)
        dest_dir = settings.TEMP_DIR / "_incoming"
        dest_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = dest_dir / f"{largest.file_unique_id}.jpg"
        await bot.download_file(file.file_path, destination=tmp_path)

        material_cache.add_image(user_id, tmp_path, filename=f"{largest.file_unique_id}.jpg")
        tmp_path.unlink(missing_ok=True)
    except CacheLimitExceeded as exc:
        await message.answer(f"⚠️ Can't add this photo: {exc}")
        return
    except (TelegramAPIError, OSError) as exc:
        logger.exception("Failed to download/store photo from user %s", user_id)
        await message.answer(f"⚠️ Couldn't save that photo: {exc}")
        return

    await message.answer("📷 Photo cached. Send more, or run /generate when ready.")


@router.message(F.document)
async def on_document(message: Message, bot) -> None:
    user_id = message.from_user.id
    document: Document = message.document
    suffix = Path(document.file_name or "").suffix.lower()

    if suffix not in ALLOWED_TEXT_SUFFIXES:
        await message.answer(
            f"⚠️ Unsupported file type '{suffix or 'unknown'}'. "
            f"Please send a .txt or .md file (or a photo)."
        )
        return

    try:
        file = await bot.get_file(document.file_id)
        dest_dir = settings.TEMP_DIR / "_incoming"
        dest_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = dest_dir / f"{document.file_unique_id}{suffix}"
        await bot.download_file(file.file_path, destination=tmp_path)

        text = tmp_path.read_text(encoding="utf-8", errors="replace")
        material_cache.add_text(user_id, text)
        tmp_path.unlink(missing_ok=True)
    except CacheLimitExceeded as exc:
        await message.answer(f"⚠️ Can't add this file: {exc}")
        return
    except (TelegramAPIError, OSError, UnicodeError) as exc:
        logger.exception("Failed to download/read document from user %s", user_id)
        await message.answer(f"⚠️ Couldn't read that file: {exc}")
        return

    await message.answer("📄 File cached. Send more, or run /generate when ready.")


@router.message(Command("generate"))
async def cmd_generate(message: Message, bot) -> None:
    user_id = message.from_user.id

    if not material_cache.has_materials(user_id):
        await message.answer(
            "You haven't sent me any materials yet. Send photos or .txt/.md "
            "files first, then run /generate."
        )
        return

    cache = material_cache.get(user_id)
    combined_text = "\n\n".join(cache.texts)

    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    await message.answer("🧠 Determining the subject…")

    try:
        subject = await classify_subject(combined_text)
    except AIAgentError as exc:
        await message.answer(f"⚠️ Couldn't determine the subject: {exc}")
        return

    if subject == UNKNOWN_SUBJECT:
        await message.answer(
            "🤔 I couldn't confidently match your materials to any known "
            "subject. Please double-check the content, or ask an admin to "
            "add the right subject to the list."
        )
        return

    global _subject_thread_map
    if not _subject_thread_map:
        _subject_thread_map = await get_subject_thread_map(bot, settings.TARGET_GROUP_ID)

    thread_id = find_thread_id(subject, _subject_thread_map)
    if thread_id is None:
        # Try a fresh rebuild once — topics may have been created after startup.
        _subject_thread_map = await get_subject_thread_map(bot, settings.TARGET_GROUP_ID)
        thread_id = find_thread_id(subject, _subject_thread_map)

    if thread_id is None:
        await message.answer(
            f"⚠️ Subject determined as *{subject}*, but I couldn't find a "
            f"matching topic for it in the target group. Ask an admin to "
            f"create a forum topic named exactly '{subject}'.",
            parse_mode="Markdown",
        )
        return

    await message.answer(f"📚 Subject: *{subject}*. Generating the PDF summary…", parse_mode="Markdown")
    await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_DOCUMENT)

    try:
        pdf_bytes = await generate_notes_pdf(combined_text, cache.images)
    except AIAgentError as exc:
        await message.answer(f"⚠️ PDF generation failed: {exc}")
        return

    try:
        work_info = await extract_work_type(combined_text)
    except Exception:  # noqa: BLE001 - never let this block delivery
        logger.exception("extract_work_type failed unexpectedly, continuing without it")
        work_info = {"work_type": None, "work_number": None}

    caption = _build_caption(work_info.get("work_type"), work_info.get("work_number"))
    filename = f"{subject.replace(' ', '_')}_{dt.date.today().isoformat()}.pdf"

    try:
        await bot.send_document(
            chat_id=settings.TARGET_GROUP_ID,
            message_thread_id=thread_id,
            document=BufferedInputFile(pdf_bytes, filename=filename),
            caption=caption,
        )
    except TelegramAPIError as exc:
        logger.exception("Failed to post PDF to target group")
        await message.answer(f"⚠️ Generated the PDF, but failed to post it to the group: {exc}")
        return

    material_cache.clear(user_id)
    await message.answer("✅ Done! The summary was posted to the group and your cache was cleared.")


def _build_caption(work_type: str | None, work_number: int | None) -> str:
    today = dt.date.today().strftime("%d.%m.%Y")
    if work_type and work_number:
        return f"{work_type.capitalize()} #{work_number} — {today}"
    if work_type:
        return f"{work_type.capitalize()} — {today}"
    return today
