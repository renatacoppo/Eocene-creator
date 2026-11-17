#!/usr/bin/env python3
"""Compare two output trees of the Eocene workflow, file by file.

Usage::

    python scripts/compare_outputs.py BASELINE NEW

Rules (see AGENTS.md, "Scientific integrity"):

- both trees must hold the same relative file list (``IGNORED_FILES`` are skipped);
- NetCDF (``.nc``): same variable names and order, dimension names, order and sizes, dtypes,
  values equal within ``RTOL`` (NaN equal to NaN), global and variable attributes equal except
  ``IGNORED_ATTRS``. Files are read with ``decode_cf=False``, so raw on-disk values and
  ``_FillValue``/``scale_factor`` attributes are compared too;
- GRIB (detected by the ``GRIB`` magic bytes): ``grib_compare`` from ecCodes, which checks values,
  all keys and the message order. No keys are ignored: outputs keep the dates of the input files;
- any other file: byte comparison.

Prints one line per file and a final summary; exits with 0 when no differences are found, 1 otherwise.
"""

import argparse
import filecmp
import logging
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import xarray as xr

logger = logging.getLogger("compare_outputs")

# Bookkeeping files of a run, not outputs
IGNORED_FILES = frozenset({"BASELINE.txt", "provenance.yml"})

# NetCDF attributes that change at every run (history and dates)
IGNORED_ATTRS = frozenset(
    {
        "history",
        "history_of_appended_files",
        "date",
        "creation_date",
        "date_created",
        "date_modified",
        "date_issued",
        "date_metadata_modified",
    }
)

# Relative tolerance for NetCDF values
RTOL = 1e-6


def list_files(root: Path) -> set[str]:
    """Return the relative paths of all files under ``root``, without ``IGNORED_FILES``."""
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name not in IGNORED_FILES
    }


def is_grib(path: Path) -> bool:
    """Return True if the file starts with the GRIB magic bytes."""
    with open(path, "rb") as f:
        return f.read(4) == b"GRIB"


def attrs_equal(a: object, b: object) -> bool:
    """Compare two attribute values, which may be strings, numbers or arrays."""
    if isinstance(a, str) or isinstance(b, str):
        return a == b
    a, b = np.asarray(a), np.asarray(b)
    if a.shape != b.shape or a.dtype != b.dtype:
        return False
    return bool(np.array_equal(a, b, equal_nan=a.dtype.kind in "fc"))


def compare_attrs(attrs_a: dict, attrs_b: dict, where: str) -> list[str]:
    """Return the attribute differences, ignoring ``IGNORED_ATTRS``. The order of attributes is compared too."""
    keys_a = [k for k in attrs_a if k not in IGNORED_ATTRS]
    keys_b = [k for k in attrs_b if k not in IGNORED_ATTRS]
    if keys_a != keys_b:
        return [f"{where} attribute names differ: {keys_a} vs {keys_b}"]
    return [f"{where} attribute '{k}' differs" for k in keys_a if not attrs_equal(attrs_a[k], attrs_b[k])]


def compare_values(a: np.ndarray, b: np.ndarray) -> bool:
    """Return True if two arrays are equal, within ``RTOL`` for numbers and NaN equal to NaN."""
    if a.dtype.kind in "iufc":
        try:
            np.testing.assert_allclose(a, b, rtol=RTOL, equal_nan=True)
        except AssertionError:
            return False
        return True
    return bool(np.array_equal(a, b))


def compare_netcdf(base: Path, new: Path) -> list[str]:
    """Return the differences between two NetCDF files (empty list if equal)."""
    with xr.open_dataset(base, decode_cf=False) as ds_a, xr.open_dataset(new, decode_cf=False) as ds_b:
        if dict(ds_a.sizes) != dict(ds_b.sizes) or list(ds_a.dims) != list(ds_b.dims):
            return [f"dimensions differ: {dict(ds_a.sizes)} vs {dict(ds_b.sizes)}"]
        if list(ds_a.variables) != list(ds_b.variables):
            return [f"variables differ: {list(ds_a.variables)} vs {list(ds_b.variables)}"]
        diffs = compare_attrs(ds_a.attrs, ds_b.attrs, "global")
        for name in ds_a.variables:
            var_a, var_b = ds_a[name], ds_b[name]
            if var_a.dims != var_b.dims:
                diffs.append(f"'{name}' dimensions differ: {var_a.dims} vs {var_b.dims}")
                continue
            if var_a.dtype != var_b.dtype:
                diffs.append(f"'{name}' dtype differs: {var_a.dtype} vs {var_b.dtype}")
                continue
            if not compare_values(var_a.values, var_b.values):
                diffs.append(f"'{name}' values differ beyond rtol={RTOL}")
            diffs += compare_attrs(var_a.attrs, var_b.attrs, f"'{name}'")
        return diffs


def compare_grib(base: Path, new: Path) -> list[str]:
    """Return the differences reported by ``grib_compare`` (values, keys, message order)."""
    result = subprocess.run(["grib_compare", str(base), str(new)], capture_output=True, text=True)
    if result.returncode == 0:
        return []
    # grib_compare prints a "-- GRIB #n --" header, then one line per differing key
    lines = [line.strip() for line in (result.stdout + result.stderr).splitlines() if line.strip()]
    header = next((line for line in lines if line.startswith("--")), "")
    detail = next((line for line in lines if not line.startswith("--")), f"exit code {result.returncode}")
    return [f"grib_compare: {header.split(' shortName')[0].strip('- ')} {detail}".strip()]


def compare_file(base: Path, new: Path) -> list[str]:
    """Compare one file with the method matching its type; return the differences."""
    if base.suffix == ".nc":
        return compare_netcdf(base, new)
    if is_grib(base):
        if not is_grib(new):
            return ["baseline is GRIB, new file is not"]
        return compare_grib(base, new)
    return [] if filecmp.cmp(base, new, shallow=False) else ["bytes differ"]


def compare_trees(baseline: Path, new: Path) -> int:
    """Compare two output trees, log one line per file and return the number of differing files."""
    files_a, files_b = list_files(baseline), list_files(new)
    n_diff = 0
    for rel in sorted(files_a | files_b):
        if rel not in files_b:
            diffs = ["missing in NEW"]
        elif rel not in files_a:
            diffs = ["extra in NEW (not in BASELINE)"]
        else:
            try:
                diffs = compare_file(baseline / rel, new / rel)
            except (OSError, ValueError) as err:
                diffs = [f"cannot be read: {err}"]
        if diffs:
            n_diff += 1
            logger.info("%s: %s", rel, "; ".join(diffs))
        else:
            logger.info("%s: identical", rel)
    logger.info("all files compared, %d differences", n_diff)
    return n_diff


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare two output trees of the Eocene workflow, file by file.")
    parser.add_argument("baseline", type=Path, help="reference tree, e.g. BASELINE/eocene")
    parser.add_argument("new", type=Path, help="tree to check, e.g. OUTPUT/eocene")
    parser.add_argument("-l", "--loglevel", default="INFO", help="logging level (default: INFO)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=args.loglevel.upper(), format="%(message)s")

    for root in (args.baseline, args.new):
        if not root.is_dir():
            parser.error(f"not a directory: {root}")
    if shutil.which("grib_compare") is None and any(is_grib(args.baseline / rel) for rel in list_files(args.baseline)):
        parser.error("GRIB files found but grib_compare (ecCodes) is not on PATH")

    return 1 if compare_trees(args.baseline, args.new) else 0


if __name__ == "__main__":
    sys.exit(main())
