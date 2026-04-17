#!/usr/bin/env bash
# End-to-end pipeline verification — runs real ingest + drain,
# then proves storage policies behaved correctly.
set -euo pipefail

REPO=/opt/skymap
DB=sky_archive
DB_USER=patrick
PG_HOST=127.0.0.1

cd "$REPO"
[[ -f .env ]] || { echo "no .env — run setup.sh first" >&2; exit 1; }
set -a; source .env; set +a

PW=$(python3 -c "import urllib.parse as u; print(u.unquote(u.urlparse('$SKYMAP_DATABASE_URL').password or ''))")
pg()  { PGPASSWORD="$PW" psql -h "$PG_HOST" -U "$DB_USER" -d "$DB" "$@"; }

echo "=== 1. APOD ingest (mirror policy, 3 days) ==="
./venv/bin/python -m workers.apod_ingest 3

echo
echo "=== 2. NASA IVL ingest (thumb_only policy, 1 query) ==="
./venv/bin/python -m workers.nasa_iv_ingest "andromeda"

echo
echo "=== 3. Drain 30 jobs ==="
./venv/bin/python -m workers.drain 30

echo
echo "=== 4. Policy verification (sources × tiles) ==="
pg -c "
SELECT s.source, s.storage_policy,
       count(DISTINCT s.id)                           AS sources,
       count(t.id) FILTER (WHERE t.kind='raw')        AS raw_tiles,
       count(t.id) FILTER (WHERE t.kind='thumb')      AS thumb_tiles,
       pg_size_pretty(coalesce(sum(t.bytes),0))       AS total_bytes
  FROM sky_sources s
  LEFT JOIN sky_tiles t ON t.source_id=s.id
 GROUP BY s.source, s.storage_policy
 ORDER BY s.source;
"

echo
echo "=== 5. Tier distribution ==="
pg -c "
SELECT storage_tier, kind, count(*) AS tiles,
       pg_size_pretty(coalesce(sum(bytes),0)) AS size
  FROM sky_tiles
 GROUP BY storage_tier, kind
 ORDER BY storage_tier, kind;
"

echo
echo "=== 6. On-disk byte check ==="
HOT="$SKYMAP_STORAGE_ROOT"
if [[ -d "$HOT" ]]; then
    RAW_COUNT=$(find "$HOT/raw" -type f 2>/dev/null | wc -l)
    THUMB_COUNT=$(find "$HOT/thumbs" -type f 2>/dev/null | wc -l)
    printf "  raw files on disk:   %s\n" "$RAW_COUNT"
    printf "  thumb files on disk: %s\n" "$THUMB_COUNT"
    APOD_RAW=$(find "$HOT/raw/apod" -type f 2>/dev/null | wc -l)
    NASA_RAW=$(find "$HOT/raw/nasa_iv" -type f 2>/dev/null | wc -l)
    printf "    apod raw:     %s (should be > 0 — mirror policy)\n" "$APOD_RAW"
    printf "    nasa_iv raw:  %s (should be 0 — thumb_only deletes raw)\n" "$NASA_RAW"
    if (( NASA_RAW == 0 )) && (( APOD_RAW > 0 )); then
        printf "\n  \033[1;32m✓ policies honored on disk\033[0m\n"
    else
        printf "\n  \033[1;31m✗ policy mismatch — check workers/drain.py logic\033[0m\n"
        exit 1
    fi
fi

echo
echo "=== 7. /health ==="
curl -fsS "http://127.0.0.1:$SKYMAP_LISTEN_PORT/health" | python3 -m json.tool
