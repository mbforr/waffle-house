"""Shared utilities for every pipeline script.

Centralizes the cross-cutting conventions required by CLAUDE.md so they are not
re-implemented nine times:
  * log to stdout AND a sibling ``.log`` file
  * never overwrite an output without ``--force``
  * one place that knows the parquet schema and matrix dtype

Scripts are named ``NN_name.py`` (not importable as normal modules), so they add
the repo root to ``sys.path`` and ``import common`` / ``import config``. This
module does the same so it can be run from anywhere.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Make the repo root importable regardless of the cwd the script is run from.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import config  # noqa: E402


# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #
def setup_logging(script_name: str, output_path: Path) -> logging.Logger:
    """Return a logger that writes to stdout and to ``<output>.log``.

    The log file lives alongside the script's primary output, e.g.
    ``data/waffle_houses.parquet`` -> ``data/waffle_houses.parquet.log``.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    log_path = output_path.with_suffix(output_path.suffix + ".log")

    logger = logging.getLogger(script_name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()  # idempotent across re-runs in the same process
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)
    logger.addHandler(stream)

    file_handler = logging.FileHandler(log_path, mode="w")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    logger.info("Logging to %s", log_path)
    return logger


# --------------------------------------------------------------------------- #
# Argument parsing + output guarding
# --------------------------------------------------------------------------- #
def make_arg_parser(description: str) -> argparse.ArgumentParser:
    """Argparse parser preconfigured with the shared ``--force`` flag."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing output instead of refusing.",
    )
    return parser


def guard_output(path: Path, force: bool, logger: logging.Logger) -> None:
    """Exit cleanly (status 0) if ``path`` exists and ``--force`` was not given.

    Honors the CLAUDE.md rule: "never overwrites without a --force flag".
    """
    path = Path(path)
    if path.exists() and not force:
        logger.info(
            "%s already exists. Use --force to overwrite. Nothing to do.", path
        )
        sys.exit(0)


# --------------------------------------------------------------------------- #
# Typed loaders (single source of schema/dtype truth)
# --------------------------------------------------------------------------- #
WAFFLE_COLUMNS = ["id", "name", "lon", "lat", "address", "city", "state", "brand"]


def load_waffle_houses():
    """Load ``data/waffle_houses.parquet`` as a pandas DataFrame.

    Raises FileNotFoundError with a helpful message pointing at Task 1.
    """
    import pandas as pd

    if not config.WAFFLE_PARQUET.exists():
        raise FileNotFoundError(
            f"{config.WAFFLE_PARQUET} not found. Run src/01_pull_locations.py first."
        )
    df = pd.read_parquet(config.WAFFLE_PARQUET)
    # Stable ordering: the distance matrix rows/cols follow DataFrame index order.
    return df.reset_index(drop=True)


def load_matrix():
    """Load the OSRM road-distance matrix (meters, float32, N x N)."""
    import numpy as np

    if not config.MATRIX_NPY.exists():
        raise FileNotFoundError(
            f"{config.MATRIX_NPY} not found. Run src/02_distance_matrix.py "
            "(requires the local OSRM server) first."
        )
    return np.load(config.MATRIX_NPY)


def write_json(path: Path, obj: dict, logger: logging.Logger) -> None:
    """Write a metrics/result dict as pretty JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)
    logger.info("Wrote %s", path)
