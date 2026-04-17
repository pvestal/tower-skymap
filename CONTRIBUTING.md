# Contributing to tower-skymap

Thanks for your interest! This project is a personal sky-archive indexer, but
contributions that make it more useful for other self-hosters are very
welcome — especially new ingesters, survey integrations, and performance
improvements.

## Ways to contribute

| Kind | Examples | Difficulty |
|---|---|---|
| **New ingester** | Hubble Legacy Archive, Chandra, JWST MAST, SDSS SkyServer | Medium |
| **HiPS proxy cache** | nginx `proxy_cache_path` fronting CDS tile servers | Medium |
| **CLIP embedding worker** | Wire drain.py → Qdrant for visual similarity | Medium |
| **Vue frontend** | Search box, result grid, detail view, tile-strip | Medium |
| **Bug fixes / tests** | Anything flagged in issues | Any |
| **Docs improvements** | Clarify quickstart, add platform notes (macOS/WSL) | Beginner |

## Dev setup

```bash
git clone https://github.com/pvestal/tower-skymap.git /opt/skymap
cd /opt/skymap
./scripts/setup.sh                     # creates venv, installs q3c, creates DB
./scripts/smoke-test.sh                # verifies policies work end-to-end
```

Postgres 16+ with the `q3c` extension is required. On Ubuntu 24.04:

```bash
sudo apt install postgresql-16-q3c
```

Other platforms: see [segasai/q3c](https://github.com/segasai/q3c) for build
instructions.

## Code style

- **Python 3.12+**. Type hints on every public function signature.
- **FastAPI** conventions — async endpoints, Pydantic response models.
- **asyncpg** for DB access (never `psycopg`). Use the shared pool in
  `app/db.py` so the jsonb codec is consistent.
- **No raw SQL strings in endpoints** if the query is reusable — put it in a
  helper. Ad-hoc one-offs in endpoints are fine.
- **systemd units** belong in `systemd/` with paths that match the Linux FHS.
  Don't use `/home/<user>` in unit files — hard-code `/opt/skymap`.

## Adding an ingester

Copy `workers/apod_ingest.py` as a starting template. Every ingester must:

1. Fetch its own metadata (no shared HTTP client — keep them independently
   rate-limited)
2. `INSERT INTO sky_sources (...)` with a sensible `storage_policy`:
   - `mirror` for curated/daily/small archives you want forever
   - `thumb_only` for bulk archives where users only need thumbs locally
   - `proxy_only` for pre-rendered tile pyramids (HiPS-style)
3. Set `upstream_is_cdn=TRUE` only if the upstream URL is publicly
   redistributable and long-lived. When TRUE, the tile-serve path can 302
   to it after local eviction.
4. Include a matching `systemd/*.timer` with a `RandomizedDelaySec` of at
   least 5 min if the source is a public API (thundering-herd avoidance)

## Commit style

```
<type>(<scope>): <short imperative subject>

<Body explaining the "why" more than the "what". Reference
line numbers or commits when relevant. Hard-wrap at 78 cols.>

Co-Authored-By: ...  (only when applicable)
```

Types: `feat` · `fix` · `chore` · `docs` · `refactor` · `test` · `perf`

## Security

- **Never commit `.env`** — `.gitignore` enforces this but please double-check
  with `git status` before pushing.
- API keys, DB passwords, etc. belong in a secrets manager (HashiCorp Vault,
  `pass`, `1password-cli`, etc.). The `.env.example` template has only
  placeholders.
- If you find a vulnerability, please email rather than opening a public
  issue.

## License

By contributing, you agree that your contributions will be licensed under the
[MIT License](LICENSE).
