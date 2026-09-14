"""All interaction with the OpenAI API.

Three operations are exposed:

- `classify_subject`   -> strict subject classification (structured output)
- `extract_work_type`  -> work type + number extraction (structured output)
- `generate_notes_pdf` -> full summary + PDF generation via the
                          Responses API with the `code_interpreter` tool

Each function raises `AIAgentError` on unrecoverable failures so callers
(handlers) can turn them into user-facing messages.
"""
from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any, Optional

from openai import AsyncOpenAI, APIError, APITimeoutError

from config import settings
from services.prompt import (
    SYSTEM_PROMPT_NOTES,
    SYSTEM_PROMPT_SUBJECT,
    SYSTEM_PROMPT_WORKTYPE,
    build_notes_user_prompt,
)
from services.subjects import SUBJECTS, UNKNOWN_SUBJECT

logger = logging.getLogger(__name__)

_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, timeout=settings.OPENAI_TIMEOUT_SECONDS)


class AIAgentError(Exception):
    """Raised when an OpenAI call fails or returns an unusable result."""


SUBJECT_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "name": "subject_classification",
    "schema": {
        "type": "object",
        "properties": {
            "subject": {
                "type": "string",
                "enum": [*SUBJECTS, UNKNOWN_SUBJECT],
            }
        },
        "required": ["subject"],
        "additionalProperties": False,
    },
    "strict": True,
}

WORKTYPE_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "name": "work_type_extraction",
    "schema": {
        "type": "object",
        "properties": {
            "work_type": {
                "type": ["string", "null"],
                "enum": ["lecture", "seminar", "lab", None],
            },
            "work_number": {"type": ["integer", "null"]},
        },
        "required": ["work_type", "work_number"],
        "additionalProperties": False,
    },
    "strict": True,
}


async def classify_subject(text: str) -> str:
    """Return one of SUBJECTS, or UNKNOWN_SUBJECT if nothing matches."""
    try:
        response = await _client.responses.create(
            model=settings.OPENAI_MODEL,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT_SUBJECT},
                {"role": "user", "content": text[:20000] or "(no text provided, images only)"},
            ],
            text={"format": SUBJECT_SCHEMA},
        )
        payload = json.loads(response.output_text)
        subject = payload.get("subject", UNKNOWN_SUBJECT)
        if subject not in SUBJECTS:
            return UNKNOWN_SUBJECT
        return subject
    except (APIError, APITimeoutError) as exc:
        logger.exception("classify_subject: OpenAI call failed")
        raise AIAgentError(f"Subject classification failed: {exc}") from exc
    except (json.JSONDecodeError, AttributeError) as exc:
        logger.exception("classify_subject: could not parse model output")
        raise AIAgentError("Subject classification returned an unparseable result") from exc


async def extract_work_type(text: str) -> dict[str, Optional[Any]]:
    """Return {"work_type": "lecture"|"seminar"|"lab"|None, "work_number": int|None}."""
    if not text.strip():
        return {"work_type": None, "work_number": None}

    try:
        response = await _client.responses.create(
            model=settings.OPENAI_MODEL,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT_WORKTYPE},
                {"role": "user", "content": text[:20000]},
            ],
            text={"format": WORKTYPE_SCHEMA},
        )
        payload = json.loads(response.output_text)
        return {
            "work_type": payload.get("work_type"),
            "work_number": payload.get("work_number"),
        }
    except (APIError, APITimeoutError) as exc:
        logger.warning("extract_work_type: OpenAI call failed, falling back to None/None: %s", exc)
        return {"work_type": None, "work_number": None}
    except (json.JSONDecodeError, AttributeError) as exc:
        logger.warning("extract_work_type: unparseable output, falling back: %s", exc)
        return {"work_type": None, "work_number": None}


def _image_to_data_url(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".") or "jpeg"
    if suffix == "jpg":
        suffix = "jpeg"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/{suffix};base64,{data}"


async def generate_notes_pdf(text: str, images: list[Path]) -> bytes:
    """Ask the model to produce a structured summary and render it as a PDF.

    Uses the Responses API with the `code_interpreter` tool so the model can
    write and execute Python (WeasyPrint/reportlab) to actually produce a
    PDF file, then downloads that file from the response's container.
    """
    user_content: list[dict[str, Any]] = [
        {"type": "input_text", "text": build_notes_user_prompt(text)}
    ]
    for image_path in images:
        try:
            user_content.append(
                {"type": "input_image", "image_url": _image_to_data_url(image_path)}
            )
        except OSError as exc:
            logger.warning("Skipping unreadable image %s: %s", image_path, exc)

    try:
        response = await _client.responses.create(
            model=settings.OPENAI_MODEL,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT_NOTES},
                {"role": "user", "content": user_content},
            ],
            tools=[{"type": "code_interpreter", "container": {"type": "auto"}}],
        )
    except (APIError, APITimeoutError) as exc:
        logger.exception("generate_notes_pdf: OpenAI call failed")
        raise AIAgentError(f"PDF generation failed: {exc}") from exc

    pdf_bytes = await _extract_pdf_from_response(response)
    if pdf_bytes is None:
        logger.error("generate_notes_pdf: no PDF file found in model response")
        raise AIAgentError(
            "The model did not return a PDF file. Try /generate again, "
            "or simplify the source materials."
        )
    return pdf_bytes


async def _extract_pdf_from_response(response: Any) -> Optional[bytes]:
    """Walk the Responses API output looking for a generated PDF container file.

    The Responses API surfaces files created by code_interpreter as
    "container_file_citation" annotations attached to output text, or as
    dedicated file parts depending on SDK version. We check both shapes
    defensively since this detail has changed across SDK releases.
    """
    file_id: Optional[str] = None
    container_id: Optional[str] = None

    for item in getattr(response, "output", []) or []:
        item_type = getattr(item, "type", None)

        # Shape 1: message content with annotations pointing at a container file.
        if item_type == "message":
            for content_part in getattr(item, "content", []) or []:
                for annotation in getattr(content_part, "annotations", []) or []:
                    if getattr(annotation, "type", None) == "container_file_citation":
                        candidate_file = getattr(annotation, "file_id", None)
                        filename = getattr(annotation, "filename", "") or ""
                        if candidate_file and filename.lower().endswith(".pdf"):
                            file_id = candidate_file
                            container_id = getattr(annotation, "container_id", None)

        # Shape 2: explicit code_interpreter_call output listing produced files.
        if item_type == "code_interpreter_call":
            outputs = getattr(item, "outputs", None) or []
            for out in outputs:
                if getattr(out, "type", None) == "file" or isinstance(out, dict) and out.get("type") == "file":
                    candidate_file = getattr(out, "file_id", None) or (
                        out.get("file_id") if isinstance(out, dict) else None
                    )
                    if candidate_file:
                        file_id = candidate_file
                        container_id = getattr(item, "container_id", None) or (
                            out.get("container_id") if isinstance(out, dict) else None
                        )

    if not file_id:
        return None

    try:
        if container_id:
            file_response = await _client.containers.files.content.retrieve(
                container_id=container_id, file_id=file_id
            )
        else:
            file_response = await _client.files.content(file_id)
        content = getattr(file_response, "content", None)
        if content is not None:
            return content
        # Some SDK versions expose .read() / .aread() on the response object.
        read = getattr(file_response, "aread", None) or getattr(file_response, "read", None)
        if read is not None:
            result = read()
            if hasattr(result, "__await__"):
                result = await result
            return result
    except (APIError, AttributeError) as exc:
        logger.exception("Failed to download generated PDF file_id=%s: %s", file_id, exc)
    return None
