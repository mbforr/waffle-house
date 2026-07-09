"""Task 7 — Find the outlier Waffle House.

For every location, compute the road distance to its nearest OTHER Waffle House
(min over the off-diagonal row of the distance matrix). The location with the
largest nearest-neighbor distance is the outlier that stretches every optimal
route — the lonely Waffle House.

Inputs:  data/waffle_houses.parquet, data/distance_matrix.npy
Output:  data/outlier.json (id, name, address, city, state, lat, lon, nn_distance_km)

Usage:
    python src/07_find_outlier.py [--force]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
import common


def main() -> None:
    import numpy as np

    parser = common.make_arg_parser(__doc__ or "Find the outlier Waffle House")
    args = parser.parse_args()

    out = config.OUTLIER_JSON
    log = common.setup_logging("07_find_outlier", out)
    common.guard_output(out, args.force, log)
    config.ensure_dirs()

    df = common.load_waffle_houses()
    matrix = common.load_matrix().copy()

    np.fill_diagonal(matrix, np.inf)  # ignore self
    nn_dist_m = matrix.min(axis=1)
    outlier_idx = int(np.argmax(nn_dist_m))
    r = df.iloc[outlier_idx]
    nn_km = float(nn_dist_m[outlier_idx] / 1000.0)

    result = {
        "id": r["id"],
        "name": r["name"],
        "address": r["address"],
        "city": r["city"],
        "state": r["state"],
        "lat": float(r["lat"]),
        "lon": float(r["lon"]),
        "nearest_neighbor_distance_km": round(nn_km, 1),
    }
    log.info("Outlier: %s, %s %s (%.1f km to nearest neighbor)",
             r["address"], r["city"], r["state"], nn_km)

    # Context: the 5 most-isolated locations.
    top5 = np.argsort(nn_dist_m)[::-1][:5]
    log.info("Five most isolated:")
    for i in top5:
        log.info("  %-22s %s %-2s  %.1f km",
                 df.iloc[i]["city"], df.iloc[i]["state"], "",
                 nn_dist_m[i] / 1000.0)

    common.write_json(out, result, log)


if __name__ == "__main__":
    main()
