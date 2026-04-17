import shutil
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import settings
from .db import close_pool, get_pool
from .routes import images, search, watchlist


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()
    yield
    await close_pool()


app = FastAPI(title="Tower Skymap", version="0.1.0", lifespan=lifespan)
app.include_router(search.router)
app.include_router(images.router)
app.include_router(watchlist.router)


def _disk_usage(path):
    if path is None or not path.exists():
        return None
    u = shutil.disk_usage(path)
    return {"total_gb": round(u.total / 1e9, 1),
            "used_gb": round(u.used / 1e9, 1),
            "free_gb": round(u.free / 1e9, 1)}


@app.get("/health")
async def health() -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        n_sources = await conn.fetchval("SELECT count(*) FROM sky_sources")
        tier_counts = await conn.fetch(
            """
            SELECT storage_tier, kind, count(*) AS n, coalesce(sum(bytes), 0) AS bytes
              FROM sky_tiles
             GROUP BY storage_tier, kind
            """
        )
        policy_counts = await conn.fetch(
            "SELECT storage_policy, count(*) AS n FROM sky_sources GROUP BY storage_policy"
        )
        n_queue = await conn.fetchval(
            "SELECT count(*) FROM sky_tile_queue WHERE status IN ('pending','failed')"
        )

    return {
        "status": "ok",
        "sources": n_sources,
        "queue_pending": n_queue,
        "policies": {r["storage_policy"]: r["n"] for r in policy_counts},
        "tiers": [
            {"tier": r["storage_tier"], "kind": r["kind"], "count": r["n"], "bytes": r["bytes"]}
            for r in tier_counts
        ],
        "disk": {
            "hot": _disk_usage(settings.storage_root),
            "cold": _disk_usage(settings.cold_storage_root),
        },
    }
