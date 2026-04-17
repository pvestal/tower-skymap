-- 003: extend sky_objects for real astronomical catalogs
-- Source catalogs: Messier (110), Caldwell (109), NGC (7840), IC (5386).
-- Designed to accept any future catalog (UGC, PGC, Sharpless, Abell, etc.)
-- via the designations[] array without further schema churn.

ALTER TABLE sky_objects
    ADD COLUMN IF NOT EXISTS designations    text[]  DEFAULT '{}'::text[],
    ADD COLUMN IF NOT EXISTS common_names    text[]  DEFAULT '{}'::text[],
    ADD COLUMN IF NOT EXISTS magnitude       double precision,
    ADD COLUMN IF NOT EXISTS size_arcmin     double precision,
    ADD COLUMN IF NOT EXISTS constellation   text,
    ADD COLUMN IF NOT EXISTS catalog_source  text;

COMMENT ON COLUMN sky_objects.designations IS
    'All catalog IDs for this object: {M31, NGC 224, UGC 454}. Used for imagery cross-link.';
COMMENT ON COLUMN sky_objects.common_names IS
    'Human-readable aliases: {Andromeda Galaxy, Great Andromeda Nebula}.';
COMMENT ON COLUMN sky_objects.magnitude IS
    'Apparent visual magnitude. Lower = brighter. NULL for catalogs that do not track it.';
COMMENT ON COLUMN sky_objects.size_arcmin IS
    'Angular diameter in arcminutes. Used by frontend to choose Aladin FOV when clicked.';
COMMENT ON COLUMN sky_objects.constellation IS
    'Three-letter IAU constellation abbreviation (e.g., And, Ori, UMa).';
COMMENT ON COLUMN sky_objects.catalog_source IS
    'Canonical provenance: {messier, caldwell, ngc, ic}.';

-- GIN on designations[] for fast "does any sky_object contain M31?" lookups
CREATE INDEX IF NOT EXISTS sky_objects_designations_idx
    ON sky_objects USING GIN (designations);

-- GIN on common_names[] for title-match cross-linking (step 5 of the plan)
CREATE INDEX IF NOT EXISTS sky_objects_common_names_idx
    ON sky_objects USING GIN (common_names);

-- Bright-object filter index — frontend "show only bright enough to see" toggle
CREATE INDEX IF NOT EXISTS sky_objects_magnitude_idx
    ON sky_objects (magnitude) WHERE magnitude IS NOT NULL;

-- Name-only tsvector for fuzzy title matching.
-- A combined index over name+designations+common_names would be nicer, but
-- array_to_string() is STABLE (not IMMUTABLE), so Postgres refuses to index
-- an expression containing it. The array GIN indexes above already handle
-- exact-match lookups against designations[] and common_names[]; step-5
-- cross-linking queries them directly:
--   SELECT id FROM sky_objects
--    WHERE common_names && ARRAY['Andromeda Galaxy']
--       OR designations && ARRAY['M31']
--       OR to_tsvector('english'::regconfig, name) @@ plainto_tsquery($1);
CREATE INDEX IF NOT EXISTS sky_objects_name_textsearch_idx
    ON sky_objects USING GIN (to_tsvector('english'::regconfig, name));
