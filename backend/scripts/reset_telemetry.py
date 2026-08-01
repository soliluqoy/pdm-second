"""
One-shot script to wipe telemetry-derived data and Redis live cache.

Usage (from repo root, backend container running):
    docker compose exec backend python scripts/reset_telemetry.py

Or locally with DATABASE_URL / REDIS_URL pointing at the stack.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.database import async_session_factory  # noqa: E402
from app.services.telemetry_reset import reset_telemetry_data  # noqa: E402


async def main() -> None:
    async with async_session_factory() as session:
        counts = await reset_telemetry_data(session)
    print("Telemetry reset complete:")
    for key, value in counts.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    asyncio.run(main())
