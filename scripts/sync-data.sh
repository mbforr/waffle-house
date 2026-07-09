#!/usr/bin/env bash
# Refresh the app's bundled route data from the pipeline output.
# Run after re-running the TSP solvers so the deployed app matches.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p app/data
cp output/routes/{pure,sleep,eating,hurricane}_tsp.geojson app/data/
cp output/routes/{pure,sleep,eating,hurricane}_tsp_metrics.json app/data/
echo "Synced $(ls app/data | wc -l | tr -d ' ') files into app/data/"
