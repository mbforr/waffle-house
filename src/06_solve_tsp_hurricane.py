"""Task 6 — Solve the TSP with hurricane closures (Hurricane Helene, 2024).

Downloads NOAA HURDAT2, parses it, and marks every Waffle House within 80 km of
a storm-track point carrying >= 75 mph sustained winds as CLOSED. The closed
nodes are removed from the routing graph and the TSP is re-solved over the
survivors. Reports the closure count and a per-storm breakdown for the 2024
season (consumed by the summary).

Inputs:  data/waffle_houses.parquet, data/distance_matrix.npy
         data/hurdat2.csv (downloaded if missing)
Outputs: output/routes/hurricane_tsp.geojson, output/routes/hurricane_tsp_metrics.json

Usage:
    python src/06_solve_tsp_hurricane.py [--force] [--time-limit 60]
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
import common
import tsp


def parse_hurdat2(filepath):
    """Parse NOAA HURDAT2 into a DataFrame of storm positions with wind speed."""
    import pandas as pd

    rows = []
    current = None
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line[:2] in ("AL", "EP", "CP"):
                parts = [p.strip() for p in line.split(",")]
                current = {"id": parts[0], "name": parts[1]}
            elif current and "," in line:
                parts = [p.strip() for p in line.split(",")]
                try:
                    rows.append({
                        "storm_id": current["id"],
                        "storm_name": current["name"],
                        "year": int(parts[0][:4]),
                        "datetime": parts[0] + parts[1],
                        "lat": float(parts[4].rstrip("NS")) * (-1 if parts[4].endswith("S") else 1),
                        "lon": float(parts[5].rstrip("EW")) * (-1 if parts[5].endswith("W") else 1),
                        "wind_mph": int(parts[6]),
                    })
                except (ValueError, IndexError):
                    continue
    return pd.DataFrame(rows)


def closures_for_track(waffle_houses, track, threshold_mph, radius_km):
    """Return the set of Waffle House ids closed by a storm track."""
    closed = set()
    hi = track[track["wind_mph"] >= threshold_mph]
    for _, p in hi.iterrows():
        d_km = (((waffle_houses["lat"] - p["lat"]) ** 2
                 + (waffle_houses["lon"] - p["lon"]) ** 2) ** 0.5) * 111.0
        closed.update(waffle_houses.loc[d_km < radius_km, "id"].tolist())
    return closed


def ensure_hurdat2(log):
    if config.HURDAT2_CSV.exists():
        return config.HURDAT2_CSV
    log.info("Downloading HURDAT2 from %s", config.HURDAT2_URL)
    subprocess.run(["curl", "-L", "-o", str(config.HURDAT2_CSV),
                    config.HURDAT2_URL], check=True)
    return config.HURDAT2_CSV


def main() -> None:
    parser = common.make_arg_parser(__doc__ or "Hurricane-constrained TSP")
    parser.add_argument("--time-limit", type=int, default=60)
    args = parser.parse_args()

    geojson_out = config.ROUTES_DIR / "hurricane_tsp.geojson"
    metrics_out = config.ROUTES_DIR / "hurricane_tsp_metrics.json"
    log = common.setup_logging("06_solve_tsp_hurricane", geojson_out)
    common.guard_output(geojson_out, args.force, log)
    config.ensure_dirs()

    df = common.load_waffle_houses()
    matrix = common.load_matrix()

    hurdat = parse_hurdat2(ensure_hurdat2(log))
    log.info("Parsed %d HURDAT2 track points across %d storms",
             len(hurdat), hurdat["storm_id"].nunique())

    # The modeled scenario: Hurricane Helene, 2024.
    storm = hurdat[(hurdat["storm_name"] == config.HURRICANE_NAME)
                   & (hurdat["year"] == config.HURRICANE_YEAR)]
    if storm.empty:
        log.error("Storm %s (%d) not found in HURDAT2.",
                  config.HURRICANE_NAME, config.HURRICANE_YEAR)
        sys.exit(1)
    log.info("%s %d: %d track points, peak wind %d mph",
             config.HURRICANE_NAME, config.HURRICANE_YEAR, len(storm),
             int(storm["wind_mph"].max()))

    closed_ids = closures_for_track(df, storm, config.CLOSURE_THRESHOLD_MPH,
                                    config.CLOSURE_RADIUS_KM)
    log.info("Closed Waffle Houses (%s): %d", config.HURRICANE_NAME, len(closed_ids))

    # Per-storm closure breakdown for the 2024 season (for the summary report).
    season = hurdat[hurdat["year"] == config.HURRICANE_YEAR]
    storm_closures = {}
    for sid, grp in season.groupby("storm_name"):
        c = closures_for_track(df, grp, config.CLOSURE_THRESHOLD_MPH,
                               config.CLOSURE_RADIUS_KM)
        if c:
            storm_closures[sid] = len(c)

    # Remove closed nodes, re-solve over the survivors.
    open_mask = ~df["id"].isin(closed_ids)
    node_index = df.index[open_mask].tolist()  # matrix-subset idx -> df idx
    sub = matrix[open_mask.values][:, open_mask.values]
    log.info("Re-solving over %d open locations...", len(node_index))

    route, dist_m = tsp.solve_ortools(sub, args.time_limit, log)

    metrics = {
        "solver": "ortools",
        "constraint": "hurricane",
        "storm": f"{config.HURRICANE_NAME} {config.HURRICANE_YEAR}",
        "closure_threshold_mph": config.CLOSURE_THRESHOLD_MPH,
        "closure_radius_km": config.CLOSURE_RADIUS_KM,
        "n_closed": len(closed_ids),
        "n_open_stops": len(route),
        "total_distance_km": round(dist_m / tsp.M_PER_KM, 1),
        "total_drive_time_hours": round(tsp.drive_hours_from_m(dist_m), 1),
        "closures_by_storm_2024": dict(sorted(storm_closures.items(),
                                              key=lambda kv: -kv[1])),
    }

    # Closed stores are kept in the output (tagged kind="closed") so the map can
    # show them in red rather than dropping them.
    closed_df = df[df["id"].isin(closed_ids)]
    closed_features = [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [float(r["lon"]), float(r["lat"])]},
        "properties": {"kind": "closed", "id": r["id"], "name": r["name"],
                       "city": r["city"], "state": r["state"]},
    } for _, r in closed_df.iterrows()]
    log.info("Tagging %d closed stores as kind='closed' in the GeoJSON.",
             len(closed_features))

    # route indexes into the subset; map back to df rows via node_index.
    tsp.write_route_geojson(df, route, geojson_out, log, node_index=node_index,
                            extra_features=closed_features)
    tsp.write_metrics(metrics_out, metrics, log)


if __name__ == "__main__":
    main()
