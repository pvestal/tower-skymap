-- Requires: sudo apt install postgresql-16-q3c (once per cluster)
-- Extension creation needs superuser — run as postgres the first time:
--   sudo -u postgres psql -d sky_archive -c "CREATE EXTENSION q3c"
-- After that, this file can be applied as the DB owner (idempotent).
CREATE EXTENSION IF NOT EXISTS q3c;

CREATE TABLE sky_sources (
    id            BIGSERIAL PRIMARY KEY,
    source        TEXT NOT NULL,
    source_id     TEXT NOT NULL,
    title         TEXT,
    caption       TEXT,
    ra            DOUBLE PRECISION,
    dec           DOUBLE PRECISION,
    fov_arcmin    DOUBLE PRECISION,
    band          TEXT,
    observed_at   TIMESTAMPTZ,
    upstream_url  TEXT,
    metadata      JSONB NOT NULL DEFAULT '{}'::jsonb,
    ingested_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source, source_id)
);

CREATE INDEX sky_sources_q3c_idx
    ON sky_sources (q3c_ang2ipix(ra, dec))
    WHERE ra IS NOT NULL AND dec IS NOT NULL;

CREATE INDEX sky_sources_observed_at_idx ON sky_sources (observed_at DESC);

CREATE INDEX sky_sources_fts_idx
    ON sky_sources
    USING gin (to_tsvector('english', coalesce(title,'') || ' ' || coalesce(caption,'')));

CREATE TABLE sky_tiles (
    id             BIGSERIAL PRIMARY KEY,
    source_id      BIGINT NOT NULL REFERENCES sky_sources(id) ON DELETE CASCADE,
    kind           TEXT NOT NULL CHECK (kind IN ('raw','thumb','cutout')),
    ra             DOUBLE PRECISION,
    dec            DOUBLE PRECISION,
    fov_arcmin     DOUBLE PRECISION,
    projection     TEXT DEFAULT 'TAN',
    size_px        INTEGER,
    local_relpath  TEXT NOT NULL,
    bytes          BIGINT,
    qdrant_id      UUID,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source_id, kind, local_relpath)
);

CREATE INDEX sky_tiles_source_idx ON sky_tiles (source_id);
CREATE INDEX sky_tiles_q3c_idx
    ON sky_tiles (q3c_ang2ipix(ra, dec))
    WHERE ra IS NOT NULL AND dec IS NOT NULL;

CREATE TABLE sky_objects (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    ra          DOUBLE PRECISION NOT NULL,
    dec         DOUBLE PRECISION NOT NULL,
    obj_type    TEXT,
    catalog_id  TEXT,
    notes       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX sky_objects_q3c_idx ON sky_objects (q3c_ang2ipix(ra, dec));

CREATE TABLE sky_observations (
    id           BIGSERIAL PRIMARY KEY,
    object_id    BIGINT NOT NULL REFERENCES sky_objects(id) ON DELETE CASCADE,
    tile_id      BIGINT NOT NULL REFERENCES sky_tiles(id) ON DELETE CASCADE,
    observed_at  TIMESTAMPTZ,
    UNIQUE (object_id, tile_id)
);

CREATE INDEX sky_observations_object_idx
    ON sky_observations (object_id, observed_at DESC NULLS LAST);

CREATE TABLE sky_tile_queue (
    id          BIGSERIAL PRIMARY KEY,
    source_id   BIGINT NOT NULL REFERENCES sky_sources(id) ON DELETE CASCADE,
    action      TEXT NOT NULL DEFAULT 'download_and_thumb',
    status      TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending','running','done','failed')),
    attempts    INT NOT NULL DEFAULT 0,
    last_error  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX sky_tile_queue_pending_idx
    ON sky_tile_queue (status, created_at)
    WHERE status IN ('pending','failed');
