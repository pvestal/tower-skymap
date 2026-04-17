#!/usr/bin/env bash
# Read-only status inspector — modifies nothing.
set -uo pipefail

REPO=/opt/skymap
DB=sky_archive
DB_USER=patrick
PG_HOST=127.0.0.1

GRN='\033[1;32m' RED='\033[1;31m' YLW='\033[1;33m' NC='\033[0m'
yes() { printf "  ${GRN}✓${NC} %s\n" "$*"; }
no()  { printf "  ${RED}✗${NC} %s\n" "$*"; }
maybe() { printf "  ${YLW}?${NC} %s\n" "$*"; }

cd "$REPO" 2>/dev/null || { no "repo not at $REPO"; exit 1; }

echo "Filesystem:"
[[ -d venv ]]      && yes "venv"            || no "venv (run setup.sh)"
[[ -f .env ]]      && yes ".env"            || no ".env (run setup.sh)"
[[ -f .env ]] && { set -a; source .env; set +a; }

[[ -n "${SKYMAP_STORAGE_ROOT:-}"  && -w "${SKYMAP_STORAGE_ROOT:-/nonexistent}" ]] \
    && yes "hot storage writable: $SKYMAP_STORAGE_ROOT" \
    || no  "hot storage not writable: ${SKYMAP_STORAGE_ROOT:-<unset>}"

if [[ -n "${SKYMAP_COLD_STORAGE_ROOT:-}" ]]; then
    [[ -w "$SKYMAP_COLD_STORAGE_ROOT" ]] \
        && yes "cold storage writable: $SKYMAP_COLD_STORAGE_ROOT" \
        || no  "cold storage not writable: $SKYMAP_COLD_STORAGE_ROOT"
else
    maybe "cold storage disabled (SKYMAP_COLD_STORAGE_ROOT unset)"
fi

echo
echo "Packages:"
if dpkg -l postgresql-16-q3c 2>/dev/null | grep -q '^ii'; then yes "postgresql-16-q3c"
else no "postgresql-16-q3c (run setup.sh)"; fi

echo
echo "Database:"
if sudo -n -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB'" 2>/dev/null | grep -q 1; then
    yes "database $DB exists"
else
    no "database $DB missing (or sudo denied)"
fi

if [[ -n "${SKYMAP_DATABASE_URL:-}" ]]; then
    PW=$(python3 -c "import urllib.parse as u; print(u.unquote(u.urlparse('$SKYMAP_DATABASE_URL').password or ''))")
    PSQL=(psql -h "$PG_HOST" -U "$DB_USER" -d "$DB" -tAc)
    HAS_001=$(PGPASSWORD="$PW" "${PSQL[@]}" "SELECT to_regclass('sky_sources')" 2>/dev/null | tr -d '[:space:]')
    HAS_002=$(PGPASSWORD="$PW" "${PSQL[@]}" "SELECT 1 FROM information_schema.columns WHERE table_name='sky_sources' AND column_name='storage_policy'" 2>/dev/null | tr -d '[:space:]')
    [[ "$HAS_001" == "sky_sources" ]] && yes "migration 001" || no "migration 001"
    [[ "$HAS_002" == "1" ]]            && yes "migration 002" || no "migration 002"
fi

echo
echo "Systemd units:"
for u in tower-skymap.service \
         tower-skymap-ingest.timer  tower-skymap-ingest-nasa-iv.timer \
         tower-skymap-drain.timer   tower-skymap-tier-migrate.timer; do
    state=$(systemctl is-active "$u" 2>/dev/null || echo "unknown")
    enabled=$(systemctl is-enabled "$u" 2>/dev/null || echo "disabled")
    case "$state/$enabled" in
        active/enabled)          yes "$u (active, enabled)" ;;
        inactive/enabled|failed/*) no  "$u ($state, $enabled)" ;;
        *)                       maybe "$u ($state, $enabled)" ;;
    esac
done

echo
echo "Service:"
PORT="${SKYMAP_LISTEN_PORT:-8410}"
if H=$(curl -fsS --max-time 3 "http://127.0.0.1:$PORT/health" 2>/dev/null); then
    yes "/health on :$PORT"
    echo "$H" | python3 -m json.tool 2>/dev/null | sed 's/^/    /'
else
    no "/health unreachable on :$PORT"
fi
