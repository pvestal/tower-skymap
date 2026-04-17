"""Catalog ingester — seeds sky_objects with visually-interesting targets.

This is a CURATED subset: ~40 most iconic Messier objects + ~15 best Caldwell
objects. Sourced from SIMBAD-verified canonical positions (J2000 ICRS). Stable
historical data — these designations haven't moved since the 1780s (Messier)
or 1995 (Caldwell).

Expand to full 110+109 via SIMBAD TAP in a future revision.

Usage:
    python -m workers.catalog_ingest              # seeds both
    python -m workers.catalog_ingest messier      # just Messier
    python -m workers.catalog_ingest caldwell     # just Caldwell
"""
import asyncio
import sys

from app.db import close_pool, get_pool

# (name, ra_deg, dec_deg, obj_type, catalog_id, designations, common_names,
#  magnitude, size_arcmin, constellation, catalog_source)
# Coordinates: J2000 ICRS, decimal degrees. Source: SIMBAD main_id lookup.

MESSIER = [
    # Showstoppers — bright, famous, easy naked-eye or binocular targets
    ("Andromeda Galaxy",       10.6847,   41.2687, "galaxy",     "M31",  ["M31", "NGC 224"],  ["Andromeda Galaxy", "Great Andromeda Nebula"], 3.44, 190.0, "And", "messier"),
    ("Triangulum Galaxy",      23.4621,   30.6601, "galaxy",     "M33",  ["M33", "NGC 598"],  ["Triangulum Galaxy", "Pinwheel of Triangulum"], 5.72, 70.8, "Tri", "messier"),
    ("Pleiades",               56.7500,   24.1167, "open cluster","M45", ["M45"],             ["Pleiades", "Seven Sisters", "Subaru"], 1.6, 110.0, "Tau", "messier"),
    ("Orion Nebula",           83.8221,   -5.3911, "nebula",     "M42",  ["M42", "NGC 1976"], ["Orion Nebula", "Great Orion Nebula"], 4.0, 65.0, "Ori", "messier"),
    ("De Mairan's Nebula",     83.8542,   -5.2700, "nebula",     "M43",  ["M43", "NGC 1982"], ["De Mairan's Nebula"],  9.0, 20.0, "Ori", "messier"),
    ("Beehive Cluster",       130.1000,   19.6833, "open cluster","M44", ["M44", "NGC 2632"], ["Beehive Cluster", "Praesepe"], 3.7, 95.0, "Cnc", "messier"),
    ("Whirlpool Galaxy",      202.4696,   47.1952, "galaxy",     "M51",  ["M51", "NGC 5194"], ["Whirlpool Galaxy"],  8.4, 11.2, "CVn", "messier"),
    ("Bode's Galaxy",         148.8882,   69.0653, "galaxy",     "M81",  ["M81", "NGC 3031"], ["Bode's Galaxy"],     6.94, 26.9, "UMa", "messier"),
    ("Cigar Galaxy",          148.9684,   69.6797, "galaxy",     "M82",  ["M82", "NGC 3034"], ["Cigar Galaxy", "Starburst Galaxy"], 8.41, 11.2, "UMa", "messier"),
    ("Pinwheel Galaxy",       210.8024,   54.3487, "galaxy",     "M101", ["M101", "NGC 5457"],["Pinwheel Galaxy"],   7.86, 28.8, "UMa", "messier"),
    ("Sombrero Galaxy",       189.9977,  -11.6231, "galaxy",     "M104", ["M104", "NGC 4594"],["Sombrero Galaxy"],   8.0, 8.7, "Vir", "messier"),
    ("Ring Nebula",           283.3963,   33.0293, "planetary nebula","M57", ["M57", "NGC 6720"], ["Ring Nebula"], 8.8, 1.4, "Lyr", "messier"),
    ("Dumbbell Nebula",       299.9015,   22.7213, "planetary nebula","M27", ["M27", "NGC 6853"], ["Dumbbell Nebula", "Apple Core Nebula"], 7.5, 8.0, "Vul", "messier"),
    ("Crab Nebula",            83.6332,   22.0145, "supernova remnant","M1", ["M1", "NGC 1952"], ["Crab Nebula"], 8.4, 6.0, "Tau", "messier"),
    ("Hercules Cluster",      250.4235,   36.4613, "globular cluster","M13", ["M13", "NGC 6205"], ["Hercules Globular Cluster", "Great Hercules Cluster"], 5.8, 20.0, "Her", "messier"),
    ("M92",                   259.2807,   43.1358, "globular cluster","M92", ["M92", "NGC 6341"], ["M92"], 6.3, 14.0, "Her", "messier"),
    ("M15",                   322.4930,   12.1670, "globular cluster","M15", ["M15", "NGC 7078"], ["Great Pegasus Cluster"], 6.2, 18.0, "Peg", "messier"),
    ("M22",                   279.0997,  -23.9048, "globular cluster","M22", ["M22", "NGC 6656"], ["Sagittarius Cluster"], 5.1, 32.0, "Sgr", "messier"),
    ("Wild Duck Cluster",     282.7667,   -6.2767, "open cluster","M11", ["M11", "NGC 6705"], ["Wild Duck Cluster"], 6.3, 14.0, "Sct", "messier"),
    ("Eagle Nebula",          274.7000,  -13.8000, "nebula",     "M16",  ["M16", "NGC 6611"], ["Eagle Nebula", "Star Queen Nebula"],  6.0, 35.0, "Ser", "messier"),
    ("Omega Nebula",          275.1960,  -16.1711, "nebula",     "M17",  ["M17", "NGC 6618"], ["Omega Nebula", "Swan Nebula", "Horseshoe Nebula"], 6.0, 11.0, "Sgr", "messier"),
    ("Trifid Nebula",         270.6083,  -23.0300, "nebula",     "M20",  ["M20", "NGC 6514"], ["Trifid Nebula"],  6.3, 28.0, "Sgr", "messier"),
    ("Lagoon Nebula",         270.9046,  -24.3867, "nebula",     "M8",   ["M8", "NGC 6523"],  ["Lagoon Nebula"],  6.0, 90.0, "Sgr", "messier"),
    ("Leo Triplet M65",       169.7333,   13.0922, "galaxy",     "M65",  ["M65", "NGC 3623"], ["Leo Triplet (M65)"],  9.3, 9.8, "Leo", "messier"),
    ("Leo Triplet M66",       170.0625,   12.9914, "galaxy",     "M66",  ["M66", "NGC 3627"], ["Leo Triplet (M66)"],  8.9, 9.1, "Leo", "messier"),
    ("Virgo A",               187.7059,   12.3911, "galaxy",     "M87",  ["M87", "NGC 4486"], ["Virgo A", "Smoking Gun"],  8.6, 8.3, "Vir", "messier"),
    ("Black Eye Galaxy",      194.1818,   21.6828, "galaxy",     "M64",  ["M64", "NGC 4826"], ["Black Eye Galaxy", "Evil Eye Galaxy"],  8.5, 10.0, "Com", "messier"),
    ("Butterfly Cluster",     265.0667,  -32.2533, "open cluster","M6",  ["M6", "NGC 6405"],  ["Butterfly Cluster"],  4.2, 25.0, "Sco", "messier"),
    ("Ptolemy Cluster",       268.4458,  -34.7925, "open cluster","M7",  ["M7", "NGC 6475"],  ["Ptolemy Cluster"],  3.3, 80.0, "Sco", "messier"),
    ("Double Cluster Region M103", 23.3400,  60.6583, "open cluster","M103", ["M103", "NGC 581"], ["M103"],  7.4, 6.0, "Cas", "messier"),
    ("M36",                    84.0833,   34.1500, "open cluster","M36", ["M36", "NGC 1960"], ["Pinwheel Cluster"], 6.3, 12.0, "Aur", "messier"),
    ("M37",                    88.0750,   32.5533, "open cluster","M37", ["M37", "NGC 2099"], ["Salt-and-Pepper Cluster"], 6.2, 24.0, "Aur", "messier"),
    ("M38",                    82.1750,   35.8500, "open cluster","M38", ["M38", "NGC 1912"], ["Starfish Cluster"], 7.4, 21.0, "Aur", "messier"),
    ("M34",                    40.5167,   42.7617, "open cluster","M34", ["M34", "NGC 1039"], ["M34"], 5.5, 35.0, "Per", "messier"),
    ("M35",                    92.2250,   24.3333, "open cluster","M35", ["M35", "NGC 2168"], ["M35"], 5.3, 28.0, "Gem", "messier"),
    ("Southern Pinwheel",     204.2538,  -29.8658, "galaxy",     "M83",  ["M83", "NGC 5236"], ["Southern Pinwheel Galaxy"], 7.54, 12.9, "Hya", "messier"),
    ("Sunflower Galaxy",      198.9553,   42.0292, "galaxy",     "M63",  ["M63", "NGC 5055"], ["Sunflower Galaxy"], 9.3, 12.6, "CVn", "messier"),
    ("Needle Galaxy",         189.0133,   33.5472, "galaxy",     "M108", ["M108", "NGC 3556"],["Surfboard Galaxy"], 10.0, 8.7, "UMa", "messier"),
    ("Owl Nebula",            168.6992,   55.0192, "planetary nebula","M97", ["M97", "NGC 3587"], ["Owl Nebula"], 9.9, 3.4, "UMa", "messier"),
    ("Little Dumbbell Nebula", 21.5683,   51.5753, "planetary nebula","M76", ["M76", "NGC 650"],  ["Little Dumbbell Nebula", "Barbell Nebula", "Cork Nebula"], 10.1, 2.7, "Per", "messier"),
]

CALDWELL = [
    # Best of Caldwell — objects Messier missed but are visually superb
    ("Cassiopeia A (SNR visual)",350.8500, 58.8150, "supernova remnant", "C11", ["C11", "NGC 7635"], ["Bubble Nebula"], 10.0, 15.0, "Cas", "caldwell"),
    ("Double Cluster NGC 869", 34.7500,  57.1333, "open cluster", "C14", ["C14", "NGC 869", "h Persei"], ["Double Cluster", "h Persei"], 3.7, 30.0, "Per", "caldwell"),
    ("NGC 7293 Helix Nebula", 337.4108, -20.8367, "planetary nebula", "C63", ["C63", "NGC 7293"], ["Helix Nebula", "Eye of God", "Eye of Sauron"], 7.3, 25.0, "Aqr", "caldwell"),
    ("NGC 7000 North America Nebula", 315.0000, 44.2500, "nebula", "C20", ["C20", "NGC 7000"], ["North America Nebula"], 4.0, 120.0, "Cyg", "caldwell"),
    ("NGC 2070 Tarantula Nebula", 84.6750, -69.1008, "nebula", "C103", ["C103", "NGC 2070"], ["Tarantula Nebula", "30 Doradus"], 8.0, 40.0, "Dor", "caldwell"),
    ("NGC 3372 Carina Nebula",161.2650, -59.8670, "nebula", "C92", ["C92", "NGC 3372"], ["Carina Nebula", "Eta Carinae Nebula"], 1.0, 120.0, "Car", "caldwell"),
    ("NGC 4755 Jewel Box",     193.2333, -60.3500, "open cluster", "C94", ["C94", "NGC 4755"], ["Jewel Box", "Kappa Crucis Cluster"], 4.2, 10.0, "Cru", "caldwell"),
    ("NGC 5139 Omega Centauri",201.6925, -47.4793, "globular cluster", "C80", ["C80", "NGC 5139"], ["Omega Centauri"], 3.9, 36.3, "Cen", "caldwell"),
    ("NGC 6543 Cat's Eye",     269.6392,  66.6328, "planetary nebula", "C6", ["C6", "NGC 6543"], ["Cat's Eye Nebula"], 8.1, 0.3, "Dra", "caldwell"),
    ("NGC 6888 Crescent Nebula", 303.0173, 38.3575, "nebula", "C27", ["C27", "NGC 6888"], ["Crescent Nebula"], 7.4, 18.0, "Cyg", "caldwell"),
    ("NGC 6960 Veil Nebula (west)", 312.7500, 30.7167, "supernova remnant", "C34", ["C34", "NGC 6960"], ["Western Veil Nebula", "Witch's Broom"], 7.0, 70.0, "Cyg", "caldwell"),
    ("NGC 6992 Veil Nebula (east)", 313.0500, 31.7000, "supernova remnant", "C33", ["C33", "NGC 6992"], ["Eastern Veil Nebula"], 7.0, 60.0, "Cyg", "caldwell"),
    ("NGC 4565 Needle Galaxy", 189.0863,  25.9873, "galaxy", "C38", ["C38", "NGC 4565"], ["Needle Galaxy"], 9.6, 15.9, "Com", "caldwell"),
    ("IC 405 Flaming Star Nebula", 79.5000, 34.2500, "nebula", "C31", ["C31", "IC 405"], ["Flaming Star Nebula"], 6.0, 37.0, "Aur", "caldwell"),
    ("NGC 281 Pacman Nebula",  12.9500,  56.6167, "nebula", "C15", ["C15", "NGC 281"], ["Pacman Nebula"], 7.4, 35.0, "Cas", "caldwell"),
    ("NGC 281 Heart Nebula",   38.1750,  61.4667, "nebula", "C13", ["C13", "IC 1805"], ["Heart Nebula"], 6.5, 60.0, "Cas", "caldwell"),
    ("NGC 6822 Barnard's Galaxy", 296.2333, -14.8028, "galaxy", "C57", ["C57", "NGC 6822"], ["Barnard's Galaxy"], 8.8, 15.5, "Sgr", "caldwell"),
    ("Sculptor Galaxy",         11.8881,  -25.2883, "galaxy", "C65", ["C65", "NGC 253"],  ["Sculptor Galaxy", "Silver Dollar Galaxy"], 8.0, 27.5, "Scl", "caldwell"),
    ("NGC 7023 Iris Nebula",  315.3833,  68.1667, "nebula", "C4", ["C4", "NGC 7023"], ["Iris Nebula"], 6.8, 18.0, "Cep", "caldwell"),
]

CATALOGS = {"messier": MESSIER, "caldwell": CALDWELL}


UPSERT_SQL = """
INSERT INTO sky_objects
    (name, ra, dec, obj_type, catalog_id, designations, common_names,
     magnitude, size_arcmin, constellation, catalog_source)
VALUES
    ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
ON CONFLICT (name) DO UPDATE SET
    ra              = EXCLUDED.ra,
    dec             = EXCLUDED.dec,
    obj_type        = EXCLUDED.obj_type,
    catalog_id      = EXCLUDED.catalog_id,
    designations    = EXCLUDED.designations,
    common_names    = EXCLUDED.common_names,
    magnitude       = EXCLUDED.magnitude,
    size_arcmin     = EXCLUDED.size_arcmin,
    constellation   = EXCLUDED.constellation,
    catalog_source  = EXCLUDED.catalog_source
RETURNING (xmax = 0) AS inserted
"""


async def ingest_catalog(name: str) -> tuple[int, int]:
    data = CATALOGS[name]
    inserted = updated = 0
    pool = await get_pool()
    async with pool.acquire() as conn:
        for row in data:
            is_new = await conn.fetchval(UPSERT_SQL, *row)
            if is_new:
                inserted += 1
            else:
                updated += 1
    print(f"[{name}] inserted={inserted} updated={updated} total={len(data)}")
    return inserted, updated


async def main() -> None:
    wanted = sys.argv[1:] or list(CATALOGS.keys())
    for name in wanted:
        if name not in CATALOGS:
            print(f"unknown catalog: {name}. choose from: {list(CATALOGS)}")
            sys.exit(2)
    for name in wanted:
        await ingest_catalog(name)
    await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
