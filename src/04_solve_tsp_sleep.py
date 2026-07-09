"""Task 4 — Solve the TSP with an overnight-sleep constraint.

Driving order for a single vehicle visiting every node is unchanged by adding
rest (rest is a function of cumulative drive time, not of which node comes
next), so we re-solve the spatial TSP with OR-Tools and then overlay the sleep
schedule: after every 16 hours of driving the driver must stop for 8 hours of
rest. The *route distance* matches the pure run, but the total ELAPSED journey
time grows by the rest hours — this is the cost the constraint adds.

Inputs:  data/waffle_houses.parquet, data/distance_matrix.npy
Outputs: output/routes/sleep_tsp.geojson, output/routes/sleep_tsp_metrics.json

Usage:
    python src/04_solve_tsp_sleep.py [--force] [--time-limit 60]
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
import common
import tsp


def main() -> None:
    parser = common.make_arg_parser(__doc__ or "Sleep-constrained TSP")
    parser.add_argument("--time-limit", type=int, default=60)
    args = parser.parse_args()

    geojson_out = config.ROUTES_DIR / "sleep_tsp.geojson"
    metrics_out = config.ROUTES_DIR / "sleep_tsp_metrics.json"
    log = common.setup_logging("04_solve_tsp_sleep", geojson_out)
    common.guard_output(geojson_out, args.force, log)
    config.ensure_dirs()

    df = common.load_waffle_houses()
    matrix = common.load_matrix()

    route, dist_m = tsp.solve_ortools(matrix, args.time_limit, log)
    drive_hours = tsp.drive_hours_from_m(dist_m)

    # Overnight rest model: one 8h rest after each full 16h driving block.
    n_rests = max(0, math.floor(drive_hours / config.MAX_DRIVE_HOURS))
    rest_hours = n_rests * config.REST_HOURS
    total_elapsed = drive_hours + rest_hours

    log.info("Drive %.1f h -> %d overnight rests (%.0f h) -> %.1f h elapsed",
             drive_hours, n_rests, rest_hours, total_elapsed)

    metrics = {
        "solver": "ortools",
        "constraint": "sleep",
        "n_stops": len(route),
        "total_distance_km": round(dist_m / tsp.M_PER_KM, 1),
        "total_drive_time_hours": round(drive_hours, 1),
        "rest_hours": round(rest_hours, 1),
        "overnight_stops": n_rests,
        "total_elapsed_hours": round(total_elapsed, 1),
        "total_elapsed_days": round(total_elapsed / 24, 1),
        "max_drive_hours_before_rest": config.MAX_DRIVE_HOURS,
        "rest_block_hours": config.REST_HOURS,
    }

    tsp.write_route_geojson(df, route, geojson_out, log)
    tsp.write_metrics(metrics_out, metrics, log)


if __name__ == "__main__":
    main()
