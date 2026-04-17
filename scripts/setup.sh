#!/usr/bin/env bash
# Tower Skymap — idempotent one-shot installer.
# Safe to re-run: every step detects completion and skips.
set -euo pipefail

REPO=/opt/skymap
DB=sky_archive
DB_USER=patrick
PG_HOST=127.0.0.1

BLU='\033[1;34m' GRN='\033[1;32m' YLW='\033[1;33m' RED='\033[1;31m' NC='\033[0m'
say()  { printf "${BLU}[skymap]${NC} %s\n" "$*"; }
ok()   { printf "${GRN}[ok]${NC}     %s\n" "$*"; }
warn() { printf "${YLW}[warn]${NC}   %s\n" "$*" >&2; }
die()  { printf "${RED}[fail]${NC}   %s\n" "$*" >&2; exit 1; }

cd "$REPO" || die "repo not found at $REPO"
command -v python3 >/dev/null || die "python3 required"
command -v psql    >/dev/null || die "psql required"

say "will need sudo for: apt, createdb, mkdir on /mnt/20TB, systemctl"
sudo -v || die "sudo refused"

# ── 1. venv + deps ──────────────────────────────────────────────────────────
if [[ ! -d venv ]]; then
    say "creating venv"
    python3 -m venv venv
fi
./venv/bin/pip install --quiet --upgrade pip
./venv/bin/pip install --quiet -r requirements.txt
ok "python venv"

# ── 2. .env ─────────────────────────────────────────────────────────────────
if [[ ! -f .env ]]; then
    say ".env missing — prompting"
    read -rsp "  postgres password for $DB_USER: " PW; echo
    read -rp  "  NASA API key (enter = DEMO_KEY): " NASA
    NASA="${NASA:-DEMO_KEY}"
    sed -e "s|CHANGEME|$PW|" \
        -e "s|^SKYMAP_NASA_API_KEY=.*|SKYMAP_NASA_API_KEY=$NASA|" \
        .env.example > .env
    chmod 600 .env
    ok ".env created (perms 600)"
else
    ok ".env exists"
fi
set -a; source .env; set +a

HOT_ROOT="$SKYMAP_STORAGE_ROOT"
COLD_ROOT="${SKYMAP_COLD_STORAGE_ROOT:-}"

# ── 3. q3c extension (one-time apt) ─────────────────────────────────────────
if ! dpkg -l postgresql-16-q3c 2>/dev/null | grep -q '^ii'; then
    say "installing postgresql-16-q3c"
    sudo apt-get update -qq
    sudo apt-get install -y postgresql-16-q3c
    ok "q3c installed"
else
    ok "q3c already installed"
fi

# ── 4. database ─────────────────────────────────────────────────────────────
if ! sudo -u postgres psql -tAc \
     "SELECT 1 FROM pg_database WHERE datname='$DB'" | grep -q 1; then
    say "creating database $DB"
    sudo -u postgres createdb "$DB" -O "$DB_USER"
    ok "database created"
else
    ok "database $DB exists"
fi

# ── 5. migrations ───────────────────────────────────────────────────────────
psql_sk() { PGPASSWORD="$(python3 -c "import urllib.parse as u; print(u.unquote(u.urlparse('$SKYMAP_DATABASE_URL').password or ''))")" \
            psql -h "$PG_HOST" -U "$DB_USER" -d "$DB" "$@"; }

if ! sudo -u postgres psql -d "$DB" -tAc \
     "SELECT 1 FROM pg_extension WHERE extname='q3c'" | grep -q 1; then
    say "creating q3c extension (superuser)"
    sudo -u postgres psql -d "$DB" -c "CREATE EXTENSION q3c" >/dev/null
    ok "q3c extension created"
else
    ok "q3c extension present"
fi

if ! psql_sk -tAc "SELECT to_regclass('sky_sources')" | grep -q sky_sources; then
    say "applying migration 001_init.sql"
    psql_sk -v ON_ERROR_STOP=1 -f migrations/001_init.sql >/dev/null
    ok "001 applied"
else
    ok "001 already applied"
fi

if ! psql_sk -tAc \
     "SELECT 1 FROM information_schema.columns
      WHERE table_name='sky_sources' AND column_name='storage_policy'" | grep -q 1; then
    say "applying migration 002_storage_policy.sql"
    psql_sk -v ON_ERROR_STOP=1 -f migrations/002_storage_policy.sql >/dev/null
    ok "002 applied"
else
    ok "002 already applied"
fi

# ── 6. storage dirs ─────────────────────────────────────────────────────────
mkdir -p "$HOT_ROOT/raw" "$HOT_ROOT/thumbs" "$HOT_ROOT/cutouts"
ok "hot storage ready: $HOT_ROOT"

if [[ -n "$COLD_ROOT" ]]; then
    if [[ ! -d "$COLD_ROOT" ]]; then
        say "creating $COLD_ROOT (needs sudo)"
        sudo mkdir -p "$COLD_ROOT"
        sudo chown "$USER:$USER" "$COLD_ROOT"
    elif [[ ! -w "$COLD_ROOT" ]]; then
        warn "$COLD_ROOT not writable; fixing ownership"
        sudo chown -R "$USER:$USER" "$COLD_ROOT"
    fi
    ok "cold storage ready: $COLD_ROOT"
else
    warn "SKYMAP_COLD_STORAGE_ROOT unset — tier migration will be a no-op"
fi

# ── 7. systemd units ────────────────────────────────────────────────────────
UNITS=(tower-skymap.service
       tower-skymap-ingest.service          tower-skymap-ingest.timer
       tower-skymap-ingest-nasa-iv.service  tower-skymap-ingest-nasa-iv.timer
       tower-skymap-drain.service           tower-skymap-drain.timer
       tower-skymap-tier-migrate.service    tower-skymap-tier-migrate.timer)

need_reload=0
for u in "${UNITS[@]}"; do
    src="$REPO/systemd/$u"
    dst="/etc/systemd/system/$u"
    if ! sudo cmp -s "$src" "$dst" 2>/dev/null; then
        sudo cp "$src" "$dst"
        need_reload=1
    fi
done
if (( need_reload )); then
    sudo systemctl daemon-reload
    ok "systemd units installed/updated"
else
    ok "systemd units current"
fi

# ── 8. enable + start ───────────────────────────────────────────────────────
sudo systemctl enable --now tower-skymap.service >/dev/null
for t in tower-skymap-ingest.timer tower-skymap-ingest-nasa-iv.timer \
         tower-skymap-drain.timer tower-skymap-tier-migrate.timer; do
    sudo systemctl enable --now "$t" >/dev/null
done
ok "service + 4 timers enabled"

# ── 9. health smoke ─────────────────────────────────────────────────────────
sleep 2
if curl -fsS "http://127.0.0.1:$SKYMAP_LISTEN_PORT/health" >/dev/null; then
    ok "/health responding on :$SKYMAP_LISTEN_PORT"
else
    die "service not responding on :$SKYMAP_LISTEN_PORT (check: journalctl -u tower-skymap -n 50)"
fi

cat <<EOF

${GRN}═════════════════════════════════════════════════════${NC}
${GRN}  Skymap is live.${NC}
${GRN}═════════════════════════════════════════════════════${NC}

  API       : http://127.0.0.1:$SKYMAP_LISTEN_PORT
  Health    : curl http://127.0.0.1:$SKYMAP_LISTEN_PORT/health
  Hot tier  : $HOT_ROOT
  Cold tier : ${COLD_ROOT:-<disabled>}

Next (optional):
  • Seed: $REPO/scripts/smoke-test.sh
  • Status: $REPO/scripts/status.sh
  • LAN (https://192.168.50.135/api/skymap/): paste
      $REPO/nginx/skymap.location.conf
    into /etc/nginx/sites-available/tower-https, then
      sudo nginx -t && sudo systemctl reload nginx

EOF
