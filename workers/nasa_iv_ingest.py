import asyncio
import sys
from datetime import datetime

import httpx

from app.db import close_pool, get_pool

SEARCH_URL = "https://images-api.nasa.gov/search"

DEFAULT_QUERIES = [
    "galaxy", "nebula", "supernova", "star cluster",
    "mars", "jupiter", "saturn", "black hole",
]

MAX_PAGES_PER_QUERY = 3
PAGE_SIZE_HINT = 100


def _derive_orig_url(thumb_url: str) -> str | None:
    for suffix in ("~thumb.jpg", "~small.jpg", "~medium.jpg"):
        if thumb_url.endswith(suffix):
            return thumb_url[: -len(suffix)] + "~orig.jpg"
    return None


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def extract_items(payload: dict):
    for item in payload.get("collection", {}).get("items", []):
        data_list = item.get("data") or []
        if not data_list:
            continue
        data = data_list[0]
        if data.get("media_type") != "image":
            continue
        nasa_id = data.get("nasa_id")
        if not nasa_id:
            continue
        thumb = next(
            (lk["href"] for lk in (item.get("links") or [])
             if lk.get("rel") == "preview" and lk.get("render") == "image"),
            None,
        )
        if not thumb:
            continue
        orig = _derive_orig_url(thumb)
        if not orig:
            continue
        yield {
            "nasa_id": nasa_id,
            "title": data.get("title"),
            "description": data.get("description"),
            "date_created": data.get("date_created"),
            "orig_url": orig,
            "raw": item,
        }


async def search_page(client: httpx.AsyncClient, query: str, page: int) -> dict:
    r = await client.get(
        SEARCH_URL,
        params={"q": query, "media_type": "image",
                "page": page, "page_size": PAGE_SIZE_HINT},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


async def store_item(conn, item: dict) -> bool:
    row = await conn.fetchrow(
        """
        INSERT INTO sky_sources (source, source_id, title, caption,
                                 observed_at, upstream_url, metadata,
                                 storage_policy, upstream_is_cdn)
        VALUES ('nasa_iv', $1, $2, $3, $4, $5, $6, 'thumb_only', TRUE)
        ON CONFLICT (source, source_id) DO NOTHING
        RETURNING id
        """,
        item["nasa_id"], item["title"], item["description"],
        _parse_date(item["date_created"]), item["orig_url"], item["raw"],
    )
    if row is None:
        return False
    await conn.execute(
        "INSERT INTO sky_tile_queue (source_id) VALUES ($1)", row["id"]
    )
    return True


def _has_next_page(payload: dict) -> bool:
    return any(
        lk.get("rel") == "next"
        for lk in (payload.get("collection", {}).get("links") or [])
    )


async def main() -> None:
    queries = sys.argv[1:] or DEFAULT_QUERIES
    pool = await get_pool()
    total_inserted = 0

    async with httpx.AsyncClient() as client:
        for q in queries:
            for page in range(1, MAX_PAGES_PER_QUERY + 1):
                try:
                    payload = await search_page(client, q, page)
                except httpx.HTTPError as exc:
                    print(f"nasa_iv q={q!r} p{page}: {exc}", file=sys.stderr)
                    break

                inserted = 0
                async with pool.acquire() as conn, conn.transaction():
                    for item in extract_items(payload):
                        if await store_item(conn, item):
                            inserted += 1
                total_inserted += inserted
                print(f"nasa_iv q={q!r} page={page}: +{inserted}")
                if not _has_next_page(payload):
                    break

    print(f"nasa_iv ingest: {total_inserted} new sources across {len(queries)} queries")
    await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
