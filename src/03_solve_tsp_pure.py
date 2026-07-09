"""Task 3 — Solve the pure (unconstrained) TSP.

OR-Tools is the publishable solver. LKH-3 is wired in as an optional optimal
benchmark behind ``--optimal`` (off by default; it can run for hours on 1,900
cities). Reports total distance/time, the naive nearest-neighbor baseline, and
the percent improvement over it.

Inputs:  data/waffle_houses.parquet, data/distance_matrix.npy
Outputs: output/routes/pure_tsp.geojson, output/routes/pure_tsp_metrics.json

Usage:
    python src/03_solve_tsp_pure.py [--force] [--time-limit 60] [--optimal]
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
    parser = common.make_arg_parser(__doc__ or "Pure TSP")
    parser.add_argument("--time-limit", type=int, default=60)
    parser.add_argument("--optimal", action="store_true",
                        help="Also run LKH-3 optimal benchmark (slow).")
    args = parser.parse_args()

    geojson_out = config.ROUTES_DIR / "pure_tsp.geojson"
    metrics_out = config.ROUTES_DIR / "pure_tsp_metrics.json"
    log = common.setup_logging("03_solve_tsp_pure", geojson_out)
    common.guard_output(geojson_out, args.force, log)
    config.ensure_dirs()

    df = common.load_waffle_houses()
    matrix = common.load_matrix()
    log.info("Loaded %d locations, matrix %s", len(df), matrix.shape)

    nn_route, nn_m = tsp.nearest_neighbor_route(matrix)
    log.info("Nearest-neighbor baseline: %.0f km", nn_m / tsp.M_PER_KM)

    log.info("Solving OR-Tools (time limit %ds)...", args.time_limit)
    route, dist_m = tsp.solve_ortools(matrix, args.time_limit, log)
    dist_km = dist_m / tsp.M_PER_KM
    improvement = 100 * (nn_m - dist_m) / nn_m
    log.info("OR-Tools route: %.0f km (%.1f%% better than naive)", dist_km, improvement)

    metrics = {
        "solver": "ortools",
        "n_stops": len(route),
        "total_distance_km": round(dist_km, 1),
        "total_drive_time_hours": round(tsp.drive_hours_from_m(dist_m), 1),
        "naive_nn_distance_km": round(nn_m / tsp.M_PER_KM, 1),
        "improvement_pct_vs_naive": round(improvement, 2),
    }

    if args.optimal:
        log.info("Running LKH-3 optimal benchmark...")
        lkh_route, lkh_m = tsp.solve_lkh(matrix, config.LKH_BIN,
                                         config.DATA_DIR / "lkh_work", logger=log)
        metrics["lkh_distance_km"] = round(lkh_m / tsp.M_PER_KM, 1)
        metrics["ortools_gap_vs_lkh_pct"] = round(100 * (dist_m - lkh_m) / lkh_m, 2)
        log.info("LKH-3 route: %.0f km", lkh_m / tsp.M_PER_KM)

    tsp.write_route_geojson(df, route, geojson_out, log)
    tsp.write_metrics(metrics_out, metrics, log)


if __name__ == "__main__":
    main()
