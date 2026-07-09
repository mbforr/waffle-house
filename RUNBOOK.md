# Waffle House TSP Pipeline — Run Book

How to complete and execute the full pipeline. Steps 1–9 must run **in order**;
each consumes the previous step's output.

> Status as of writing: **Task 1 already ran** (`data/waffle_houses.parquet`,
> 2,059 locations). Tasks 3–9 are written and smoke-tested on synthetic data.
> **Task 2 (the distance matrix) has not run** — it needs a local OSRM server,
> which is the one heavy piece of setup below.

---

## 0. Prerequisites (already done on this machine)

- Python venv at `.venv` (Python 3.12; **not** 3.14 — the wheels don't support it yet).
  Re-create with:
  ```bash
  python3.12 -m venv .venv
  .venv/bin/python -m pip install -r requirements.txt
  ```
- `docker` is installed. `make` and `curl` are present. **`wget` is NOT** — every
  download below uses `curl -L -o` instead.
- Always run scripts with the venv Python: `.venv/bin/python src/XX_*.py`
  (or `source .venv/bin/activate` once per shell).

### Conventions baked into every script
- `--force` is required to overwrite an existing output; otherwise the script
  exits cleanly and does nothing.
- Each script writes a sibling `.log` file next to its output.
- All paths/URLs/constants live in `config.py`. Override at runtime with env vars
  (`WAFFLE_DATA_DIR`, `WAFFLE_OUTPUT_DIR`, `OSRM_URL`, `LKH_BIN`, `OVERTURE_RELEASE`).

---

## 1. Task 1 — Pull locations (DONE, re-run only if needed)

```bash
.venv/bin/python src/01_pull_locations.py            # no-op if parquet exists
.venv/bin/python src/01_pull_locations.py --force    # re-pull from Overture
```
- Scans the full Overture `places` theme from S3 (~4 minutes).
- **Gate:** row count must land in 1,800–2,100 (currently 2,059) or it refuses to write.
- Before a fresh pull, confirm the latest Overture release at
  https://overturemaps.org and set it if newer than the default:
  ```bash
  OVERTURE_RELEASE=YYYY-MM-DD.0 .venv/bin/python src/01_pull_locations.py --force
  ```

---

## 2. Task 2 — Build the road-distance matrix (THE HEAVY STEP)

**Approach that works on this 18 GB Apple-Silicon machine: OSRM on a *filtered*
major-roads network.** Two dead ends got us here (see "Engine notes" below):
full-US OSRM OOMs (needs >20 GB RAM) and the Valhalla `latest` arm64 tile-builder
crashes deterministically. The fix: strip the OSM extract to the high-level road
network (`motorway`→`tertiary`), which shrinks it **11 GB → ~550 MB**. That graph
fits in RAM easily, OSRM builds it cleanly, and Waffle Houses snap to the nearest
major-road node (a small, accepted approximation — distances route over arterials,
not residential streets). `config.ROUTING_ENGINE` defaults to `osrm`.

### 2a. Download the US OSM extract (~10–11 GB)

```bash
mkdir -p data
curl -L -o data/us-latest.osm.pbf https://download.geofabrik.de/north-america/us-latest.osm.pbf
```
> `data/*.pbf` and `data/*.osrm*` are git-ignored — never commit them.

### 2b. Filter to the high-level road network (~1 min, needs `osmium`)

```bash
# brew install osmium-tool   # if not present
osmium tags-filter --overwrite -o data/us-major.osm.pbf data/us-latest.osm.pbf \
  w/highway=motorway,motorway_link,trunk,trunk_link,primary,primary_link,secondary,secondary_link,tertiary,tertiary_link
# result: ~550 MB, ~42M nodes, ~4M ways
```

### 2c. Build OSRM on the filtered network + serve (Docker, ~2–3 min)

```bash
docker pull osrm/osrm-backend
docker run --rm --platform linux/amd64 -v "${PWD}/data:/data" osrm/osrm-backend \
  osrm-extract -p /opt/car.lua /data/us-major.osm.pbf
docker run --rm --platform linux/amd64 -v "${PWD}/data:/data" osrm/osrm-backend \
  osrm-partition /data/us-major.osrm
docker run --rm --platform linux/amd64 -v "${PWD}/data:/data" osrm/osrm-backend \
  osrm-customize /data/us-major.osrm

# Serve on host port 5001 (NOT 5000 — macOS ControlCenter/AirPlay owns 5000).
# --max-table-size must exceed 2x the matrix batch (100x100 block = 200 coords).
docker run -d --name osrm --platform linux/amd64 -p 5001:5000 \
  -v "${PWD}/data:/data" osrm/osrm-backend \
  osrm-routed --algorithm mld --max-table-size 10000 /data/us-major.osrm
```

Verify (note the cross-country distances are real, not great-circle):
```bash
curl -s "http://localhost:5001/table/v1/driving/-84.39,33.75;-112.07,33.45;-122.27,37.80?annotations=distance"
# Atlanta->Phoenix ~2,909 km, Atlanta->Oakland ~3,963 km — code:"Ok"
```

### 2d. Build the matrix

```bash
.venv/bin/python src/02_distance_matrix.py        # ROUTING_ENGINE defaults to osrm, OSRM_URL to :5001
```
- OSRM `/table` in 100×100 blocks (441 blocks for 2,059 WH, ~4 min total).
- **Restartable:** checkpoints to `data/distance_matrix.partial.npy` every 10
  blocks; re-run after a crash and it resumes. Failed blocks retry with backoff.
- **Gate:** zero diagonal and mean asymmetry ≤ 5% (got 0.57%), else it won't
  write `data/distance_matrix.npy`. Deletes checkpoints on success.

### Stop OSRM when done
```bash
docker rm -f osrm
```

### Engine notes (why filtered-OSRM, not the obvious paths)
- **Full-US OSRM:** `osrm-extract` OOM-kills (exit 137) — the US graph needs
  >20 GB RAM; this machine has 18 GB.
- **Valhalla (full or filtered):** the gis-ops `latest` **arm64** image's
  `valhalla_build_tiles` crashes in the tile-building phase — `double free`
  on the full extract, `segfault` on the filtered one. Not a resource issue
  (reproduced with 2 threads and on a 550 MB graph). The `02_distance_matrix.py`
  Valhalla path is still wired up (`ROUTING_ENGINE=valhalla`, `/sources_to_targets`)
  for a host where the image works (e.g. a cloud x86 box).
- **Big-RAM box:** you can skip the filter and build full-US OSRM directly
  (`osrm-extract` on `us-latest.osm.pbf`), giving residential-street accuracy.

---

## 3. Tasks 3–7 — Solve and analyze

All read `data/waffle_houses.parquet` + `data/distance_matrix.npy`. The
`--time-limit` (seconds) controls the OR-Tools search; 60–300 s is reasonable at
full scale. Increase it if you want a tighter route.

```bash
.venv/bin/python src/03_solve_tsp_pure.py     --time-limit 120
.venv/bin/python src/04_solve_tsp_sleep.py    --time-limit 120
.venv/bin/python src/05_solve_tsp_eating.py   --time-limit 120
.venv/bin/python src/06_solve_tsp_hurricane.py --time-limit 120   # downloads HURDAT2 on first run
.venv/bin/python src/07_find_outlier.py
```

Outputs land in `output/routes/*.geojson` + `*_metrics.json` and `data/outlier.json`.

### Optional: LKH-3 optimal benchmark (slow — hours at 2,059 cities)

Compile once, then pass `--optimal` to Task 3:
```bash
curl -L -o LKH-3.0.13.tgz http://akira.ruc.dk/~keld/research/LKH-3/LKH-3.0.13.tgz
tar xvfz LKH-3.0.13.tgz
cd LKH-3.0.13 && make && cd ..        # binary at LKH-3.0.13/LKH (matches config.LKH_BIN)

.venv/bin/python src/03_solve_tsp_pure.py --force --optimal --time-limit 120
```
The metrics JSON then includes `lkh_distance_km` and the OR-Tools gap vs optimal.

---

## 4. Tasks 8–9 — Visualize and report

```bash
.venv/bin/python src/08_visualize.py    # 4 kepler.gl maps + 2 Plotly charts
.venv/bin/python src/09_summary.py      # output/SUMMARY.md
```
- Maps: `output/maps/route_{pure,sleep,eating,hurricane}.html` (~11 MB each).
- Charts: `output/charts/{algorithm_comparison,constraint_cost}.html`.
- Open `output/SUMMARY.md` — that's what feeds the video script.

---

## 5. Full pipeline, end to end (after OSRM is up at :5000)

```bash
source .venv/bin/activate
python src/02_distance_matrix.py
python src/03_solve_tsp_pure.py     --time-limit 120
python src/04_solve_tsp_sleep.py    --time-limit 120
python src/05_solve_tsp_eating.py   --time-limit 120
python src/06_solve_tsp_hurricane.py --time-limit 120
python src/07_find_outlier.py
python src/08_visualize.py
python src/09_summary.py
```

---

## 6. Validation gates (check before declaring done)

1. **Locations** in 1,800–2,100. ✅ (2,059)
2. **Matrix** symmetric (mean asymmetry ≤ 5%) with zero diagonal. *(checked by Task 2)*
3. **Optimal route** distance in **30,000–40,000 km**. *(read `pure_tsp_metrics.json`)*
4. **Outlier** geographically plausible (AZ/CO-ish). *(synthetic test already pointed at Tucson, AZ)*
5. **Constrained runs longer than pure** — see the caveat below.
6. **All four maps render** as a continuous animated path.

### Caveat on gate 5 (important)
- **Sleep** and **eating** add *time*, not distance. For a single vehicle visiting
  every node, the optimal driving order doesn't change, so their **distance equals
  pure**; their **elapsed time is strictly longer** (rest hours / eating hours).
  Compare on `total_elapsed_hours`, not `total_distance_km`.
- **Hurricane** removes closed nodes, so its **distance is usually slightly
  *shorter*** than pure (fewer stops). This contradicts gate 5 read literally — it
  is correct modeling, not a bug. Treat gate 5 as "elapsed time escalates across
  sleep/eating; hurricane is the closure scenario."

---

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| `osrm-extract` exits ~137 (OOM) | Raise Docker memory to 12–16 GB. |
| `docker: error creating temporary lease ... input/output error` | **Host disk is full**, not Docker. Check `df -h /System/Volumes/Data`. Free 40 GB+ (Docker's `~/Library/.../Docker.raw` is the usual hog — quit Docker Desktop, delete the raw to reset, relaunch). Need ~40 GB free for the US build. |
| `curl http://localhost:5000/...` refuses connection | The `osrm-routed` container isn't running (step 2c). |
| Task 2 slow / intermittent 5xx | Expected under load; it retries with backoff. Let it run. |
| `ModuleNotFoundError: pkg_resources` (keplergl) | `setuptools<81` must be installed — it's pinned in `requirements.txt`. |
| Wrong/empty Overture results | Verify the release date at overturemaps.org; set `OVERTURE_RELEASE`. |
| A script "does nothing" | Output already exists — add `--force`. |
| Want a fast dry run without OSRM | Point `WAFFLE_DATA_DIR`/`WAFFLE_OUTPUT_DIR` at a temp dir, drop in a parquet + a placeholder `distance_matrix.npy`, and run 03–09 there (this is how the pipeline was smoke-tested). |

---

## 8. What's verified vs. not (so far)

- **Task 1:** run for real against live Overture — works (2,059 rows).
- **Tasks 3–9:** run end-to-end on an 80-location synthetic (haversine) matrix —
  all produce well-formed output. **Not yet run at full 2,059 scale or on real
  OSRM road distances.**
- **Task 2 and LKH-3:** written but **never executed** — they need the OSRM build
  / the compiled binary above. Expect to debug these on first real run.
