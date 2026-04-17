from fastapi import APIRouter, HTTPException

from ..db import get_pool
from ..schemas import ConeQuery, HybridQuery, SemanticQuery, SourceOut

router = APIRouter(prefix="/search", tags=["search"])

_COLS = "id, source, source_id, title, caption, ra, dec, observed_at, upstream_url"


def _row_to_source(row) -> SourceOut:
    return SourceOut(**{k: row[k] for k in SourceOut.model_fields})


@router.post("/cone", response_model=list[SourceOut])
async def cone_search(q: ConeQuery) -> list[SourceOut]:
    pool = await get_pool()
    rows = await pool.fetch(
        f"""
        SELECT {_COLS}
          FROM sky_sources
         WHERE ra IS NOT NULL AND dec IS NOT NULL
           AND q3c_radial_query(ra, dec, $1, $2, $3)
         ORDER BY q3c_dist(ra, dec, $1, $2) ASC
         LIMIT $4
        """,
        q.ra, q.dec, q.radius_deg, q.limit,
    )
    return [_row_to_source(r) for r in rows]


@router.post("/semantic", response_model=list[SourceOut])
async def semantic_search(q: SemanticQuery) -> list[SourceOut]:
    pool = await get_pool()
    rows = await pool.fetch(
        f"""
        SELECT {_COLS}
          FROM sky_sources
         WHERE to_tsvector('english', coalesce(title,'') || ' ' || coalesce(caption,''))
               @@ plainto_tsquery('english', $1)
         ORDER BY ts_rank(
                    to_tsvector('english', coalesce(title,'') || ' ' || coalesce(caption,'')),
                    plainto_tsquery('english', $1)
                  ) DESC
         LIMIT $2
        """,
        q.q, q.limit,
    )
    return [_row_to_source(r) for r in rows]


@router.post("/hybrid", response_model=list[SourceOut])
async def hybrid_search(q: HybridQuery) -> list[SourceOut]:
    has_coord = q.ra is not None and q.dec is not None
    if not q.q and not has_coord:
        raise HTTPException(400, "hybrid search needs either q, or ra+dec")

    if q.q and has_coord:
        pool = await get_pool()
        radius = q.radius_deg or 1.0
        rows = await pool.fetch(
            f"""
            SELECT {_COLS}
              FROM sky_sources
             WHERE q3c_radial_query(ra, dec, $1, $2, $3)
               AND to_tsvector('english', coalesce(title,'') || ' ' || coalesce(caption,''))
                   @@ plainto_tsquery('english', $4)
             ORDER BY q3c_dist(ra, dec, $1, $2)
             LIMIT $5
            """,
            q.ra, q.dec, radius, q.q, q.limit,
        )
        return [_row_to_source(r) for r in rows]

    if q.q:
        return await semantic_search(SemanticQuery(q=q.q, limit=q.limit))

    return await cone_search(
        ConeQuery(ra=q.ra, dec=q.dec, radius_deg=q.radius_deg or 0.1, limit=q.limit)
    )
