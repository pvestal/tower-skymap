from fastapi import APIRouter, HTTPException

from ..db import get_pool
from ..schemas import ObjectIn

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


@router.get("")
async def list_objects() -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT id, name, ra, dec, obj_type, catalog_id, notes FROM sky_objects ORDER BY name"
    )
    return [dict(r) for r in rows]


@router.post("")
async def upsert_object(obj: ObjectIn) -> dict:
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO sky_objects (name, ra, dec, obj_type, catalog_id, notes)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (name) DO UPDATE
          SET ra = EXCLUDED.ra,
              dec = EXCLUDED.dec,
              obj_type = EXCLUDED.obj_type,
              catalog_id = EXCLUDED.catalog_id,
              notes = EXCLUDED.notes
        RETURNING id, name, ra, dec, obj_type, catalog_id, notes
        """,
        obj.name, obj.ra, obj.dec, obj.obj_type, obj.catalog_id, obj.notes,
    )
    return dict(row)


@router.delete("/{obj_id}")
async def delete_object(obj_id: int) -> dict:
    pool = await get_pool()
    result = await pool.execute("DELETE FROM sky_objects WHERE id = $1", obj_id)
    if result == "DELETE 0":
        raise HTTPException(404)
    return {"deleted": obj_id}


@router.get("/{obj_id}/timeline")
async def object_timeline(obj_id: int) -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT o.id AS observation_id, o.observed_at,
               t.id AS tile_id, t.local_relpath, t.kind, t.source_id
          FROM sky_observations o
          JOIN sky_tiles t ON t.id = o.tile_id
         WHERE o.object_id = $1
         ORDER BY o.observed_at DESC NULLS LAST
        """,
        obj_id,
    )
    return [dict(r) for r in rows]
