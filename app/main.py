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
<title>Tower Skymap · {n_sources} imagery · {n_objects} catalog</title>
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
  .section-title {{
    font-size: 13px; text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--muted); margin: 0 0 12px 0; font-weight: 600;
  }}
  .section-title .count {{
    color: var(--text); background: var(--panel); padding: 2px 8px;
    border-radius: 10px; margin-left: 6px; font-size: 11px;
  }}
  .catalog-strip {{
    display: flex; gap: 10px; overflow-x: auto; padding-bottom: 12px;
    margin-bottom: 24px; scrollbar-width: thin;
  }}
  .chip {{
    flex: 0 0 auto; background: var(--panel); border: 1px solid var(--border);
    border-radius: 10px; padding: 10px 14px; min-width: 180px;
    display: flex; flex-direction: column; gap: 4px;
    transition: border-color 0.15s, transform 0.15s;
    text-decoration: none; color: inherit;
  }}
  .chip:hover {{ transform: translateY(-2px); border-color: var(--accent); }}
  .chip-active {{
    border-color: var(--accent) !important;
    background: linear-gradient(135deg, #1e2a4a 0%, var(--panel) 100%);
    box-shadow: 0 0 0 1px var(--accent) inset;
  }}
  .object-banner {{
    background: linear-gradient(90deg, #1a2845 0%, var(--panel) 100%);
    border: 1px solid var(--accent); border-radius: 12px;
    padding: 16px 20px; margin-bottom: 20px;
    display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
  }}
  .object-banner .obj-id {{
    font-family: ui-monospace, monospace; font-weight: 700; font-size: 18px;
    color: var(--accent);
  }}
  .object-banner .obj-name {{ font-size: 18px; font-weight: 600; }}
  .object-banner .obj-meta {{ color: var(--muted); font-size: 13px; }}
  .object-banner a.clear {{
    margin-left: auto; color: var(--muted); text-decoration: none;
    font-size: 13px; padding: 4px 10px; border: 1px solid var(--border);
    border-radius: 6px;
  }}
  .object-banner a.clear:hover {{ border-color: var(--accent); color: var(--text); }}
  .empty-for-object {{
    padding: 40px 20px; text-align: center; color: var(--muted);
    background: var(--panel); border: 1px dashed var(--border); border-radius: 12px;
    margin-bottom: 24px;
  }}
  .chip-head {{ display: flex; align-items: baseline; gap: 8px; }}
  .chip-id {{
    font-family: ui-monospace, monospace; font-size: 12px; font-weight: 600;
    padding: 2px 8px; border-radius: 6px; color: #fff;
  }}
  .chip-id.messier  {{ background: #6644aa; }}
  .chip-id.caldwell {{ background: #aa6644; }}
  .chip-cst {{ font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }}
  .chip-name {{ font-size: 13px; font-weight: 500; line-height: 1.3; }}
  .chip-meta {{ font-size: 11px; color: var(--muted); font-family: ui-monospace, monospace; }}
  footer {{ margin-top: 40px; color: var(--muted); font-size: 12px; text-align: center; }}
  footer a {{ color: var(--accent); text-decoration: none; }}
  footer a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
<header>
  <h1><span class="logo">◉</span> tower-skymap</h1>
  <div class="stats">
    <strong>{n_sources}</strong> imagery
    <span class="sep">·</span>
    <strong>{n_objects}</strong> catalog
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

{catalog_section}

{object_banner}

<div class="section-title">Imagery <span class="count">{imagery_count_label}</span></div>

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
async def gallery(q: str = "", obj: str = "", limit: int = 60) -> HTMLResponse:
    pool = await get_pool()
    active_object = None
    async with pool.acquire() as conn:
        if obj:
            active_object = await conn.fetchrow(
                """
                SELECT catalog_id, name, designations, common_names, obj_type,
                       magnitude, size_arcmin, constellation, catalog_source,
                       ra, dec
                  FROM sky_objects
                 WHERE catalog_id = $1
                """,
                obj,
            )
            if active_object:
                # Only match aliases that are specific enough to avoid false positives.
                # Drop <4-char aliases (M31, M45, C92) — too likely to appear
                # accidentally in archive IDs or PIA numbers. Keep the longer
                # common names which are unambiguous astronomy terms.
                aliases = [a for a in (list(active_object["designations"])
                                       + list(active_object["common_names"]))
                           if a and len(a) >= 4]
                if not aliases:
                    rows = []
                else:
                    rows = await conn.fetch(
                        """
                        SELECT s.id, s.source, s.source_id, s.title, s.storage_policy,
                               s.upstream_url,
                               (SELECT id FROM sky_tiles t
                                 WHERE t.source_id = s.id AND t.kind='thumb' LIMIT 1) AS thumb_id
                          FROM sky_sources s
                         WHERE s.title ILIKE ANY($1)
                         ORDER BY s.id DESC
                         LIMIT $2
                        """,
                        [f"%{a}%" for a in aliases], limit,
                    )
            else:
                rows = []
        elif q:
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
        n_objects = await conn.fetchval("SELECT count(*) FROM sky_objects")

        catalog_rows = await conn.fetch(
            """
            SELECT catalog_id, name, obj_type, constellation,
                   magnitude, size_arcmin, catalog_source
              FROM sky_objects
             ORDER BY magnitude NULLS LAST
             LIMIT 12
            """
        )

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

    if catalog_rows:
        chips = []
        for r in catalog_rows:
            mag = f"mag {r['magnitude']:.1f}" if r['magnitude'] is not None else "—"
            size = f"· {r['size_arcmin']:.0f}'" if r['size_arcmin'] else ""
            is_active = active_object is not None and active_object["catalog_id"] == r["catalog_id"]
            active_cls = " chip-active" if is_active else ""
            chips.append(
                f'<a class="chip{active_cls}" href="/?obj={escape(r["catalog_id"])}">'
                f'  <div class="chip-head">'
                f'    <span class="chip-id {escape(r["catalog_source"])}">{escape(r["catalog_id"])}</span>'
                f'    <span class="chip-cst">{escape(r["constellation"] or "")}</span>'
                f'  </div>'
                f'  <div class="chip-name">{escape(r["name"])}</div>'
                f'  <div class="chip-meta">{escape(r["obj_type"] or "")} · {mag} {size}</div>'
                f'</a>'
            )
        catalog_section = (
            f'<div class="section-title">Catalog <span class="count">{n_objects}</span> '
            f'<span style="text-transform:none;letter-spacing:0;font-weight:400;color:var(--muted);">'
            f'— brightest first · click to filter imagery</span></div>'
            f'<div class="catalog-strip">{"".join(chips)}</div>'
        )
    else:
        catalog_section = ""

    if active_object:
        mag = (f"mag {active_object['magnitude']:.1f}"
               if active_object['magnitude'] is not None else "")
        size = (f"{active_object['size_arcmin']:.0f}' across"
                if active_object['size_arcmin'] else "")
        aliases_str = ", ".join(list(active_object["common_names"])
                                + [d for d in active_object["designations"]
                                   if d != active_object["catalog_id"]])
        meta_bits = [b for b in (active_object["obj_type"],
                                 active_object["constellation"],
                                 mag, size) if b]
        object_banner = (
            f'<div class="object-banner">'
            f'  <span class="obj-id">{escape(active_object["catalog_id"])}</span>'
            f'  <span class="obj-name">{escape(active_object["name"])}</span>'
            f'  <span class="obj-meta">{escape(" · ".join(meta_bits))}</span>'
            f'  <span class="obj-meta">{escape(f"also: {aliases_str}") if aliases_str else ""}</span>'
            f'  <a class="clear" href="/">clear ×</a>'
            f'</div>'
        )
        imagery_count_label = str(len(rows))
        if not rows:
            grid = (
                f'<div class="empty-for-object">'
                f'No NASA imagery indexed for <b>{escape(active_object["name"])}</b> yet. '
                f'Try a different object, or run<br>'
                f'<code>python -m workers.nasa_iv_ingest "{escape(active_object["name"])}"</code>'
                f'</div>'
            )
    else:
        object_banner = ""
        imagery_count_label = str(n_sources)

    return HTMLResponse(GALLERY_HTML.format(
        n_sources=n_sources,
        n_objects=n_objects,
        n_tiles=n_tiles,
        hot_free_gb=hot["free_gb"] / 1000,
        cold_free_gb=cold["free_gb"] / 1000,
        q=escape(q),
        catalog_section=catalog_section,
        object_banner=object_banner,
        imagery_count_label=imagery_count_label,
        grid=grid,
    ))
