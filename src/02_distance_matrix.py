"""Task 2 — Build the N x N road-distance matrix.

Calls a local routing engine in blocks and assembles a float32 matrix of road
distances in METERS. Two engines are supported (``config.ROUTING_ENGINE``):

  * ``valhalla`` (default) — POSTs to ``/sources_to_targets``. Tile-based and
    low-memory, so the full-US graph fits on an 18 GB machine where OSRM cannot.
  * ``osrm`` — GETs ``/table`` (needs >20 GB RAM to hold the full-US graph).

Restartable: progress is checkpointed to ``distance_matrix.partial.npy`` plus a
``.done`` block index, so a crashed run resumes. Failed blocks retry with
exponential backoff.

REQUIRES the chosen engine's server to be running (see RUNBOOK.md). Verify:
  Valhalla: curl "http://localhost:8002/status"
  OSRM:     curl "http://localhost:5000/route/v1/driving/-84.39,33.75;-84.45,33.78"

Output: data/distance_matrix.npy  (float32, shape N x N, meters)
Validation: zero diagonal; mean asymmetry <= 5%.

Usage:
    python src/02_distance_matrix.py [--force] [--batch-size N]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
import common

# Valhalla matrix calls are heavier per pair than OSRM's table, so default to a
# smaller block. Override with --batch-size.
DEFAULT_BATCH = {"valhalla": 80, "osrm": 100}
MAX_RETRIES = 6
KM_TO_M = 1000.0
DONE_INDEX = config.MATRIX_PARTIAL.with_suffix(".done.json")


def _osrm_table(sources, destinations):
    """sources x destinations meters via OSRM /table. None -> nan."""
    import numpy as np
    import requests

    src_coords = ";".join(f"{lon},{lat}" for lon, lat in sources)
    dst_coords = ";".join(f"{lon},{lat}" for lon, lat in destinations)
    coords = src_coords + ";" + dst_coords
    src_idx = ";".join(str(i) for i in range(len(sources)))
    dst_idx = ";".join(str(i + len(sources)) for i in range(len(destinations)))
    url = (
        f"{config.OSRM_URL}/table/v1/driving/{coords}"
        f"?sources={src_idx}&destinations={dst_idx}&annotations=distance"
    )
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    data = r.json()
    if data.get("code") != "Ok":
        raise RuntimeError(f"OSRM code={data.get('code')}")
    return np.array(data["distances"], dtype=np.float32)


def _valhalla_table(sources, destinations):
    """sources x destinations meters via Valhalla /sources_to_targets.

    Valhalla returns distance in the requested units (km) and null for
    unreachable pairs; we convert to meters and leave unreachable as nan.
    """
    import numpy as np
    import requests

    payload = {
        "sources": [{"lat": lat, "lon": lon} for lon, lat in sources],
        "targets": [{"lat": lat, "lon": lon} for lon, lat in destinations],
        "costing": "auto",
        "units": "kilometers",
    }
    r = requests.post(f"{config.VALHALLA_URL}/sources_to_targets",
                      json=payload, timeout=300)
    r.raise_for_status()
    rows = r.json()["sources_to_targets"]
    out = np.full((len(sources), len(destinations)), np.nan, dtype=np.float32)
    for i, row in enumerate(rows):
        for cell in row:
            d = cell.get("distance")
            if d is not None:
                out[i, cell["to_index"]] = d * KM_TO_M
    return out


def get_table_distances(sources, destinations, logger):
    """Return a sources x destinations matrix of road distances in meters.

    Dispatches to the configured engine. sources/destinations are (lon, lat)
    lists. Retries with exponential backoff (a local engine can choke on load).
    """
    impl = _valhalla_table if config.ROUTING_ENGINE == "valhalla" else _osrm_table
    for attempt in range(MAX_RETRIES):
        try:
            return impl(sources, destinations)
        except Exception as e:  # noqa: BLE001
            wait = 2 ** attempt
            logger.warning("%s call failed (attempt %d/%d): %s -> retry in %ds",
                           config.ROUTING_ENGINE, attempt + 1, MAX_RETRIES, e, wait)
            time.sleep(wait)
    raise RuntimeError(
        f"{config.ROUTING_ENGINE} table call failed after {MAX_RETRIES} attempts")


def _load_checkpoint(n, logger):
    import numpy as np

    if config.MATRIX_PARTIAL.exists() and DONE_INDEX.exists():
        matrix = np.load(config.MATRIX_PARTIAL)
        done = set(tuple(b) for b in json.loads(DONE_INDEX.read_text()))
        if matrix.shape == (n, n):
            logger.info("Resuming from checkpoint: %d blocks already done.",
                        len(done))
            return matrix, done
        logger.warning("Checkpoint shape mismatch; starting fresh.")
    return np.zeros((n, n), dtype=np.float32), set()


def _save_checkpoint(matrix, done):
    import numpy as np

    np.save(config.MATRIX_PARTIAL, matrix)
    DONE_INDEX.write_text(json.dumps(sorted(done)))


def main() -> None:
    import numpy as np

    parser = common.make_arg_parser(__doc__ or "Build distance matrix")
    parser.add_argument("--batch-size", type=int, default=None,
                        help="Block size; defaults per engine (valhalla=80, osrm=100).")
    args = parser.parse_args()

    out = config.MATRIX_NPY
    log = common.setup_logging("02_distance_matrix", out)
    common.guard_output(out, args.force, log)
    config.ensure_dirs()

    engine = config.ROUTING_ENGINE
    engine_url = config.VALHALLA_URL if engine == "valhalla" else config.OSRM_URL
    df = common.load_waffle_houses()
    coords = list(zip(df["lon"].tolist(), df["lat"].tolist()))
    n = len(coords)
    bs = args.batch_size or DEFAULT_BATCH.get(engine, 80)
    log.info("Building %d x %d matrix in %d-row blocks via %s (%s)",
             n, n, bs, engine, engine_url)

    matrix, done = _load_checkpoint(n, log)

    blocks = [(i, j) for i in range(0, n, bs) for j in range(0, n, bs)]
    t0 = time.time()
    for k, (i, j) in enumerate(blocks):
        if (i, j) in done:
            continue
        srcs = coords[i:i + bs]
        dsts = coords[j:j + bs]
        block = get_table_distances(srcs, dsts, log)
        matrix[i:i + len(srcs), j:j + len(dsts)] = block
        done.add((i, j))

        if k % 10 == 0 or k == len(blocks) - 1:
            _save_checkpoint(matrix, done)
            elapsed = time.time() - t0
            log.info("block %d/%d (%.1f%%) elapsed %.0fs",
                     k + 1, len(blocks), 100 * (k + 1) / len(blocks), elapsed)

    # Replace unreachable (nan) with a large but finite sentinel; warn if any.
    n_nan = int(np.isnan(matrix).sum())
    if n_nan:
        log.warning("%d unreachable pairs (nan) -> set to 0 on diagonal / max "
                    "off-diagonal", n_nan)
        finite_max = np.nanmax(matrix)
        matrix = np.where(np.isnan(matrix), finite_max, matrix).astype(np.float32)

    np.fill_diagonal(matrix, 0.0)

    # --- Validation -------------------------------------------------------- #
    diag_ok = float(np.abs(np.diag(matrix)).max()) == 0.0
    with np.errstate(divide="ignore", invalid="ignore"):
        denom = (matrix + matrix.T) / 2.0
        asym = np.abs(matrix - matrix.T) / np.where(denom == 0, 1, denom)
    mean_asym = float(np.nanmean(asym))
    log.info("Validation: zero diagonal=%s, mean asymmetry=%.3f%%",
             diag_ok, 100 * mean_asym)
    if not diag_ok or mean_asym > 0.05:
        log.error("VALIDATION FAILED (diagonal/symmetry). Not writing final output.")
        sys.exit(1)

    np.save(out, matrix)
    log.info("Wrote %s shape=%s dtype=%s", out, matrix.shape, matrix.dtype)
    # Clean up checkpoints on success.
    for p in (config.MATRIX_PARTIAL, DONE_INDEX):
        if p.exists():
            p.unlink()


if __name__ == "__main__":
    main()
