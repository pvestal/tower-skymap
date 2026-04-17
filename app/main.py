import shutil
from contextlib import asynccontextmanager
from html import escape

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

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


GALLERY_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tower Skymap · {n_sources} indexed</title>
<style>
  :root {{
    --bg: #0a0d14;
    --panel: #141925;
    --text: #e4e8f0;
    --muted: #8892a8;
    --accent: #6ea8ff;
    --mirror: #3a7a4f;
    --thumb_only: #7a5a2a;
    --proxy_only: #7a3a3a;
    --border: #252a38;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 24px 32px;
    font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    background: radial-gradient(ellipse at top, #151a2b 0%, var(--bg) 70%);
    color: var(--text); min-height: 100vh;
  }}
  header {{ display: flex; align-items: baseline; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }}
  h1 {{ margin: 0; font-size: 28px; font-weight: 600; letter-spacing: -0.02em; }}
  h1 .logo {{ color: var(--accent); }}
  .stats {{ color: var(--muted); font-size: 14px; }}
  .stats strong {{ color: var(--text); font-weight: 600; }}
  .stats .sep {{ opacity: 0.4; margin: 0 8px; }}
  .search {{
    margin-left: auto; display: flex; gap: 8px;
  }}
  .search input {{
    background: var(--panel); border: 1px solid var(--border); color: var(--text);
    padding: 8px 14px; border-radius: 8px; font-size: 14px; width: 280px;
    outline: none; transition: border-color 0.15s;
  }}
  .search input:focus {{ border-color: var(--accent); }}
  .search button {{
    background: var(--accent); border: none; color: #0a0d14; font-weight: 600;
    padding: 8px 16px; border-radius: 8px; cursor: pointer; font-size: 14px;
  }}
  .search button:hover {{ filter: brightness(1.1); }}
  .grid {{
    display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 16px;
  }}
  .card {{
    background: var(--panel); border: 1px solid var(--border); border-radius: 12px;
    overflow: hidden; transition: transform 0.15s, border-color 0.15s;
    display: flex; flex-direction: column;
    text-decoration: none; color: inherit;
  }}
  .card:hover {{ transform: translateY(-2px); border-color: var(--accent); }}
  .thumb {{
    aspect-ratio: 16/9; background: #000 center/contain no-repeat; position: relative;
  }}
  .thumb.placeholder {{
    background: linear-gradient(135deg, #1a2040 0%, #0a0d14 100%);
    display: flex; align-items: center; justify-content: center; color: var(--muted); font-size: 12px;
  }}
  .badges {{
    position: absolute; top: 8px; left: 8px; display: flex; gap: 6px;
  }}
  .badge {{
    font-size: 10px; font-weight: 600; padding: 3px 8px; border-radius: 10px;
    text-transform: uppercase; letter-spacing: 0.03em; color: #fff;
    backdrop-filter: blur(4px);
  }}
  .badge.source {{ background: rgba(110, 168, 255, 0.85); }}
  .badge.mirror {{ background: rgba(58, 122, 79, 0.9); }}
  .badge.thumb_only {{ background: rgba(122, 90, 42, 0.9); }}
  .badge.proxy_only {{ background: rgba(122, 58, 58, 0.9); }}
  .meta {{ padding: 12px 14px; flex: 1; display: flex; flex-direction: column; }}
  .title {{
    font-size: 14px; font-weight: 500; line-height: 1.35;
    overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
    margin-bottom: 8px;
  }}
  .source-id {{
    font-size: 11px; color: var(--muted); font-family: ui-monospace, monospace;
    margin-top: auto;
  }}
  .empty {{
    text-align: center; padding: 80px 0; color: var(--muted);
  }}
  footer {{ margin-top: 40px; color: var(--muted); font-size: 12px; text-align: center; }}
  footer a {{ color: var(--accent); text-decoration: none; }}
  footer a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
<header>
  <h1><span class="logo">◉</span> tower-skymap</h1>
  <div class="stats">
    <strong>{n_sources}</strong> sources
    <span class="sep">·</span>
    <strong>{n_tiles}</strong> tiles
    <span class="sep">·</span>
    <strong>{hot_free_gb:.1f} TB</strong> hot free
    <span class="sep">·</span>
    <strong>{cold_free_gb:.1f} TB</strong> cold free
  </div>
  <form class="search" action="/" method="get">
    <input name="q" placeholder="search titles + captions…" value="{q}">
    <button type="submit">search</button>
  </form>
</header>

{grid}

<footer>
  <a href="/docs">/docs</a> ·
  <a href="/health">/health</a> ·
  <a href="https://github.com/pvestal/tower-skymap">github</a>
</footer>
</body>
</html>"""


CARD_HTML = """<a href="{upstream}" target="_blank" class="card">
  <div class="thumb"{bg_style}>
    <div class="badges">
      <span class="badge source">{source}</span>
      <span class="badge {policy}">{policy}</span>
    </div>
    {placeholder}
  </div>
  <div class="meta">
    <div class="title">{title}</div>
    <div class="source-id">{source_id}</div>
  </div>
</a>"""


@app.get("/", response_class=HTMLResponse)
async def gallery(q: str = "", limit: int = 60) -> HTMLResponse:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if q:
            rows = await conn.fetch(
                """
                SELECT s.id, s.source, s.source_id, s.title, s.storage_policy,
                       s.upstream_url,
                       (SELECT id FROM sky_tiles t
                         WHERE t.source_id = s.id AND t.kind='thumb' LIMIT 1) AS thumb_id
                  FROM sky_sources s
                 WHERE to_tsvector('english', coalesce(s.title,'') || ' ' || coalesce(s.caption,''))
                       @@ plainto_tsquery('english', $1)
                 ORDER BY ts_rank(
                     to_tsvector('english', coalesce(s.title,'') || ' ' || coalesce(s.caption,'')),
                     plainto_tsquery('english', $1)) DESC
                 LIMIT $2
                """,
                q, limit,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT s.id, s.source, s.source_id, s.title, s.storage_policy,
                       s.upstream_url,
                       (SELECT id FROM sky_tiles t
                         WHERE t.source_id = s.id AND t.kind='thumb' LIMIT 1) AS thumb_id
                  FROM sky_sources s
                 ORDER BY s.ingested_at DESC
                 LIMIT $1
                """,
                limit,
            )

        n_sources = await conn.fetchval("SELECT count(*) FROM sky_sources")
        n_tiles = await conn.fetchval("SELECT count(*) FROM sky_tiles")

    hot = _disk_usage(settings.storage_root) or {"free_gb": 0}
    cold = _disk_usage(settings.cold_storage_root) or {"free_gb": 0}

    if rows:
        cards = []
        for r in rows:
            thumb_id = r["thumb_id"]
            if thumb_id:
                bg_style = f' style="background-image:url(/image/tile/{thumb_id}/file)"'
                placeholder = ""
            else:
                bg_style = ""
                placeholder = '<div class="placeholder" style="position:absolute;inset:0">queued</div>'

            cards.append(CARD_HTML.format(
                upstream=escape(r["upstream_url"] or "#"),
                bg_style=bg_style,
                placeholder=placeholder,
                source=escape(r["source"]),
                policy=escape(r["storage_policy"]),
                title=escape((r["title"] or r["source_id"])[:140]),
                source_id=escape(r["source_id"]),
            ))
        grid = f'<div class="grid">{"".join(cards)}</div>'
    else:
        grid = '<div class="empty">No results. Try a different search term.</div>'

    return HTMLResponse(GALLERY_HTML.format(
        n_sources=n_sources,
        n_tiles=n_tiles,
        hot_free_gb=hot["free_gb"] / 1000,
        cold_free_gb=cold["free_gb"] / 1000,
        q=escape(q),
        grid=grid,
    ))
