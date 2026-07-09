# Waffle House TSP Pipeline

## Project goal

Build the data and analysis pipeline for a YouTube video titled "The Fastest Way to Visit Every Waffle House in America." The pipeline pulls every Waffle House location from Overture Maps using SedonaDB, computes road distances between all of them with OSRM, solves the Traveling Salesman Problem four times under increasing real-world constraints, and produces visualizations for the video.

The final deliverables are a clean CSV of locations, a 1,900 x 1,900 road distance matrix, four solved routes (pure TSP, with sleep constraint, with eating constraint, with hurricane closure constraint), and a kepler.gl visualization for each route.

## Tech stack

- **SedonaDB** (`sedonadb`) for spatial queries against Overture Maps. Local Python package, Rust-backed, single-node. No cluster setup needed.
- **OSRM** for road distance computation. Run locally via Docker with the OSM US extract from Geofabrik.
- **OR-Tools** for constrained TSP (time windows, capacity).
- **LKH-3** (Lin-Kernighan-Helsgaun) for the optimal benchmark. Compiled from source, binary called via subprocess.
- **GeoPandas** for general geometric operations and CSV/Parquet handling.
- **kepler.gl** (Python bindings via `keplergl` package) for the route animation maps.
- **Plotly** for the algorithm comparison charts.
- **Pandas** and **NumPy** for general data work.

## Setup

```bash
# Python environment
python -m venv .venv
source .venv/bin/activate
pip install sedonadb geopandas pandas numpy ortools requests keplergl plotly

# OSRM (Docker)
docker pull osrm/osrm-backend
# Pull the latest US OSM extract from Geofabrik
wget https://download.geofabrik.de/north-america/us-latest.osm.pbf -O data/us-latest.osm.pbf
docker run -t -v "${PWD}/data:/data" osrm/osrm-backend osrm-extract -p /opt/car.lua /data/us-latest.osm.pbf
docker run -t -v "${PWD}/data:/data" osrm/osrm-backend osrm-partition /data/us-latest.osrm
docker run -t -v "${PWD}/data:/data" osrm/osrm-backend osrm-customize /data/us-latest.osrm
docker run -t -i -p 5000:5000 -v "${PWD}/data:/data" osrm/osrm-backend osrm-routed --algorithm mld /data/us-latest.osrm

# LKH-3
wget http://akira.ruc.dk/~keld/research/LKH-3/LKH-3.0.13.tgz
tar xvfz LKH-3.0.13.tgz
cd LKH-3.0.13 && make
# Binary will be at LKH-3.0.13/LKH
```

## File structure

```
waffle-house-pipeline/
├── CLAUDE.md                # This file
├── data/
│   ├── waffle_houses.parquet     # Pulled from Overture via SedonaDB
│   ├── distance_matrix.npy       # 1900x1900 road distances from OSRM
│   ├── hurdat2.csv               # NOAA hurricane track data
│   └── us-latest.osm.pbf         # Geofabrik OSM extract
├── src/
│   ├── 01_pull_locations.py      # SedonaDB query → waffle_houses.parquet
│   ├── 02_distance_matrix.py     # OSRM batch routing → distance_matrix.npy
│   ├── 03_solve_tsp_pure.py      # Vanilla TSP
│   ├── 04_solve_tsp_sleep.py     # With overnight rest constraint
│   ├── 05_solve_tsp_eating.py    # With per-stop eating time
│   ├── 06_solve_tsp_hurricane.py # With dynamic closures
│   └── 07_visualize.py           # kepler.gl maps for each route
├── output/
│   ├── routes/                   # GeoJSON for each solved route
│   ├── maps/                     # HTML kepler.gl exports
│   └── charts/                   # Plotly algorithm comparisons
└── notebooks/
    └── exploration.ipynb         # Optional, for ad-hoc analysis
```

## Conventions

- All coordinates use EPSG:4326 (WGS84 lon/lat) unless explicitly noted.
- Distances in road kilometers (from OSRM), not haversine.
- Every script writes outputs to `data/` or `output/` and never overwrites without a `--force` flag.
- Every script logs progress to stdout and saves an `.log` file alongside its output.
- Use Parquet for tabular data over CSV when the data is more than 10k rows.
- Never hard-code paths. Use a `config.py` at the repo root with `DATA_DIR`, `OUTPUT_DIR`, `OSRM_URL`, and `LKH_BIN`.

## SedonaDB query patterns

SedonaDB reads Overture Maps Parquet files directly from S3 or Azure without needing to download the full dataset. The Overture places theme has brand information for chain restaurants. Query pattern:

```python
import sedonadb

# Connect to local SedonaDB
db = sedonadb.connect()

# Pull every Waffle House from Overture's places theme
query = """
SELECT
    id,
    names.primary AS name,
    ST_X(geometry) AS lon,
    ST_Y(geometry) AS lat,
    addresses[1].freeform AS address,
    addresses[1].locality AS city,
    addresses[1].region AS state,
    brand.names.primary AS brand
FROM read_parquet('s3://overturemaps-us-west-2/release/2026-05-20.0/theme=places/type=place/*')
WHERE
    LOWER(brand.names.primary) = 'waffle house'
    AND ST_Within(
        geometry,
        ST_GeomFromText('POLYGON((-125 24, -66 24, -66 50, -125 50, -125 24))')
    )
"""

df = db.sql(query).to_pandas()
df.to_parquet('data/waffle_houses.parquet')
```

Notes on the query:

- The `read_parquet` path uses Overture's official S3 bucket and the latest release date. Update the release path to the most recent Overture release before each run.
- The bounding box filter restricts to the continental US to avoid pulling any international locations or Alaska/Hawaii outliers. Verify this matches the video's scope. The plan focuses on the continental US.
- Cross-validate by also pulling locations where `names.primary` contains "Waffle House" in case the brand attribution is incomplete for some records.
- Expected output: 1,900 to 2,050 locations.

## OSRM batch routing pattern

OSRM provides a `/table` endpoint that returns a distance matrix for up to 100 locations per call. For 1,900 Waffle Houses we need to batch the calls.

```python
import requests
import numpy as np
from itertools import product

BATCH_SIZE = 100
OSRM_URL = "http://localhost:5000"

def get_table_distances(sources, destinations):
    """Returns a sources x destinations matrix of road distances in meters."""
    src_coords = ";".join(f"{lon},{lat}" for lon, lat in sources)
    dst_coords = ";".join(f"{lon},{lat}" for lon, lat in destinations)
    coords = src_coords + ";" + dst_coords
    src_idx = ";".join(str(i) for i in range(len(sources)))
    dst_idx = ";".join(str(i + len(sources)) for i in range(len(destinations)))
    url = f"{OSRM_URL}/table/v1/driving/{coords}?sources={src_idx}&destinations={dst_idx}&annotations=distance"
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    return np.array(r.json()["distances"])

# Build full 1900x1900 matrix by batching
n = len(waffle_houses)
matrix = np.zeros((n, n), dtype=np.float32)
for i in range(0, n, BATCH_SIZE):
    for j in range(0, n, BATCH_SIZE):
        srcs = waffle_houses[i:i+BATCH_SIZE]
        dsts = waffle_houses[j:j+BATCH_SIZE]
        matrix[i:i+len(srcs), j:j+len(dsts)] = get_table_distances(srcs, dsts)

np.save("data/distance_matrix.npy", matrix)
```

Notes on routing:

- 1,900 squared is 3.6 million pairwise distances. At 100 per batch this is 361 batches. Each batch takes ~5 seconds on a local OSRM. Total runtime ~30 minutes.
- Save intermediate progress every 10,000 pairs in case the run crashes. The script should be restartable.
- Cache the matrix to disk. Never recompute unless the source location list changes.

## TSP solver patterns

### Pure TSP with OR-Tools

```python
from ortools.constraint_solver import pywrapcp, routing_enums_pb2

def solve_tsp_ortools(distance_matrix, time_limit_seconds=60):
    n = len(distance_matrix)
    manager = pywrapcp.RoutingIndexManager(n, 1, 0)
    routing = pywrapcp.RoutingModel(manager)
    
    def distance_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return int(distance_matrix[from_node][to_node])
    
    transit_callback_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)
    
    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    search_parameters.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    search_parameters.time_limit.seconds = time_limit_seconds
    
    solution = routing.SolveWithParameters(search_parameters)
    
    route = []
    index = routing.Start(0)
    while not routing.IsEnd(index):
        route.append(manager.IndexToNode(index))
        index = solution.Value(routing.NextVar(index))
    return route, solution.ObjectiveValue()
```

### Optimal TSP with LKH-3

LKH-3 is a CLI tool. Generate a `.tsp` problem file, run the binary, parse the output:

```python
import subprocess
from pathlib import Path

def solve_tsp_lkh(distance_matrix, lkh_binary, work_dir):
    n = len(distance_matrix)
    work = Path(work_dir)
    work.mkdir(exist_ok=True)
    
    # Write TSP file
    tsp_file = work / "problem.tsp"
    with open(tsp_file, "w") as f:
        f.write(f"NAME: waffle\nTYPE: TSP\nDIMENSION: {n}\n")
        f.write("EDGE_WEIGHT_TYPE: EXPLICIT\nEDGE_WEIGHT_FORMAT: FULL_MATRIX\n")
        f.write("EDGE_WEIGHT_SECTION\n")
        for row in distance_matrix:
            f.write(" ".join(str(int(d)) for d in row) + "\n")
        f.write("EOF\n")
    
    # Write parameter file
    par_file = work / "problem.par"
    out_file = work / "problem.out"
    with open(par_file, "w") as f:
        f.write(f"PROBLEM_FILE = {tsp_file}\n")
        f.write(f"OUTPUT_TOUR_FILE = {out_file}\n")
        f.write("RUNS = 10\n")
        f.write("MAX_TRIALS = 10000\n")
    
    # Run LKH
    subprocess.run([lkh_binary, str(par_file)], check=True)
    
    # Parse output
    with open(out_file) as f:
        lines = f.readlines()
    tour_start = lines.index("TOUR_SECTION\n") + 1
    route = []
    for line in lines[tour_start:]:
        node = int(line.strip())
        if node == -1:
            break
        route.append(node - 1)  # LKH uses 1-indexed
    return route
```

### Constrained variants

For runs 2 (sleep), 3 (eating), and 4 (hurricanes), use OR-Tools' VRP with custom constraints. The patterns:

- **Sleep:** add a time dimension where the driver accumulates driving hours. Every 16 hours, force a stop at the nearest location and add 8 hours of "rest" cost.
- **Eating:** add a service time at every node (30 minutes). The total time grows linearly with the number of stops.
- **Hurricanes:** dynamically remove nodes from the routing graph based on closure status during a real hurricane track. Use NOAA HURDAT2 wind speed at each location to determine closure. Threshold: above 75 mph sustained winds equals closure.

## Hurricane data pattern

```python
import pandas as pd

# Parse NOAA HURDAT2 format
def parse_hurdat2(filepath):
    """Returns DataFrame of hurricane positions with wind speed."""
    rows = []
    current_storm = None
    with open(filepath) as f:
        for line in f:
            if line.startswith("AL") or line.startswith("EP"):
                parts = [p.strip() for p in line.split(",")]
                current_storm = {"id": parts[0], "name": parts[1]}
            elif current_storm and "," in line:
                parts = [p.strip() for p in line.split(",")]
                rows.append({
                    "storm_id": current_storm["id"],
                    "storm_name": current_storm["name"],
                    "datetime": parts[0] + parts[1],
                    "lat": float(parts[4].rstrip("N").rstrip("S")) * (-1 if parts[4].endswith("S") else 1),
                    "lon": float(parts[5].rstrip("W").rstrip("E")) * (-1 if parts[5].endswith("W") else 1),
                    "wind_mph": int(parts[6]),
                })
    return pd.DataFrame(rows)

# Use to compute Waffle House closures during a specific storm
def closures_for_storm(waffle_houses, storm_track, closure_threshold_mph=75, radius_km=80):
    """Returns a list of Waffle House IDs closed during the storm."""
    closures = []
    for _, point in storm_track.iterrows():
        if point["wind_mph"] >= closure_threshold_mph:
            # Find WHs within radius_km of this storm position
            nearby = waffle_houses[
                ((waffle_houses["lat"] - point["lat"]) ** 2 +
                 (waffle_houses["lon"] - point["lon"]) ** 2) ** 0.5 * 111 < radius_km
            ]
            closures.extend(nearby["id"].tolist())
    return list(set(closures))
```

For the video, use Hurricane Helene (2024) as the modeled scenario. Download HURDAT2 from NHC: https://www.nhc.noaa.gov/data/hurdat/hurdat2-1851-2024-040425.txt

## Tasks (run in order)

Each task should produce a file in `data/` or `output/` that the next task consumes. Do not run task N+1 until task N succeeds and produces the expected output.

### Task 1. Pull Waffle House locations

- Script: `src/01_pull_locations.py`
- Tool: SedonaDB querying Overture Maps places theme
- Output: `data/waffle_houses.parquet` with columns `id, name, lon, lat, address, city, state, brand`
- Validation: row count between 1,800 and 2,100. Cross-check against the Waffle House store locator at locations.wafflehouse.com for spot accuracy on 5 random locations.

### Task 2. Build road distance matrix

- Script: `src/02_distance_matrix.py`
- Tool: OSRM batch routing
- Output: `data/distance_matrix.npy`, a float32 NumPy array of shape (N, N) where N is the location count
- Validation: matrix should be approximately symmetric (allow small asymmetry from one-way roads). Diagonal should be zero.

### Task 3. Solve pure TSP

- Script: `src/03_solve_tsp_pure.py`
- Tool: OR-Tools for fast heuristic, LKH-3 for optimal benchmark
- Output: `output/routes/pure_tsp.geojson` and `output/routes/pure_tsp_metrics.json`
- Metrics JSON contains: total distance (km), total drive time (hours), naive nearest-neighbor comparison, percent improvement.

### Task 4. Solve TSP with sleep

- Script: `src/04_solve_tsp_sleep.py`
- Tool: OR-Tools VRP with time dimension
- Output: `output/routes/sleep_tsp.geojson` and metrics JSON
- Add 8 hours of rest after every 16 hours of driving. Use 60 mph average highway speed for time-from-distance conversion.

### Task 5. Solve TSP with eating

- Script: `src/05_solve_tsp_eating.py`
- Tool: OR-Tools VRP with service time
- Output: `output/routes/eating_tsp.geojson` and metrics JSON
- Add 30 minutes of service time at every node. Track cumulative calories.

### Task 6. Solve TSP with hurricane closures

- Script: `src/06_solve_tsp_hurricane.py`
- Tool: OR-Tools VRP with dynamic node availability
- Output: `output/routes/hurricane_tsp.geojson` and metrics JSON
- Use Hurricane Helene 2024 track. Closure threshold: 75 mph sustained wind within 80 km radius.

### Task 7. Identify the outlier location

- Script: `src/07_find_outlier.py`
- For every Waffle House, compute the road distance to the nearest other Waffle House. The location with the largest "nearest neighbor" distance is the outlier that breaks every optimal route.
- Output: `data/outlier.json` with the location ID, name, address, coordinates, and nearest-neighbor distance.

### Task 8. Generate visualizations

- Script: `src/08_visualize.py`
- Tool: kepler.gl for route animation, Plotly for charts
- Outputs:
  - `output/maps/route_pure.html` (animated route over US)
  - `output/maps/route_sleep.html`
  - `output/maps/route_eating.html`
  - `output/maps/route_hurricane.html`
  - `output/charts/algorithm_comparison.html` (naive vs heuristic vs optimal bar chart)
  - `output/charts/constraint_cost.html` (how each constraint adds distance and time)

### Task 9. Summary report

- Script: `src/09_summary.py`
- Compile a single Markdown report (`output/SUMMARY.md`) with:
  - Total Waffle House count
  - The outlier location and its story
  - All four route distances (pure, sleep, eating, hurricane)
  - Algorithm comparison (naive vs OR-Tools vs LKH-3)
  - Hurricane closure count and which storms hit how many
  - Anything unexpected the data revealed

## Validation gates

Before declaring the pipeline complete:

1. Row count of Waffle Houses is within the expected range.
2. Distance matrix is symmetric within 5 percent average asymmetry.
3. Optimal TSP route distance is between 30,000 and 40,000 km.
4. The outlier location is geographically plausible (likely Arizona, Colorado, or similar).
5. The sleep, eating, and hurricane runs all produce strictly longer routes than the pure TSP.
6. All four kepler.gl maps render without errors and show the route as a continuous animated path.

## Common commands

```bash
# Run the full pipeline
python src/01_pull_locations.py
python src/02_distance_matrix.py
python src/03_solve_tsp_pure.py
python src/04_solve_tsp_sleep.py
python src/05_solve_tsp_eating.py
python src/06_solve_tsp_hurricane.py
python src/07_find_outlier.py
python src/08_visualize.py
python src/09_summary.py

# Force-rerun a single step
python src/03_solve_tsp_pure.py --force

# Check OSRM is up
curl http://localhost:5000/route/v1/driving/-84.388,33.749;-84.45,33.78

# Stop OSRM
docker stop $(docker ps -q --filter ancestor=osrm/osrm-backend)
```

## Notes for Claude Code

- The SedonaDB Overture release path needs to be updated to the most recent release date before running task 1. Check overturemaps.org for the current release.
- Do not commit `data/us-latest.osm.pbf` to git. It is 10+ GB. Add it to `.gitignore`.
- The LKH-3 binary takes hours to run on 1,900 cities at default settings. Use `RUNS = 10` and `MAX_TRIALS = 10000` for a good balance of accuracy and runtime. For the video, OR-Tools' solution is publishable. LKH-3 is the benchmark only.
- If OSRM batch calls fail intermittently, retry with exponential backoff. The local OSRM instance can choke under load.
- The Waffle House brand spelling in Overture may vary ("Waffle House", "WAFFLE HOUSE", "Waffle House Inc"). The query should normalize on lowercase.
- After the pipeline runs, the analyst (Matt) reads SUMMARY.md and pulls the most interesting numbers for the script. Do not autogenerate the script from this pipeline. The script comes from the youtube-longform-script-writer skill after the data is in.

## Reference document

The video plan this pipeline supports lives at `Video7_Waffle_House_TSP_PLAN.md` in the same outputs folder. Reference that document for the narrative arc, the four-constraint escalation logic, and the hidden science segments the video will eventually cover.