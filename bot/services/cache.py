"""In-memory, per-user cache of accumulated materials (texts + images).

The cache tracks approximate size in bytes so a user cannot exceed
`MAX_CACHE_SIZE_MB`. Files are written under `TEMP_DIR/{user_id}/`.
"""
from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from config import settings

logger = logging.getLogger(__name__)


class CacheLimitExceeded(Exception):
    """Raised when adding an item would exceed the user's cache size limit."""


@dataclass
class UserCache:
    user_id: int
    texts: list[str] = field(default_factory=list)
    images: list[Path] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    size_bytes: int = 0

    @property
    def is_empty(self) -> bool:
        return not self.texts and not self.images

    @property
    def dir(self) -> Path:
        return settings.TEMP_DIR / str(self.user_id)


class MaterialCacheService:
    """Manages per-user `UserCache` objects."""

    def __init__(self) -> None:
        self._caches: dict[int, UserCache] = {}
        self._max_bytes = int(settings.MAX_CACHE_SIZE_MB * 1024 * 1024)

    def _get_or_create(self, user_id: int) -> UserCache:
        cache = self._caches.get(user_id)
        if cache is None:
            cache = UserCache(user_id=user_id)
            cache.dir.mkdir(parents=True, exist_ok=True)
            self._caches[user_id] = cache
        return cache

    def _check_limit(self, cache: UserCache, additional_bytes: int) -> None:
        if cache.size_bytes + additional_bytes > self._max_bytes:
            raise CacheLimitExceeded(
                f"Cache limit of {settings.MAX_CACHE_SIZE_MB} MB exceeded "
                f"for user {cache.user_id}"
            )

    def add_text(self, user_id: int, text: str) -> None:
        cache = self._get_or_create(user_id)
        text_bytes = len(text.encode("utf-8"))
        self._check_limit(cache, text_bytes)
        cache.texts.append(text)
        cache.size_bytes += text_bytes
        logger.info("Added text (%d bytes) to cache for user %s", text_bytes, user_id)

    def add_image(self, user_id: int, source_path: Path, filename: str) -> Path:
        cache = self._get_or_create(user_id)
        file_size = source_path.stat().st_size
        self._check_limit(cache, file_size)

        dest = cache.dir / filename
        shutil.copy2(source_path, dest)
        cache.images.append(dest)
        cache.size_bytes += file_size
        logger.info("Added image %s (%d bytes) to cache for user %s", dest, file_size, user_id)
        return dest

    def get(self, user_id: int) -> UserCache:
        return self._get_or_create(user_id)

    def has_materials(self, user_id: int) -> bool:
        cache = self._caches.get(user_id)
        return cache is not None and not cache.is_empty

    def clear(self, user_id: int) -> None:
        cache = self._caches.pop(user_id, None)
        if cache is not None and cache.dir.exists():
            shutil.rmtree(cache.dir, ignore_errors=True)
        logger.info("Cleared cache for user %s", user_id)


# Single shared instance used across handlers.
material_cache = MaterialCacheService()
