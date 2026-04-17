import asyncio
import shutil
import sys

from app.config import settings
from app.db import close_pool, get_pool


async def claim_stale_tile(conn):
    return await conn.fetchrow(
        """
        SELECT id, source_id, local_relpath
          FROM sky_tiles
         WHERE kind = 'raw'
           AND storage_tier = 'hot'
           AND last_accessed_at < NOW() - make_interval(days => $1)
         ORDER BY last_accessed_at ASC
         FOR UPDATE SKIP LOCKED
         LIMIT 1
        """,
        settings.hot_retention_days,
    )


async def demote(conn, tile: dict) -> str:
    hot_path = settings.storage_root / tile["local_relpath"]
    cold_root = settings.cold_storage_root
    if cold_root is None:
        raise RuntimeError("SKYMAP_COLD_STORAGE_ROOT not configured")

    cold_path = cold_root / tile["local_relpath"]

    if not hot_path.exists():
        await conn.execute(
            "UPDATE sky_tiles SET storage_tier='evicted' WHERE id=$1", tile["id"]
        )
        return "evicted-missing"

    cold_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(hot_path), str(cold_path))

    await conn.execute(
        "UPDATE sky_tiles SET storage_tier='cold' WHERE id=$1", tile["id"]
    )
    return "moved"


async def main() -> None:
    max_jobs = int(sys.argv[1]) if len(sys.argv) > 1 else 500
    if settings.cold_storage_root is None:
        print("tier-migrate: SKYMAP_COLD_STORAGE_ROOT not set; nothing to do")
        return

    pool = await get_pool()
    moved = 0
    evicted_missing = 0
    for _ in range(max_jobs):
        async with pool.acquire() as conn, conn.transaction():
            tile = await claim_stale_tile(conn)
            if tile is None:
                break
            result = await demote(conn, dict(tile))
            if result == "moved":
                moved += 1
            else:
                evicted_missing += 1
    print(
        f"tier-migrate: moved={moved} evicted_missing={evicted_missing} "
        f"retention={settings.hot_retention_days}d"
    )
    await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
