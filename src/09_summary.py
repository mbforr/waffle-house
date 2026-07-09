"""Task 9 — Compile the human-readable summary report.

Reads every artifact the pipeline produced (locations, four route metrics, the
outlier) and writes output/SUMMARY.md. The analyst (Matt) reads this to pull the
most interesting numbers into the video script. This does NOT write the script.

Outputs: output/SUMMARY.md

Usage:
    python src/09_summary.py [--force]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
import common

ROUTE_LABELS = [
    ("pure", "Pure TSP"),
    ("sleep", "With sleep"),
    ("eating", "With eating"),
    ("hurricane", "With hurricane closures"),
]


def _metrics(name):
    p = config.ROUTES_DIR / f"{name}_tsp_metrics.json"
    return json.loads(p.read_text()) if p.exists() else None


def main() -> None:
    parser = common.make_arg_parser(__doc__ or "Compile summary report")
    args = parser.parse_args()

    out = config.OUTPUT_DIR / "SUMMARY.md"
    log = common.setup_logging("09_summary", out)
    common.guard_output(out, args.force, log)
    config.ensure_dirs()

    df = common.load_waffle_houses()
    metrics = {n: _metrics(n) for n, _ in ROUTE_LABELS}
    outlier = (json.loads(config.OUTLIER_JSON.read_text())
               if config.OUTLIER_JSON.exists() else None)

    lines = []
    lines.append("# The Fastest Way to Visit Every Waffle House in America")
    lines.append("")
    lines.append("_Auto-generated pipeline summary. Numbers feed the video script;"
                 " this file is not the script._")
    lines.append("")

    # Count
    lines.append("## Locations")
    lines.append(f"- **Total Waffle Houses (continental US):** {len(df):,}")
    top_states = df["state"].value_counts().head(5)
    lines.append("- **Top states:** "
                 + ", ".join(f"{s} ({c})" for s, c in top_states.items()))
    lines.append("")

    # Outlier
    lines.append("## The outlier (the route-breaker)")
    if outlier:
        lines.append(
            f"- **{outlier['address']}, {outlier['city']}, {outlier['state']}**")
        lines.append(
            f"- Nearest other Waffle House is **{outlier['nearest_neighbor_distance_km']:,} km**"
            " away by road — the loneliest Waffle House in America.")
        lines.append(f"- Coordinates: {outlier['lat']:.4f}, {outlier['lon']:.4f}")
    else:
        lines.append("- _(run 07_find_outlier.py)_")
    lines.append("")

    # Routes
    lines.append("## The four routes")
    lines.append("")
    lines.append("| Route | Distance (km) | Drive time (h) | Elapsed (h) | Notes |")
    lines.append("|---|---|---|---|---|")
    for name, label in ROUTE_LABELS:
        m = metrics[name]
        if not m:
            lines.append(f"| {label} | _pending_ | | | |")
            continue
        elapsed = m.get("total_elapsed_hours", "—")
        note = ""
        if name == "sleep":
            note = f"{m.get('overnight_stops','?')} overnight stops"
        elif name == "eating":
            note = f"{m.get('cumulative_calories','?'):,} kcal"
        elif name == "hurricane":
            note = f"{m.get('n_closed','?')} closed; {m.get('storm','')}"
        lines.append(f"| {label} | {m['total_distance_km']:,} | "
                     f"{m['total_drive_time_hours']} | {elapsed} | {note} |")
    lines.append("")

    # Algorithm comparison
    lines.append("## Algorithm comparison")
    pure = metrics["pure"]
    if pure:
        lines.append(f"- **Naive nearest-neighbor:** {pure['naive_nn_distance_km']:,} km")
        lines.append(f"- **OR-Tools:** {pure['total_distance_km']:,} km "
                     f"({pure['improvement_pct_vs_naive']}% better than naive)")
        if "lkh_distance_km" in pure:
            lines.append(f"- **LKH-3 (optimal):** {pure['lkh_distance_km']:,} km "
                         f"(OR-Tools is {pure.get('ortools_gap_vs_lkh_pct','?')}% above optimal)")
    lines.append("")

    # Hurricanes
    lines.append("## Hurricane closures (2024 season)")
    hm = metrics["hurricane"]
    if hm:
        lines.append(f"- Modeled storm: **{hm['storm']}** "
                     f"(>= {hm['closure_threshold_mph']} mph within {hm['closure_radius_km']} km)")
        lines.append(f"- Closed during the modeled storm: **{hm['n_closed']}** locations")
        by_storm = hm.get("closures_by_storm_2024", {})
        if by_storm:
            lines.append("- Closures by 2024 storm:")
            for s, c in by_storm.items():
                lines.append(f"  - {s}: {c}")
    else:
        lines.append("- _(run 06_solve_tsp_hurricane.py)_")
    lines.append("")

    lines.append("## Anything unexpected")
    lines.append("- _Analyst note: fill in from the numbers above (e.g. how much "
                 "the outlier alone adds, how sleep dominates total elapsed time)._")
    lines.append("")

    out.write_text("\n".join(lines))
    log.info("Wrote %s", out)


if __name__ == "__main__":
    main()
