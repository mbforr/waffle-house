"""Central configuration for the Waffle House TSP pipeline.

Every script imports paths and constants from here. Never hard-code paths
elsewhere (see CLAUDE.md conventions).
"""

import os
from pathlib import Path

# --- Repo root -------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent

# --- Top-level directories (overridable via env vars) ----------------------
DATA_DIR = Path(os.environ.get("WAFFLE_DATA_DIR", REPO_ROOT / "data"))
OUTPUT_DIR = Path(os.environ.get("WAFFLE_OUTPUT_DIR", REPO_ROOT / "output"))

# --- Derived output subdirectories -----------------------------------------
ROUTES_DIR = OUTPUT_DIR / "routes"
MAPS_DIR = OUTPUT_DIR / "maps"
CHARTS_DIR = OUTPUT_DIR / "charts"

# --- Canonical data artifacts ----------------------------------------------
WAFFLE_PARQUET = DATA_DIR / "waffle_houses.parquet"
MATRIX_NPY = DATA_DIR / "distance_matrix.npy"
MATRIX_PARTIAL = DATA_DIR / "distance_matrix.partial.npy"  # resume checkpoint
HURDAT2_CSV = DATA_DIR / "hurdat2.csv"
OUTLIER_JSON = DATA_DIR / "outlier.json"

# --- Routing engine for the distance matrix (Task 2) ------------------------
# We route on a *filtered* OSM network (high-level roads only: motorway->tertiary;
# see RUNBOOK). That shrinks the US graph ~11GB -> ~550MB, so OSRM fits in RAM
# AND we sidestep the Valhalla `latest` tile-builder crash. Waffle Houses snap to
# the nearest major-road node (a small, accepted approximation).
# Port 5001, not 5000: macOS ControlCenter/AirPlay Receiver occupies 5000.
ROUTING_ENGINE = os.environ.get("ROUTING_ENGINE", "osrm")
OSRM_URL = os.environ.get("OSRM_URL", "http://localhost:5001")
VALHALLA_URL = os.environ.get("VALHALLA_URL", "http://localhost:8002")
LKH_BIN = os.environ.get("LKH_BIN", str(REPO_ROOT / "LKH-3.0.13" / "LKH"))

# --- Overture Maps -----------------------------------------------------------
# Update to the most recent Overture release before running Task 1.
# Check https://overturemaps.org for the current release date.
OVERTURE_RELEASE = os.environ.get("OVERTURE_RELEASE", "2026-05-20.0")
OVERTURE_PLACES_PATH = (
    f"s3://overturemaps-us-west-2/release/{OVERTURE_RELEASE}"
    "/theme=places/type=place/*"
)

# --- Continental US bounding box (lon/lat, EPSG:4326) ----------------------
# Excludes Alaska, Hawaii, and international outliers.
CONUS_BBOX_WKT = "POLYGON((-125 24, -66 24, -66 50, -125 50, -125 24))"

# --- Modeling constants -----------------------------------------------------
HIGHWAY_SPEED_MPH = 60.0          # distance -> time conversion
MAX_DRIVE_HOURS = 16.0            # before a mandatory rest
REST_HOURS = 8.0                  # overnight rest duration
EATING_MINUTES_PER_STOP = 30.0    # service time at every Waffle House
WAFFLE_CALORIES_PER_STOP = 410    # one waffle, per the video premise

# Hurricane closure model (Task 6)
HURRICANE_NAME = "HELENE"
HURRICANE_YEAR = 2024
CLOSURE_THRESHOLD_MPH = 75
CLOSURE_RADIUS_KM = 80
HURDAT2_URL = (
    "https://www.nhc.noaa.gov/data/hurdat/hurdat2-1851-2024-040425.txt"
)


def ensure_dirs() -> None:
    """Create all output directories if they do not exist."""
    for d in (DATA_DIR, OUTPUT_DIR, ROUTES_DIR, MAPS_DIR, CHARTS_DIR):
        d.mkdir(parents=True, exist_ok=True)
