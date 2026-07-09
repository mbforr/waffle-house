"""Shared TSP solving + route-output helpers used by Tasks 3-6.

Keeps the OR-Tools setup, the LKH-3 file/subprocess dance, the nearest-neighbor
baseline, and the GeoJSON/metrics writers in one place so each constrained
variant only expresses what makes it different.

All distances are in METERS (OSRM matrix units) internally; helpers convert to
km / hours for reporting.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np

import config

M_PER_KM = 1000.0
MPH_TO_KMH = 1.609344


# --------------------------------------------------------------------------- #
# Baselines and metrics
# --------------------------------------------------------------------------- #
def route_distance_m(matrix: np.ndarray, route: list[int], closed: bool = True) -> float:
    """Total meters along ``route``; if ``closed`` add the return-to-start leg."""
    d = sum(matrix[route[i], route[i + 1]] for i in range(len(route) - 1))
    if closed and len(route) > 1:
        d += matrix[route[-1], route[0]]
    return float(d)


def nearest_neighbor_route(matrix: np.ndarray, start: int = 0) -> tuple[list[int], float]:
    """Greedy nearest-neighbor tour — the naive baseline to beat."""
    n = len(matrix)
    unvisited = set(range(n))
    unvisited.remove(start)
    route = [start]
    cur = start
    while unvisited:
        nxt = min(unvisited, key=lambda j: matrix[cur, j])
        unvisited.remove(nxt)
        route.append(nxt)
        cur = nxt
    return route, route_distance_m(matrix, route)


def drive_hours_from_m(distance_m: float, speed_mph: float = config.HIGHWAY_SPEED_MPH) -> float:
    km = distance_m / M_PER_KM
    return km / (speed_mph * MPH_TO_KMH)


# --------------------------------------------------------------------------- #
# OR-Tools (heuristic) — the publishable solver
# --------------------------------------------------------------------------- #
def solve_ortools(matrix: np.ndarray, time_limit_seconds: int = 60,
                  logger=None) -> tuple[list[int], float]:
    """Single-vehicle TSP via OR-Tools (PATH_CHEAPEST_ARC + GUIDED_LOCAL_SEARCH)."""
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2

    n = len(matrix)
    manager = pywrapcp.RoutingIndexManager(n, 1, 0)
    routing = pywrapcp.RoutingModel(manager)
    # Integer-meter matrix for the callback (OR-Tools needs ints).
    int_matrix = np.rint(matrix).astype(np.int64)

    def distance_callback(from_index, to_index):
        return int(int_matrix[manager.IndexToNode(from_index),
                              manager.IndexToNode(to_index)])

    transit_idx = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_idx)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC)
    params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH)
    params.time_limit.seconds = time_limit_seconds

    solution = routing.SolveWithParameters(params)
    if solution is None:
        raise RuntimeError("OR-Tools found no solution")

    route, index = [], routing.Start(0)
    while not routing.IsEnd(index):
        route.append(manager.IndexToNode(index))
        index = solution.Value(routing.NextVar(index))
    return route, route_distance_m(matrix, route)


# --------------------------------------------------------------------------- #
# LKH-3 (optimal benchmark) — optional, off by default
# --------------------------------------------------------------------------- #
def solve_lkh(matrix: np.ndarray, lkh_binary: str, work_dir: Path,
              runs: int = 10, max_trials: int = 10000,
              logger=None) -> tuple[list[int], float]:
    """Optimal-ish tour via LKH-3. Writes .tsp/.par, runs the binary, parses."""
    n = len(matrix)
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    tsp_file, par_file, out_file = (work / "problem.tsp",
                                    work / "problem.par", work / "problem.out")

    int_matrix = np.rint(matrix).astype(np.int64)
    with open(tsp_file, "w") as f:
        f.write(f"NAME: waffle\nTYPE: TSP\nDIMENSION: {n}\n")
        f.write("EDGE_WEIGHT_TYPE: EXPLICIT\nEDGE_WEIGHT_FORMAT: FULL_MATRIX\n")
        f.write("EDGE_WEIGHT_SECTION\n")
        for row in int_matrix:
            f.write(" ".join(str(int(d)) for d in row) + "\n")
        f.write("EOF\n")
    with open(par_file, "w") as f:
        f.write(f"PROBLEM_FILE = {tsp_file}\n")
        f.write(f"OUTPUT_TOUR_FILE = {out_file}\n")
        f.write(f"RUNS = {runs}\nMAX_TRIALS = {max_trials}\n")

    if logger:
        logger.info("Running LKH-3 (%s)... this can take a long time on %d cities.",
                    lkh_binary, n)
    subprocess.run([lkh_binary, str(par_file)], check=True)

    lines = out_file.read_text().splitlines()
    start = lines.index("TOUR_SECTION") + 1
    route = []
    for line in lines[start:]:
        node = int(line.strip())
        if node == -1:
            break
        route.append(node - 1)  # LKH is 1-indexed
    return route, route_distance_m(matrix, route)


# --------------------------------------------------------------------------- #
# Output writers
# --------------------------------------------------------------------------- #
def write_route_geojson(df, route: list[int], path: Path, logger,
                        node_index: list[int] | None = None,
                        closed: bool = True,
                        extra_features: list | None = None) -> None:
    """Write the route as a GeoJSON LineString (route order) + Point features.

    ``route`` indexes into ``df`` rows (or into ``node_index`` if the matrix was
    a subset of df, as in the hurricane variant). ``extra_features`` are appended
    verbatim (e.g. the hurricane variant's closed-store points, kind="closed").
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    def df_row(matrix_idx):
        return df.iloc[node_index[matrix_idx]] if node_index is not None \
            else df.iloc[matrix_idx]

    ordered = route + ([route[0]] if closed and route else [])
    line_coords = [[float(df_row(i)["lon"]), float(df_row(i)["lat"])] for i in ordered]

    features = [{
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": line_coords},
        "properties": {"kind": "route", "n_stops": len(route)},
    }]
    for order, i in enumerate(route):
        r = df_row(i)
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point",
                         "coordinates": [float(r["lon"]), float(r["lat"])]},
            "properties": {"kind": "stop", "order": order, "id": r["id"],
                           "name": r["name"], "city": r["city"], "state": r["state"]},
        })
    if extra_features:
        features.extend(extra_features)
    geojson = {"type": "FeatureCollection", "features": features}
    with open(path, "w") as f:
        json.dump(geojson, f)
    logger.info("Wrote %s (%d stops%s)", path, len(route),
                f", +{len(extra_features)} extra" if extra_features else "")


def write_metrics(path: Path, metrics: dict, logger) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(metrics, f, indent=2)
    logger.info("Wrote %s", path)
