"""ESA/Hubble ingester — pulls real science-release imagery from esahubble.org.

Far better quality than NASA IVL: each release has a full 20K-pixel TIFF, a
26 MB `large` JPEG, rich metadata (object name, redshift, RA/Dec), and a
stable ID pattern like `heic2506a`. CC-BY licensed, freely redistributable.

Two usage modes:
    python -m workers.esa_hubble_ingest                       # seed with curated
    python -m workers.esa_hubble_ingest heic2506a heic1502a   # specific IDs

Curated seed set covers the most iconic Hubble releases across Messier/Caldwell
targets we already have in sky_objects.
"""
import asyncio
import re
import sys

import httpx

from app.db import close_pool, get_pool

DETAIL_URL = "https://www.esahubble.org/images/{id}/"
THUMB_URL  = "https://cdn.esahubble.org/archives/images/screen/{id}.jpg"
LARGE_URL  = "https://cdn.esahubble.org/archives/images/large/{id}.jpg"

# Curated iconic releases — each tied to one of our catalog objects.
CURATED = [
    ("heic2506a", "Sombrero Galaxy"),        # M104
    ("heic1502a", "Andromeda Galaxy"),        # M31 — Hubble panoramic, 1.5 billion pixels
    ("heic0910h", "Carina Nebula"),           # C92 — Hubble 20th anniversary
    ("heic0506a", "Pillars of Creation"),     # M16 Eagle Nebula
    ("heic0602a", "Whirlpool Galaxy"),        # M51
    ("heic0405a", "Ring Nebula"),             # M57
    ("heic0910a", "Orion Nebula"),            # M42
    ("heic1602a", "Crab Nebula"),             # M1
    ("heic0601a", "Omega Centauri"),          # C80
    ("heic1118a", "Helix Nebula"),            # C63
    ("heic1107a", "Tarantula Nebula"),        # C103
    ("heic1007a", "Cat's Eye Nebula"),        # C6
    ("heic2005a", "Veil Nebula"),             # C34/C33
    ("heic0601c", "Eagle Nebula"),            # M16
    ("heic0715a", "Pleiades"),                # M45
    ("heic1105a", "Cigar Galaxy"),            # M82
    ("heic0604a", "Bode's Galaxy"),           # M81
    ("heic0910b", "Pinwheel Galaxy"),         # M101
]

TIMEOUT = httpx.Timeout(60.0, connect=20.0)
HEADERS = {"User-Agent": "tower-skymap/0.1 (+https://github.com/pvestal/tower-skymap)"}

META_OG_TITLE = re.compile(r'<meta property="og:title" content="([^"]+)"')
META_OG_DESC  = re.compile(r'<meta property="og:description" content="([^"]*)"')
META_OG_IMG   = re.compile(r'<meta property="og:image" content="([^"]+)"')
# ESA pages sometimes include coordinates in structured data
RA_PATTERN    = re.compile(r'Position\s*\(RA\)[^<]*<td[^>]*>([\d\s:.h m]+)', re.I)
DEC_PATTERN   = re.compile(r'Position\s*\(Dec\)[^<]*<td[^>]*>([-+\d\s:.°\' ]+)', re.I)


async def fetch_detail(client: httpx.AsyncClient, release_id: str) -> dict | None:
    url = DETAIL_URL.format(id=release_id)
    r = await client.get(url, headers=HEADERS)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    html = r.text

    title_m = META_OG_TITLE.search(html)
    desc_m  = META_OG_DESC.search(html)
    if not title_m:
        return None

    # Favor the large variant URL for the source's upstream_url — but store
    # the screen URL as the thumb_source metadata so drain uses the 100 KB
    # version for local thumbnailing instead of downloading 26 MB.
    title = title_m[1]
    description = desc_m[1] if desc_m else title
    large = LARGE_URL.format(id=release_id)
    screen = THUMB_URL.format(id=release_id)
    detail = url

    return {
        "release_id": release_id,
        "title": title,
        "caption": description,
        "upstream_url": screen,   # what drain downloads (100 KB)
        "detail_url": detail,     # click-through destination
        "full_url": large,        # 26 MB full-res if user wants it
    }


INSERT_SQL = """
INSERT INTO sky_sources
    (source, source_id, title, caption, upstream_url, upstream_is_cdn,
     storage_policy, metadata, observed_at)
VALUES
    ('esa_hubble', $1, $2, $3, $4, TRUE, 'mirror', $5, NOW())
ON CONFLICT (source, source_id) DO UPDATE SET
    title = EXCLUDED.title,
    caption = EXCLUDED.caption,
    upstream_url = EXCLUDED.upstream_url,
    metadata = EXCLUDED.metadata
RETURNING id, (xmax = 0) AS is_new
"""

QUEUE_SQL = """
INSERT INTO sky_tile_queue (source_id, status)
VALUES ($1, 'pending')
ON CONFLICT DO NOTHING
"""


async def store(conn, payload: dict) -> tuple[int, bool]:
    meta = {
        "release_id":  payload["release_id"],
        "detail_url":  payload["detail_url"],
        "full_url":    payload["full_url"],
        "license":     "CC BY 4.0",
        "attribution": "ESA/Hubble",
    }
    row = await conn.fetchrow(
        INSERT_SQL,
        payload["release_id"], payload["title"], payload["caption"],
        payload["upstream_url"], meta,
    )
    await conn.execute(QUEUE_SQL, row["id"])
    return row["id"], row["is_new"]


async def main() -> None:
    ids = [a for a in sys.argv[1:] if a] or [c[0] for c in CURATED]
    pool = await get_pool()
    async with pool.acquire() as conn, httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
        inserted = updated = skipped = 0
        for release_id in ids:
            try:
                payload = await fetch_detail(client, release_id)
            except Exception as e:
                print(f"[{release_id}] fetch failed: {e}")
                skipped += 1
                continue
            if payload is None:
                print(f"[{release_id}] not found on esahubble.org")
                skipped += 1
                continue
            _, is_new = await store(conn, payload)
            marker = "+" if is_new else "="
            print(f"  {marker} {release_id}: {payload['title']}")
            if is_new:
                inserted += 1
            else:
                updated += 1
    print(f"\nesa_hubble ingest: inserted={inserted} updated={updated} skipped={skipped}")
    await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
