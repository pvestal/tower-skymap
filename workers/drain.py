import asyncio
import sys
from pathlib import Path

import httpx
from PIL import Image

from app.config import settings
from app.db import close_pool, get_pool

THUMB_SIZE = (256, 256)


async def claim_job(conn) -> dict | None:
    return await conn.fetchrow(
        """
        UPDATE sky_tile_queue
           SET status='running', attempts=attempts+1, updated_at=NOW()
         WHERE id = (
           SELECT id FROM sky_tile_queue
            WHERE status IN ('pending','failed') AND attempts < 5
            ORDER BY created_at
            FOR UPDATE SKIP LOCKED
            LIMIT 1
         )
        RETURNING id, source_id
        """
    )


async def process(conn, job: dict) -> None:
    src = await conn.fetchrow(
        """
        SELECT id, source, source_id, upstream_url, storage_policy
          FROM sky_sources WHERE id=$1
        """,
        job["source_id"],
    )
    if src is None:
        raise RuntimeError("missing source row")

    policy = src["storage_policy"]

    if policy == "proxy_only":
        return

    if not src["upstream_url"]:
        raise RuntimeError("missing upstream_url")

    suffix = Path(src["upstream_url"]).suffix.lower() or ".jpg"
    if suffix not in {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".fits"}:
        suffix = ".jpg"
    rel_raw = f"raw/{src['source']}/{src['source_id']}{suffix}"
    rel_thumb = f"thumbs/{src['source']}/{src['source_id']}.jpg"
    raw_path = settings.storage_root / rel_raw
    thumb_path = settings.storage_root / rel_thumb
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    thumb_path.parent.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(follow_redirects=True) as client:
        r = await client.get(src["upstream_url"], timeout=120)
        r.raise_for_status()
        raw_path.write_bytes(r.content)

    with Image.open(raw_path) as im:
        im.thumbnail(THUMB_SIZE)
        im.convert("RGB").save(thumb_path, "JPEG", quality=85)

    thumb_bytes = thumb_path.stat().st_size
    await conn.execute(
        """
        INSERT INTO sky_tiles (source_id, kind, local_relpath, bytes, storage_tier)
        VALUES ($1, 'thumb', $2, $3, 'hot')
        ON CONFLICT (source_id, kind, local_relpath) DO NOTHING
        """,
        src["id"], rel_thumb, thumb_bytes,
    )

    if policy == "mirror":
        await conn.execute(
            """
            INSERT INTO sky_tiles (source_id, kind, local_relpath, bytes, storage_tier)
            VALUES ($1, 'raw', $2, $3, 'hot')
            ON CONFLICT (source_id, kind, local_relpath) DO NOTHING
            """,
            src["id"], rel_raw, raw_path.stat().st_size,
        )
    else:
        raw_path.unlink(missing_ok=True)


async def main() -> None:
    max_jobs = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    pool = await get_pool()
    done = 0
    failed = 0
    for _ in range(max_jobs):
        async with pool.acquire() as conn:
            async with conn.transaction():
                job = await claim_job(conn)
                if job is None:
                    break
                try:
                    await process(conn, job)
                    await conn.execute(
                        "UPDATE sky_tile_queue SET status='done', updated_at=NOW() WHERE id=$1",
                        job["id"],
                    )
                    done += 1
                except Exception as exc:
                    await conn.execute(
                        """
                        UPDATE sky_tile_queue
                           SET status='failed', last_error=$2, updated_at=NOW()
                         WHERE id=$1
                        """,
                        job["id"], str(exc)[:500],
                    )
                    failed += 1
    print(f"drain: done={done} failed={failed}")
    await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
