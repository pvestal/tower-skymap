# tower-skymap

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.136-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PostgreSQL 16](https://img.shields.io/badge/PostgreSQL-16-336791?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![q3c](https://img.shields.io/badge/q3c-sky%20indexing-663399)](https://github.com/segasai/q3c)
[![NASA APIs](https://img.shields.io/badge/NASA-APOD%20%7C%20IVL-0B3D91?logo=nasa&logoColor=white)](https://api.nasa.gov/)
[![systemd](https://img.shields.io/badge/systemd-timer%20driven-d33847)](https://systemd.io/)
[![Status: MVP](https://img.shields.io/badge/status-MVP%20live-brightgreen)](https://github.com/pvestal/tower-skymap)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)
[![Linux](https://img.shields.io/badge/platform-linux-informational?logo=linux&logoColor=white)](#)

A browsable, searchable **NASA/astronomy sky-image archive**. Indexes imagery
by sky coordinates (RA/Dec, via the [q3c](https://github.com/segasai/q3c)
Postgres extension) and caches strategically across hot/cold storage tiers
with a CDN-fallback pattern, so the local disk footprint stays tiny while
the archive *feels* unbounded.

> **Status:** MVP live. APOD + NASA Image & Video Library ingesters working.
> Semantic search (CLIP → Qdrant) and HiPS proxy cache are roadmap items.

**Contributing:** see [CONTRIBUTING.md](CONTRIBUTING.md). PRs for new ingesters
(Hubble, JWST, Chandra, SDSS), HiPS proxy cache, CLIP embedding worker, or a
Vue frontend are especially welcome.

---

## Why

Sky surveys are huge — SDSS is 100+ TB, Pan-STARRS 400+ TB of HiPS tiles alone.
Mirroring is pointless when NASA/ESA/CDS already run public tile servers with
permissive redistribution terms. The right architecture treats upstream as a
CDN, mirrors only what you curate or view, and evicts cold bytes to cheap
storage or to nothing (re-fetched on demand from upstream).

On a 10 TB drive this design runs for 100,000+ years before filling, because
metadata + thumbs are ~3% of raw image size, and raws are optional.

---

## Architecture

```mermaid
flowchart LR
    subgraph upstream[Upstream Archives]
        APOD[NASA APOD<br/>api.nasa.gov]
        IVL[NASA Image & Video<br/>images-api.nasa.gov]
        ESA[ESA Sky HiPS<br/>cds.unistra.fr]
    end

    subgraph ingest[Ingesters · hourly/daily]
        A1[apod_ingest.py]
        A2[nasa_iv_ingest.py]
        A3[hips_cutout.py · future]
    end

    subgraph db[Postgres · sky_archive]
        S[sky_sources<br/>metadata + policy]
        Q[sky_tile_queue<br/>download jobs]
        T[sky_tiles<br/>file locations + tier]
    end

    subgraph workers[Drain + Tier Migrate]
        D[drain.py<br/>every 60s]
        M[tier_migrate.py<br/>weekly Sun 03:00]
    end

    subgraph disk[Storage]
        HOT[/mnt/10TB2/skymap<br/>HOT tier/]
        COLD[/mnt/20TB/skymap-cold<br/>COLD tier/]
    end

    subgraph api[FastAPI · :8410]
        API1[/search]
        API2[/image/:id]
        API3[/image/tile/:id/file]
        API4[/watchlist]
    end

    APOD --> A1
    IVL  --> A2
    ESA  --> A3

    A1 --> S --> Q
    A2 --> S
    A3 --> S

    Q --> D
    D --> HOT
    D --> T

    HOT -- ">90d unread" --> M --> COLD
    COLD -- "read hit" --> API3

    S --> API1 & API2
    T --> API3
    API3 -. "302 redirect on miss" .-> upstream

    style upstream fill:#1e3a5f,stroke:#6495ed,color:#fff
    style disk fill:#2d5f3f,stroke:#70c090,color:#fff
    style api fill:#5f3f1e,stroke:#c09060,color:#fff
```

### Storage policies

Every source has one of three policies. The drain worker honors the policy
when processing download jobs.

```mermaid
flowchart TD
    Start([source row created]) --> Q{storage_policy?}
    Q -->|mirror| M[Download raw<br/>Generate thumb<br/>Keep BOTH on disk]
    Q -->|thumb_only| T[Download raw<br/>Generate thumb<br/>DELETE raw]
    Q -->|proxy_only| P[Skip download<br/>Metadata only]

    M --> MOut[raw+thumb tiles<br/>tier=hot]
    T --> TOut[thumb tile only<br/>tier=hot]
    P --> POut[no tiles<br/>upstream_url served via 302]

    style M fill:#2d5f3f,color:#fff
    style T fill:#5f5f2d,color:#fff
    style P fill:#5f2d2d,color:#fff
```

| Policy | Disk cost | Use for |
|---|---|---|
| `mirror` | ~5 MB/item | Curated daily picks (APOD). You want everything forever. |
| `thumb_only` | ~60 KB/item | Bulk searchable corpora (NASA IVL, Hubble archive). User views trigger upstream fetch. |
| `proxy_only` | 0 bytes | Pre-rendered tile pyramids (HiPS). Nginx fronts the upstream tile server. |

### Tile serving — hot → cold → CDN fallback

When a client requests `/image/tile/:id/file`, the service checks tiers in
order of speed and falls back gracefully:

```mermaid
flowchart LR
    REQ[GET /image/tile/42/file] --> BUMP[UPDATE last_accessed_at]
    BUMP --> CHECK{tier?}

    CHECK -->|hot| H{file on disk?}
    CHECK -->|cold| C{file on disk?}
    CHECK -->|evicted| E{is_cdn?}

    H -->|yes| SERVE[FileResponse]
    H -->|no| E
    C -->|yes| SERVE
    C -->|no| E

    E -->|yes| REDIR[302 → upstream URL]
    E -->|no| FAIL[404 tile unavailable]

    style SERVE fill:#2d5f3f,color:#fff
    style REDIR fill:#2d4f5f,color:#fff
    style FAIL fill:#5f2d2d,color:#fff
```

The `last_accessed_at` bump makes promotion an emergent property: a cold tile
viewed this week simply doesn't get demoted again in next week's tier
migration. No explicit "promote" code path.

---

## Quickstart

### 1. Get a NASA API key (2 minutes, free)

The NASA APOD endpoint is rate-limited. Without a key you get `DEMO_KEY`, which
shares a 30 req/hour / 50 req/day quota with every other anonymous caller on
the internet — you'll see 429/503s within an hour. A personal key gets 1000
req/hour, plenty for this service's hourly APOD poll plus on-demand queries.

1. Browse to **https://api.nasa.gov/**
2. Fill the **Generate API Key** form:
   - First Name, Last Name, Email (required)
   - "How will you use the APIs?" — free-text, anything like "personal sky image archive indexer" is fine
3. Submit. The key arrives **immediately on the next page** and also by email.
4. Save it in `/opt/skymap/.env` as `SKYMAP_NASA_API_KEY=<your-key>`
5. Restart: `sudo systemctl restart tower-skymap`

The NASA Image & Video Library (used by the `nasa_iv` ingester) does **not**
require a key — it's a separate service at `images-api.nasa.gov` with its own
rate limits and no auth requirement.

### 2. Install

```bash
cd /opt/skymap
./scripts/setup.sh
```

The script is idempotent — safe to re-run. It will:

- Create a Python venv and install `requirements.txt`
- Prompt once for your Postgres password + NASA key (writes `.env` with
  mode 600) — or use `DEMO_KEY` by hitting enter
- Install `postgresql-16-q3c` via apt
- Create the `sky_archive` database (owned by the patrick role)
- Create the `q3c` extension (needs superuser — handled via `sudo -u postgres`)
- Apply both migrations
- Create `/mnt/10TB2/skymap/` hot-tier dirs
- Create `/mnt/20TB/skymap-cold/` cold-tier dir (sudo)
- Install 9 systemd units to `/etc/systemd/system/`
- Enable and start the service + 4 timers
- Smoke-test `/health` on port 8410

### 3. Verify

```bash
./scripts/status.sh     # read-only diagnostic
./scripts/smoke-test.sh # forces APOD + IVL ingest, drains 30 jobs, verifies policies
```

The smoke test asserts that `apod` sources have raw files on disk (mirror
policy) while `nasa_iv` sources have zero raws (thumb_only policy deleted
them after thumbnailing). If the assertion fails, policy machinery is broken.

---

## API

Base URL: `http://127.0.0.1:8410` (or `https://<tower>/api/skymap/` behind nginx — see below).

| Route | Description |
|---|---|
| `GET /health` | DB + queue + per-tier tile counts + disk usage |
| `GET /search/text?q=galaxy` | Full-text search over title/caption/metadata |
| `GET /search/cone?ra=10.68&dec=41.27&radius_arcmin=30` | q3c-indexed cone search (requires RA/Dec on sources) |
| `GET /search/semantic?q=...` | CLIP similarity (future) |
| `GET /image/{source_id}` | Source row + its tiles |
| `GET /image/tile/{tile_id}/file` | Raw bytes (hot/cold FS) or 302 to upstream |
| `GET /watchlist` · `POST /watchlist` | User-curated target list |

---

## Scripts

| Script | Purpose | Idempotent? |
|---|---|---|
| `scripts/setup.sh` | One-shot installer; prompts for secrets only on first run | ✅ |
| `scripts/status.sh` | Read-only diagnostic — filesystem, DB, units, `/health` | ✅ |
| `scripts/smoke-test.sh` | End-to-end: forces ingest + drain, verifies storage policies honored on disk | ✅ |

---

## LAN exposure

Skymap binds to `127.0.0.1:8410` by default (safer). To expose it on the LAN
via the existing Tower nginx vhost, paste `nginx/skymap.location.conf` into
`/etc/nginx/sites-available/tower-https` inside the `server { listen 443 }`
block alongside the other `/api/*` locations:

```bash
sudo $EDITOR /etc/nginx/sites-available/tower-https
sudo nginx -t && sudo systemctl reload nginx
```

Then `https://<tower>/api/skymap/health` is LAN-reachable. CORS is enabled
for browser clients.

---

## Directory layout

```
/opt/skymap/
├── app/                 FastAPI service
│   ├── config.py        Settings (reads .env)
│   ├── db.py            asyncpg pool with jsonb codec
│   ├── main.py          lifespan + /health
│   ├── schemas.py       Pydantic models
│   └── routes/
│       ├── search.py    text + cone + semantic
│       ├── images.py    source detail + tile file (hot→cold→CDN fallback)
│       └── watchlist.py user-curated targets
├── workers/
│   ├── apod_ingest.py    NASA APOD (hourly)
│   ├── nasa_iv_ingest.py NASA IVL (daily)
│   ├── drain.py          Queue processor (60s)
│   └── tier_migrate.py   Hot → cold mover (weekly)
├── migrations/
│   ├── 001_init.sql      Schema + q3c + tables
│   └── 002_storage_policy.sql  storage_policy/tier columns
├── systemd/              9 units (1 service + 4 timers + 4 helpers)
├── scripts/              setup · status · smoke-test
├── nginx/                LAN-exposure snippet
└── .env.example          Configuration template
```

## Storage tiers on disk

```
/mnt/10TB2/skymap/                    HOT — recent, frequently accessed
├── raw/apod/2026-04-17.jpg           (full-res, mirror policy)
├── thumbs/apod/2026-04-17.jpg        (256px JPEG)
├── thumbs/nasa_iv/...jpg             (thumb_only — no raw kept)
└── cutouts/                          (future: ESA Sky cutouts)

/mnt/20TB/skymap-cold/                COLD — demoted after 90 days unread
└── raw/apod/2025-*.jpg               (moved by tier_migrate.py)
```

Files in `raw/` and `thumbs/` mirror the `sky_tiles.local_relpath` column; the
DB is authoritative for which tier a tile currently lives in, and the file
path follows.

---

## Configuration reference (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `SKYMAP_DATABASE_URL` | — | `postgresql://user:pass@host:port/sky_archive` |
| `SKYMAP_STORAGE_ROOT` | `/mnt/10TB2/skymap` | Hot-tier root |
| `SKYMAP_COLD_STORAGE_ROOT` | `/mnt/20TB/skymap-cold` | Cold-tier root (unset disables demotion) |
| `SKYMAP_HOT_RETENTION_DAYS` | `90` | Un-accessed age before demotion |
| `SKYMAP_LISTEN_HOST` | `127.0.0.1` | Bind address |
| `SKYMAP_LISTEN_PORT` | `8410` | Bind port |
| `SKYMAP_NASA_API_KEY` | `DEMO_KEY` | NASA APOD key (see §1 above) |
| `SKYMAP_QDRANT_URL` | `http://127.0.0.1:6333` | Qdrant (semantic search, future) |
| `SKYMAP_QDRANT_COLLECTION` | `sky_embeddings` | Collection name |

---

## Roadmap

- [ ] CLIP ViT-B-32 encoder in `drain.py` → Qdrant upsert → semantic search endpoint
- [ ] ESA Sky HiPS cutout ingester (`hips_cutout.py`) — generate N arcmin FITS around targets
- [ ] HiPS tile proxy cache — nginx `proxy_cache_path` fronting CDS tile servers, effectively making Tower a regional HiPS mirror at zero disk cost
- [ ] Vue frontend — search box, result grid, detail view, "same region over time" tile strip
- [ ] Auth — bearer token or reuse tower_auth session cookies for `/watchlist` writes
- [ ] Prometheus metrics export

---

## License

MIT — see [LICENSE](LICENSE).

---

## Topics

`astronomy` · `nasa` · `nasa-api` · `apod` · `sky-survey` · `image-archive` ·
`fastapi` · `python` · `postgresql` · `q3c` · `asyncpg` · `self-hosted` ·
`systemd` · `qdrant` · `clip` · `hips` · `tower-server`
