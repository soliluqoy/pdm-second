"""Health transition logging helper."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.models import AssetHealth
from app.services.health import log_health_transition


@pytest.mark.asyncio
async def test_log_health_transition_skips_same_health():
    session = MagicMock()
    session.add = MagicMock()
    await log_health_transition(
        session, 1, AssetHealth.GREEN, AssetHealth.GREEN, reason="noop"
    )
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_log_health_transition_adds_event():
    session = MagicMock()
    session.add = MagicMock()
    await log_health_transition(
        session, 7, AssetHealth.GREEN, AssetHealth.GREY, reason="offline_watchdog"
    )
    session.add.assert_called_once()
    event = session.add.call_args[0][0]
    assert event.vehicle_id == 7
    assert event.from_health == AssetHealth.GREEN
    assert event.to_health == AssetHealth.GREY
    assert event.reason == "offline_watchdog"
