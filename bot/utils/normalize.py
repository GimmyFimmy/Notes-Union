"""Helpers for normalizing forum topic names and other free text.

Telegram forum topic names are frequently decorated with emoji, icons,
extra whitespace, or inconsistent casing (e.g. "📐 Linear Algebra",
"LINEAR ALGEBRA  ", "linear-algebra"). To reliably match a topic name
against the fixed SUBJECTS list we strip all of that down to a
canonical form before comparing.
"""
from __future__ import annotations

import re
import unicodedata

# Matches most emoji / pictographic ranges plus variation selectors.
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "\U00002190-\U000021FF"
    "\U00002B00-\U00002BFF"
    "\U0000FE0F"
    "]+",
    flags=re.UNICODE,
)

_NON_ALNUM_PATTERN = re.compile(r"[^\w\s]", flags=re.UNICODE)
_WHITESPACE_PATTERN = re.compile(r"\s+")


def strip_emojis(text: str) -> str:
    """Remove emoji / pictographic characters from a string."""
    return _EMOJI_PATTERN.sub("", text)


def normalize_topic_name(text: str) -> str:
    """Return a canonical, comparison-friendly form of a topic/subject name.

    Steps:
        1. Strip emojis.
        2. Unicode-normalize (NFKC) so visually-identical characters compare equal.
        3. Replace punctuation/symbols with spaces.
        4. Collapse whitespace.
        5. Lowercase and strip.
    """
    if not text:
        return ""

    text = strip_emojis(text)
    text = unicodedata.normalize("NFKC", text)
    text = _NON_ALNUM_PATTERN.sub(" ", text)
    text = _WHITESPACE_PATTERN.sub(" ", text)
    return text.strip().lower()


def names_match(a: str, b: str) -> bool:
    """True if two topic/subject names refer to the same thing once normalized."""
    return normalize_topic_name(a) == normalize_topic_name(b)
