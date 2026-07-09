"""Task 1 — Pull every continental-US Waffle House from Overture Maps.

Uses the local SedonaDB package to query Overture's ``places`` theme directly
from the public S3 bucket (anonymous access). The canonical set is the chain's
*brand*-attributed locations (brand spelling is normalized to lowercase, spaces
stripped, so "Waffle House" / "Wafflehouse" / "Waffle House Inc" all collapse to
one brand). A broad ``names.primary LIKE '%waffle house%'`` match is also pulled
purely for cross-validation reporting — it surfaces unbranded look-alikes
("Brooklyn Waffle House", museums, etc.) which are NOT included.

SedonaDB 0.3.0 SQL notes (discovered empirically):
  * ``read_parquet`` is a context method, not a SQL table function. Register the
    S3 directory as a view via ``ctx.read_parquet(dir, options).to_view(...)``.
  * The S3 path must be the directory (trailing slash), not a ``*`` glob.
  * Overture geometry CRS is ``ogc:crs84``; a WKT literal has no CRS, so the
    bbox polygon must be wrapped in ``ST_SetSRID(..., 4326)`` to compare.
  * There is no list-element access in SQL (no ``array_element`` / ``addr[1]``),
    so we select the raw ``addresses`` list and extract element 0 in pandas.

Output: data/waffle_houses.parquet  (id, name, lon, lat, address, city, state, brand)
Validation gate: 1,800 <= row count <= 2,100.

Usage:
    python src/01_pull_locations.py [--force]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
import common

MIN_ROWS, MAX_ROWS = 1800, 2100

# Brand spellings (normalized: lowercased, whitespace removed) that ARE the chain.
CANONICAL_BRANDS = {"wafflehouse", "wafflehouseinc", "wafflehouseincorporated"}

# Final cleaning (brand attribution in Overture is noisy): keep only POIs whose
# primary name is exactly "Waffle House" AND that sit in a state where the chain
# actually operates. This purges look-alikes ("The Waffle House" in Oakland, a
# medical museum, "Belgian Waffle House", etc.) and geographic mis-attributions
# (California, Iowa, a Hermosillo MX record) that slip through the brand match.
NAME_EXACT = "waffle house"
WH_STATES = {  # Waffle House's 25 operating states (2-letter region codes)
    "AL", "AZ", "AR", "CO", "DE", "FL", "GA", "IL", "IN", "KS", "KY", "LA",
    "MD", "MS", "MO", "NM", "NC", "OH", "OK", "PA", "SC", "TN", "TX", "VA", "WV",
}

# S3 read options for anonymous access to Overture's public bucket.
S3_OPTS = {"aws.skip_signature": True, "aws.region": "us-west-2"}


def _first_address(addresses):
    """Extract (freeform, locality, region) from element 0 of an addresses list.

    Overture's ``addresses`` is a list<struct>; SedonaDB returns it as an ndarray
    of dicts. Returns (None, None, None) when absent.
    """
    if addresses is None or len(addresses) == 0:
        return None, None, None
    a = addresses[0]
    return a.get("freeform"), a.get("locality"), a.get("region")


def _norm_brand(b):
    if b is None:
        return None
    return "".join(str(b).lower().split())


def main() -> None:
    parser = common.make_arg_parser(__doc__ or "Pull Waffle House locations")
    args = parser.parse_args()

    out = config.WAFFLE_PARQUET
    log = common.setup_logging("01_pull_locations", out)
    common.guard_output(out, args.force, log)
    config.ensure_dirs()

    import sedonadb

    log.info("Overture release: %s", config.OVERTURE_RELEASE)
    base = (
        f"s3://overturemaps-us-west-2/release/{config.OVERTURE_RELEASE}"
        "/theme=places/type=place/"
    )
    log.info("Registering Overture places theme from %s", base)

    ctx = sedonadb.connect()
    ctx.read_parquet(base, options=S3_OPTS).to_view("places", overwrite=True)

    query = f"""
        SELECT
            id,
            names.primary AS name,
            ST_X(geometry) AS lon,
            ST_Y(geometry) AS lat,
            addresses,
            brand.names.primary AS brand
        FROM places
        WHERE (
              LOWER(brand.names.primary) = 'waffle house'
           OR LOWER(names.primary) LIKE '%waffle house%'
        )
        AND ST_Within(
            geometry,
            ST_SetSRID(ST_GeomFromText('{config.CONUS_BBOX_WKT}'), 4326)
        )
    """
    log.info("Scanning Overture places (full-theme scan, ~4 min)...")
    raw = ctx.sql(query).to_pandas()
    log.info("Raw matches (brand OR name): %d", len(raw))

    # Extract address fields from the list<struct> column.
    raw[["address", "city", "state"]] = raw["addresses"].apply(
        lambda a: __import__("pandas").Series(_first_address(a))
    )
    raw["brand_norm"] = raw["brand"].apply(_norm_brand)

    is_canonical = raw["brand_norm"].isin(CANONICAL_BRANDS)
    log.info("Canonical brand-attributed locations: %d", int(is_canonical.sum()))

    # Tighten further: exact name AND operating-state allowlist (see WH_STATES).
    name_ok = raw["name"].str.strip().str.lower() == NAME_EXACT
    state_ok = raw["state"].str.strip().str.upper().isin(WH_STATES)
    keep = is_canonical & name_ok & state_ok
    df = raw[keep].copy()

    dropped = raw[is_canonical & ~(name_ok & state_ok)]
    log.info("After exact-name + WH-state filter: %d (dropped %d noisy/out-of-area)",
             len(df), len(dropped))
    log.info("Top dropped names:\n%s",
             dropped["name"].value_counts().head(8).to_string())
    bad_states = dropped.loc[name_ok, "state"].dropna().unique().tolist()
    log.info("Dropped exact-name records in non-operating states: %s", sorted(bad_states))

    df = df[common.WAFFLE_COLUMNS].reset_index(drop=True)
    by_state = df["state"].value_counts().head(10)
    log.info("Top states:\n%s", by_state.to_string())

    if not (MIN_ROWS <= len(df) <= MAX_ROWS):
        log.error(
            "VALIDATION FAILED: row count %d outside expected [%d, %d]. "
            "Not writing output.",
            len(df), MIN_ROWS, MAX_ROWS,
        )
        sys.exit(1)

    df.to_parquet(out)
    log.info("Wrote %s (%d rows). Validation gate passed.", out, len(df))

    sample = df.sample(min(5, len(df)), random_state=42)[
        ["name", "address", "city", "state", "lat", "lon"]
    ]
    log.info("Spot-check sample (verify against locations.wafflehouse.com):\n%s",
             sample.to_string(index=False))


if __name__ == "__main__":
    main()
