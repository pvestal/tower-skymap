from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

from ..config import settings
from ..db import get_pool

router = APIRouter(prefix="/image", tags=["image"])


@router.get("/{source_id}")
async def get_source(source_id: int) -> dict:
    pool = await get_pool()
    src = await pool.fetchrow(
        "SELECT * FROM sky_sources WHERE id = $1", source_id
    )
    if src is None:
        raise HTTPException(404)
    tiles = await pool.fetch(
        """
        SELECT id, kind, local_relpath, storage_tier, size_px, bytes,
               ra, dec, fov_arcmin, last_accessed_at
          FROM sky_tiles WHERE source_id = $1
         ORDER BY kind, storage_tier
        """,
        source_id,
    )
    return {"source": dict(src), "tiles": [dict(t) for t in tiles]}


def _tier_root(tier: str):
    if tier == "cold":
        if settings.cold_storage_root is None:
            return None
        return settings.cold_storage_root
    return settings.storage_root


@router.get("/tile/{tile_id}/file")
async def get_tile_file(tile_id: int):
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT t.id, t.local_relpath, t.storage_tier,
               s.upstream_url, s.upstream_is_cdn, s.storage_policy
          FROM sky_tiles t
          JOIN sky_sources s ON s.id = t.source_id
         WHERE t.id = $1
        """,
        tile_id,
    )
    if row is None:
        raise HTTPException(404)

    await pool.execute(
        "UPDATE sky_tiles SET last_accessed_at = NOW() WHERE id = $1", tile_id
    )

    tier = row["storage_tier"]
    if tier in ("hot", "cold"):
        root = _tier_root(tier)
        if root is not None:
            path = root / row["local_relpath"]
            if path.exists():
                return FileResponse(path)

    if row["upstream_is_cdn"] and row["upstream_url"]:
        return RedirectResponse(row["upstream_url"], status_code=302)

    raise HTTPException(
        404,
        f"tile unavailable (tier={tier}, policy={row['storage_policy']}, no CDN fallback)",
    )
