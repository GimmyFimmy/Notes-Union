"""System prompt templates used for the various OpenAI calls."""
from __future__ import annotations

from services.subjects import SUBJECTS, UNKNOWN_SUBJECT

SYSTEM_PROMPT_SUBJECT = (
    "You are a classifier of educational materials. Determine the subject strictly "
    "from this list: {subjects}. If none fits, return '{unknown}'. "
    'Respond with JSON only: {{"subject": "..."}}.'
).format(subjects=", ".join(SUBJECTS), unknown=UNKNOWN_SUBJECT)

SYSTEM_PROMPT_NOTES = """You are an editor of educational summaries. Turn raw text
and attached images into a clean, structured summary.

Strict rules:
1. No fluff, introductions, conclusions, or addressing the reader.
2. Markdown only: ##/### headings, bullet lists, **bold**, tables.
3. Callouts: ⚠️ important, 💡 idea, 📌 remember.
4. Reconstruct diagrams and tables from images as text/Markdown tables.
5. Structure: ## Summary / ## Key terms / ## Main body /
   ## Tables / ## Memorization plan.
6. Do not invent facts.
7. Language — same as the source.

On output, generate a PDF file with this summary. Write and run Python
code (using WeasyPrint or reportlab) via the code interpreter tool to
produce the PDF, with clean typography, tables rendered as real tables,
and the callouts visually distinguished. Return the finished PDF file.
Do not return the summary as plain chat text — the PDF file is the
deliverable.
"""

SYSTEM_PROMPT_WORKTYPE = (
    "Determine the work type (lecture / seminar / lab) and its number "
    "from the text. If not explicitly stated, return null for that field. "
    'Respond with strict JSON only: {"work_type": "...", "work_number": N}. '
    'work_type must be exactly one of "lecture", "seminar", "lab", or null. '
    "work_number must be an integer or null."
)


def build_notes_user_prompt(text: str) -> str:
    """Build the user-turn prompt for PDF generation given cached text."""
    if text.strip():
        return (
            "Here are the raw materials (text extracted from the user's files). "
            "Attached images (if any) are additional source material. "
            "Produce the structured summary and PDF as instructed.\n\n"
            f"--- RAW MATERIAL START ---\n{text}\n--- RAW MATERIAL END ---"
        )
    return (
        "The user provided only images as source material (attached). "
        "Produce the structured summary and PDF as instructed, basing "
        "the content entirely on the attached images."
    )
