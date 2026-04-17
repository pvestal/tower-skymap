-- Storage policy & tiering: strategy A (upstream-as-CDN) + strategy C (hot/cold local tiers).

ALTER TABLE sky_sources
    ADD COLUMN storage_policy TEXT NOT NULL DEFAULT 'mirror'
        CHECK (storage_policy IN ('mirror', 'thumb_only', 'proxy_only')),
    ADD COLUMN upstream_is_cdn BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN sky_sources.storage_policy IS
    'mirror = download + keep raw; thumb_only = download, thumb, delete raw; proxy_only = metadata only';

COMMENT ON COLUMN sky_sources.upstream_is_cdn IS
    'TRUE when upstream_url is safe to 302-redirect to (NASA/ESA/CDS public archives)';

ALTER TABLE sky_tiles
    ADD COLUMN storage_tier TEXT NOT NULL DEFAULT 'hot'
        CHECK (storage_tier IN ('hot', 'cold', 'evicted')),
    ADD COLUMN last_accessed_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

CREATE INDEX sky_tiles_tier_access_idx
    ON sky_tiles (storage_tier, last_accessed_at)
    WHERE kind = 'raw';

-- Seed known-safe CDN flag for APOD (NASA public archive)
UPDATE sky_sources SET upstream_is_cdn = TRUE WHERE source = 'apod';
