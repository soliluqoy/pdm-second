"""
PREDICT — Runtime settings (single source of truth: system_config table)
Shadow mode is read from the DB with a small in-process cache so the
ingestion hot path doesn't query it on every alert.
"""
import time
from typing import Optional

from sqlalchemy import select

from app.config import settings
from app.db.models import SystemConfig

_CACHE_TTL = 10.0
_shadow_cache: Optional[bool] = None
_shadow_cached_at: float = 0.0


def invalidate_shadow_mode_cache() -> None:
    global _shadow_cache
    _shadow_cache = None


async def get_shadow_mode(session) -> bool:
    """Shadow mode from system_config (cached ~10s); env value is only a
    fallback for databases that predate the config row."""
    global _shadow_cache, _shadow_cached_at
    now = time.monotonic()
    if _shadow_cache is not None and (now - _shadow_cached_at) < _CACHE_TTL:
        return _shadow_cache

    result = await session.execute(
        select(SystemConfig.value).where(SystemConfig.key == "shadow_mode")
    )
    value = result.scalar_one_or_none()
    _shadow_cache = (value.lower() == "true") if value is not None else settings.SHADOW_MODE
    _shadow_cached_at = now
    return _shadow_cache
