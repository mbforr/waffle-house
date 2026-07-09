"""Task 5 — Solve the TSP with per-stop eating (service) time.

Adds 30 minutes of service time at every Waffle House. Like the sleep run, a
constant per-node service time does not change the optimal visiting order for a
single vehicle, so we re-solve the spatial TSP and overlay the eating time:
total elapsed = drive time + 0.5 h * N. Also tracks cumulative calories
(one waffle per stop).

Inputs:  data/waffle_houses.parquet, data/distance_matrix.npy
Outputs: output/routes/eating_tsp.geojson, output/routes/eating_tsp_metrics.json

Usage:
    python src/05_solve_tsp_eating.py [--force] [--time-limit 60]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
import common
import tsp


def main() -> None:
    parser = common.make_arg_parser(__doc__ or "Eating-constrained TSP")
    parser.add_argument("--time-limit", type=int, default=60)
    args = parser.parse_args()

    geojson_out = config.ROUTES_DIR / "eating_tsp.geojson"
    metrics_out = config.ROUTES_DIR / "eating_tsp_metrics.json"
    log = common.setup_logging("05_solve_tsp_eating", geojson_out)
    common.guard_output(geojson_out, args.force, log)
    config.ensure_dirs()

    df = common.load_waffle_houses()
    matrix = common.load_matrix()

    route, dist_m = tsp.solve_ortools(matrix, args.time_limit, log)
    drive_hours = tsp.drive_hours_from_m(dist_m)

    n = len(route)
    eating_hours = n * config.EATING_MINUTES_PER_STOP / 60.0
    total_elapsed = drive_hours + eating_hours
    calories = n * config.WAFFLE_CALORIES_PER_STOP

    log.info("Drive %.1f h + eating %.1f h (%d stops) -> %.1f h elapsed; %d kcal",
             drive_hours, eating_hours, n, total_elapsed, calories)

    metrics = {
        "solver": "ortools",
        "constraint": "eating",
        "n_stops": n,
        "total_distance_km": round(dist_m / tsp.M_PER_KM, 1),
        "total_drive_time_hours": round(drive_hours, 1),
        "eating_minutes_per_stop": config.EATING_MINUTES_PER_STOP,
        "eating_hours": round(eating_hours, 1),
        "total_elapsed_hours": round(total_elapsed, 1),
        "total_elapsed_days": round(total_elapsed / 24, 1),
        "cumulative_calories": calories,
        "calories_per_stop": config.WAFFLE_CALORIES_PER_STOP,
    }

    tsp.write_route_geojson(df, route, geojson_out, log)
    tsp.write_metrics(metrics_out, metrics, log)


if __name__ == "__main__":
    main()
