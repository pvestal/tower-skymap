import asyncio
import sys
from datetime import date, datetime, timezone

import httpx

from app.config import settings
from app.db import close_pool, get_pool

APOD_URL = "https://api.nasa.gov/planetary/apod"


async def fetch_apod(client: httpx.AsyncClient, when: date | None = None) -> dict:
    params = {"api_key": settings.nasa_api_key}
    if when is not None:
        params["date"] = when.isoformat()
    r = await client.get(APOD_URL, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


async def store_apod(payload: dict) -> bool:
    if payload.get("media_type") != "image":
        return False
    url = payload.get("hdurl") or payload.get("url")
    if not url:
        return False

    observed_at = datetime.fromisoformat(payload["date"]).replace(tzinfo=timezone.utc)
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            """
            INSERT INTO sky_sources (source, source_id, title, caption,
                                     observed_at, upstream_url, metadata)
            VALUES ('apod', $1, $2, $3, $4, $5, $6)
            ON CONFLICT (source, source_id) DO NOTHING
            RETURNING id
            """,
            payload["date"], payload.get("title"), payload.get("explanation"),
            observed_at, url, payload,
        )
        if row is None:
            return False
        await conn.execute(
            "INSERT INTO sky_tile_queue (source_id) VALUES ($1)", row["id"]
        )
    return True


async def main() -> None:
    days_back = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    inserted = 0
    today = date.today()
    async with httpx.AsyncClient() as client:
        for d in range(days_back):
            when = date.fromordinal(today.toordinal() - d)
            try:
                payload = await fetch_apod(client, when)
            except httpx.HTTPError as exc:
                print(f"apod {when}: {exc}", file=sys.stderr)
                continue
            if await store_apod(payload):
                inserted += 1
    print(f"apod ingest: {inserted} new sources across {days_back} day(s)")
    await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
