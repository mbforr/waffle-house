"""Task 8 — Generate the visualizations.

kepler.gl HTML maps animate each solved route over the US; Plotly charts compare
the algorithms and the per-constraint cost. Reads the GeoJSON routes and metrics
produced by Tasks 3-6.

Outputs:
    output/maps/route_pure.html, route_sleep.html, route_eating.html,
        route_hurricane.html
    output/charts/algorithm_comparison.html
    output/charts/constraint_cost.html

Usage:
    python src/08_visualize.py [--force]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
import common

ROUTES = [
    ("pure", "Pure TSP"),
    ("sleep", "With Sleep"),
    ("eating", "With Eating"),
    ("hurricane", "With Hurricane Closures"),
]


def _load(name):
    """Return (geojson dict, metrics dict) for a route name, or (None, None)."""
    gj = config.ROUTES_DIR / f"{name}_tsp.geojson"
    mt = config.ROUTES_DIR / f"{name}_tsp_metrics.json"
    geo = json.loads(gj.read_text()) if gj.exists() else None
    met = json.loads(mt.read_text()) if mt.exists() else None
    return geo, met


def build_map(name, label, geojson, log):
    """Render one kepler.gl HTML map with the route's stops as an ordered path."""
    from keplergl import KeplerGl

    # Extract stop points ordered along the route for an animated path.
    stops = [f for f in geojson["features"] if f["properties"].get("kind") == "stop"]
    stops.sort(key=lambda f: f["properties"]["order"])
    rows = [{
        "order": f["properties"]["order"],
        "name": f["properties"]["name"],
        "city": f["properties"]["city"],
        "state": f["properties"]["state"],
        "lon": f["geometry"]["coordinates"][0],
        "lat": f["geometry"]["coordinates"][1],
    } for f in stops]

    import pandas as pd

    m = KeplerGl(height=800)
    m.add_data(data=pd.DataFrame(rows), name=f"{label} stops")
    m.add_data(data=geojson, name=f"{label} route")
    out = config.MAPS_DIR / f"route_{name}.html"
    m.save_to_html(file_name=str(out))
    log.info("Wrote %s (%d stops)", out, len(rows))


def build_algorithm_chart(metrics_by_name, log):
    """Naive vs OR-Tools (vs LKH-3 if present) for the pure run."""
    import plotly.graph_objects as go

    pure = metrics_by_name.get("pure")
    if not pure:
        log.warning("No pure metrics; skipping algorithm chart.")
        return
    labels, values = ["Naive NN", "OR-Tools"], [
        pure["naive_nn_distance_km"], pure["total_distance_km"]]
    if "lkh_distance_km" in pure:
        labels.append("LKH-3 (optimal)")
        values.append(pure["lkh_distance_km"])

    fig = go.Figure([go.Bar(x=labels, y=values,
                            text=[f"{v:,.0f} km" for v in values],
                            textposition="auto")])
    fig.update_layout(title="Algorithm comparison — total route distance",
                      yaxis_title="Distance (km)")
    out = config.CHARTS_DIR / "algorithm_comparison.html"
    fig.write_html(str(out))
    log.info("Wrote %s", out)


def build_constraint_chart(metrics_by_name, log):
    """How each constraint adds distance and elapsed time."""
    import plotly.graph_objects as go

    names = [n for n, _ in ROUTES if n in metrics_by_name]
    labels = [lbl for n, lbl in ROUTES if n in metrics_by_name]
    dist = [metrics_by_name[n]["total_distance_km"] for n in names]
    elapsed = [metrics_by_name[n].get("total_elapsed_hours",
               metrics_by_name[n]["total_drive_time_hours"]) for n in names]

    fig = go.Figure()
    fig.add_bar(name="Distance (km)", x=labels, y=dist, yaxis="y")
    fig.add_scatter(name="Elapsed (h)", x=labels, y=elapsed, yaxis="y2",
                    mode="lines+markers")
    fig.update_layout(
        title="Cost of each constraint",
        yaxis=dict(title="Distance (km)"),
        yaxis2=dict(title="Elapsed time (hours)", overlaying="y", side="right"),
    )
    out = config.CHARTS_DIR / "constraint_cost.html"
    fig.write_html(str(out))
    log.info("Wrote %s", out)


def main() -> None:
    parser = common.make_arg_parser(__doc__ or "Generate visualizations")
    args = parser.parse_args()

    # Guard on the first map output as the representative artifact.
    first_map = config.MAPS_DIR / "route_pure.html"
    log = common.setup_logging("08_visualize", first_map)
    common.guard_output(first_map, args.force, log)
    config.ensure_dirs()

    metrics_by_name = {}
    for name, label in ROUTES:
        geo, met = _load(name)
        if met:
            metrics_by_name[name] = met
        if geo:
            build_map(name, label, geo, log)
        else:
            log.warning("Route %s missing; skipping its map.", name)

    build_algorithm_chart(metrics_by_name, log)
    build_constraint_chart(metrics_by_name, log)
    log.info("Visualization complete.")


if __name__ == "__main__":
    main()
