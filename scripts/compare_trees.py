#!/usr/bin/env python3
"""Compare two EC-Earth input trees and write a Markdown report.

Unlike ``compare_outputs.py`` (a strict pass/fail check against the frozen baseline), this script
describes *how much* two trees differ, to judge trees made by different tools or EC-Earth versions
(e.g. ECE4-DATA-4.1.11-eocene against a tree built by hand from ECE4-DATA v9).

Usage::

    python scripts/compare_trees.py TREE_A TREE_B -o report.md \\
        [--labels new old] [--include 'nemo/*'] [--exclude 'initial_state/*'] \\
        [--rename nemo/initial/deepmip-L31_cold-30.nc=nemo/initial/woa13-levitus-L31_deepmip-30.nc]

The report lists the files only in A, only in B, and for files in both:

- identical bytes (or the same file through a link);
- NetCDF: dimensions, variables only in one file, dtype changes, and for each variable that differs
  the number of differing points, the largest absolute and relative difference and where it is;
  global and variable attributes that differ (``history`` and dates ignored);
- ``domain_cfg.nc`` (NEMO domain): land-sea mask and ``bottom_level`` statistics, the vertical grid
  (``e3t_1d``, ``e3w_1d``) and the cells that change from ocean to land or back;
- GRIB: ``grib_compare -f`` (all messages), summarised by key;
- text: number of differing lines and the first lines of a unified diff.

Links are followed; directories that cannot be read are reported and skipped.
"""

import argparse
import difflib
import filecmp
import fnmatch
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import netCDF4
import numpy as np

logger = logging.getLogger("compare_trees")

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

# Variables larger than this many elements are compared slice by slice along their first dimension
CHUNK_ELEMENTS = 50_000_000

# Lines of a text diff and of grib_compare output kept in the report
MAX_DETAIL_LINES = 15


def list_files(root: Path, include: list[str], exclude: list[str]) -> tuple[dict[str, Path], list[str]]:
    """Return {relative path: path} of the files under ``root`` (links followed) and the unreadable dirs."""
    files, unreadable = {}, []
    for dirpath, dirnames, filenames in os.walk(
        root, followlinks=True, onerror=lambda e: unreadable.append(e.filename)
    ):
        dirnames.sort()
        for name in filenames:
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            if include and not any(fnmatch.fnmatch(rel, p) for p in include):
                continue
            if any(fnmatch.fnmatch(rel, p) for p in exclude):
                continue
            files[rel] = path
    return files, sorted(str(Path(u).relative_to(root)) for u in unreadable)


def file_kind(path: Path) -> str:
    """Return 'netcdf', 'grib', 'text' or 'binary' from the first bytes of the file."""
    with open(path, "rb") as f:
        head = f.read(4096)
    if head[:3] == b"CDF" or head[:4] == b"\x89HDF":
        return "netcdf"
    if head[:4] == b"GRIB":
        return "grib"
    try:
        head.decode("utf-8")
    except UnicodeDecodeError:
        return "binary"
    return "text"


# ----------------------------------------------------------------------------------------- NetCDF


def attrs_equal(a: object, b: object) -> bool:
    """Compare two attribute values, which may be strings, numbers or arrays."""
    if isinstance(a, str) or isinstance(b, str):
        return a == b
    a, b = np.asarray(a), np.asarray(b)
    return a.shape == b.shape and bool(np.array_equal(a, b, equal_nan=a.dtype.kind in "fc"))


def compare_attrs(obj_a, obj_b, where: str) -> list[str]:
    """Return the attribute differences between two netCDF4 objects, ignoring ``IGNORED_ATTRS``."""
    attrs_a = {k: obj_a.getncattr(k) for k in obj_a.ncattrs() if k not in IGNORED_ATTRS}
    attrs_b = {k: obj_b.getncattr(k) for k in obj_b.ncattrs() if k not in IGNORED_ATTRS}
    diffs = []
    if only := sorted(set(attrs_a) - set(attrs_b)):
        diffs.append(f"{where} attributes only in A: {only}")
    if only := sorted(set(attrs_b) - set(attrs_a)):
        diffs.append(f"{where} attributes only in B: {only}")
    for key in attrs_a.keys() & attrs_b.keys():
        if not attrs_equal(attrs_a[key], attrs_b[key]):
            diffs.append(f"{where} attribute '{key}': {short(attrs_a[key])} vs {short(attrs_b[key])}")
    return diffs


def short(value: object, width: int = 60) -> str:
    """Return a one-line representation of ``value``, cut to ``width`` characters."""
    text = repr(value).replace("\n", " ")
    return text if len(text) <= width else text[: width - 3] + "..."


def read_raw(var: netCDF4.Variable, index=slice(None)) -> np.ndarray:
    """Read raw values (no scaling, no masking) of ``var``; missing values become NaN for floats."""
    var.set_auto_maskandscale(False)
    data = np.asarray(var[index])
    return data


def variable_stats(var_a: netCDF4.Variable, var_b: netCDF4.Variable, rtol: float, atol: float) -> str | None:
    """Return a description of the value differences of two variables of the same shape, or None if equal."""
    numeric = var_a.dtype.kind in "iufb" and var_b.dtype.kind in "iufb"
    shape = var_a.shape
    if not numeric:
        equal = np.array_equal(read_raw(var_a), read_raw(var_b))
        return None if equal else "values differ (non numeric)"

    n_diff, n_nan_mismatch = 0, 0
    max_abs, where_abs, max_rel = 0.0, None, 0.0
    first_a = first_b = None
    steps = range(shape[0]) if shape and var_a.size > CHUNK_ELEMENTS else [None]
    for step in steps:
        index = slice(None) if step is None else step
        a = read_raw(var_a, index).astype(np.float64)
        b = read_raw(var_b, index).astype(np.float64)
        nan_a, nan_b = np.isnan(a), np.isnan(b)
        n_nan_mismatch += int(np.count_nonzero(nan_a != nan_b))
        both = ~(nan_a | nan_b)
        diff = np.zeros_like(a)
        diff[both] = np.abs(a[both] - b[both])
        bad = both & (diff > atol + rtol * np.abs(a))
        count = int(np.count_nonzero(bad))
        if count:
            n_diff += count
            flat = int(np.argmax(np.where(bad, diff, -1.0)))
            if diff.flat[flat] > max_abs:
                max_abs = float(diff.flat[flat])
                local = np.unravel_index(flat, a.shape) if a.ndim else ()
                where_abs = ((step,) if step is not None else ()) + tuple(int(i) for i in local)
                first_a, first_b = a.flat[flat], b.flat[flat]
            denom = np.abs(a[bad])
            with np.errstate(divide="ignore", invalid="ignore"):
                rel = np.where(denom > 0, diff[bad] / denom, np.inf)
            max_rel = max(max_rel, float(np.max(rel)))
    if not n_diff and not n_nan_mismatch:
        return None
    size = int(np.prod(shape)) if shape else 1
    parts = [f"{n_diff}/{size} points differ ({100 * n_diff / size:.3g}%)"]
    if n_diff:
        dims = dict(zip(var_a.dimensions, where_abs, strict=False)) if where_abs is not None else {}
        parts.append(f"max |A-B| = {max_abs:.6g} at {dims} (A={first_a:.6g}, B={first_b:.6g}), max rel = {max_rel:.3g}")
    if n_nan_mismatch:
        parts.append(f"{n_nan_mismatch} points NaN in only one file")
    return "; ".join(parts)


def compare_netcdf(path_a: Path, path_b: Path, rtol: float, atol: float) -> list[str]:
    """Return the differences between two NetCDF files (empty list if equal)."""
    diffs = []
    with netCDF4.Dataset(path_a) as ds_a, netCDF4.Dataset(path_b) as ds_b:
        dims_a = {k: len(v) for k, v in ds_a.dimensions.items()}
        dims_b = {k: len(v) for k, v in ds_b.dimensions.items()}
        if dims_a != dims_b:
            diffs.append(f"dimensions: {dims_a} vs {dims_b}")
        vars_a, vars_b = list(ds_a.variables), list(ds_b.variables)
        if only := [v for v in vars_a if v not in vars_b]:
            diffs.append(f"variables only in A: {only}")
        if only := [v for v in vars_b if v not in vars_a]:
            diffs.append(f"variables only in B: {only}")
        common = [v for v in vars_a if v in vars_b]
        if common != [v for v in vars_b if v in vars_a]:
            diffs.append("common variables are in a different order")
        if ds_a.data_model != ds_b.data_model:
            diffs.append(f"format: {ds_a.data_model} vs {ds_b.data_model}")
        diffs += compare_attrs(ds_a, ds_b, "global")
        for name in common:
            var_a, var_b = ds_a[name], ds_b[name]
            if var_a.dimensions != var_b.dimensions or var_a.shape != var_b.shape:
                diffs.append(
                    f"'{name}' shape: {dict(zip(var_a.dimensions, var_a.shape, strict=True))} vs "
                    f"{dict(zip(var_b.dimensions, var_b.shape, strict=True))}"
                )
                continue
            if var_a.dtype != var_b.dtype:
                diffs.append(f"'{name}' dtype: {var_a.dtype} vs {var_b.dtype}")
            if stats := variable_stats(var_a, var_b, rtol, atol):
                diffs.append(f"'{name}': {stats}")
            diffs += compare_attrs(var_a, var_b, f"'{name}'")
    return collapse_attribute_diffs(diffs)


def collapse_attribute_diffs(diffs: list[str], limit: int = 3) -> list[str]:
    """Merge attribute differences that repeat for more than ``limit`` variables into one line."""
    by_message: dict[str, list[str]] = {}
    for diff in diffs:
        if match := re.match(r"'([^']+)' (attribute.*)", diff):
            by_message.setdefault(match.group(2), []).append(match.group(1))
    out = []
    for diff in diffs:
        match = re.match(r"'([^']+)' (attribute.*)", diff)
        if not match or len(by_message[match.group(2)]) <= limit:
            out.append(diff)
        elif match.group(1) == by_message[match.group(2)][0]:
            names = by_message[match.group(2)]
            out.append(f"{len(names)} variables, {match.group(2)}: {names}")
    return out


def nemo_domain_summary(path_a: Path, path_b: Path) -> list[str]:
    """Return a NEMO-specific comparison of two ``domain_cfg.nc`` files: mask, levels, vertical grid."""
    lines = []
    with netCDF4.Dataset(path_a) as ds_a, netCDF4.Dataset(path_b) as ds_b:
        for name in ("e3t_1d", "e3w_1d", "nav_lev"):
            if name in ds_a.variables and name in ds_b.variables:
                a, b = np.squeeze(ds_a[name][:]), np.squeeze(ds_b[name][:])
                if a.shape != b.shape:
                    lines.append(f"vertical grid `{name}`: {a.size} vs {b.size} levels")
                else:
                    lines.append(f"vertical grid `{name}`: {a.size} levels, max |A-B| = {np.max(np.abs(a - b)):.3g} m")
        if "bottom_level" not in ds_a.variables or "bottom_level" not in ds_b.variables:
            return lines + ["no `bottom_level` in one of the files"]
        bl_a, bl_b = np.squeeze(ds_a["bottom_level"][:]), np.squeeze(ds_b["bottom_level"][:])
        if bl_a.shape != bl_b.shape:
            return lines + [f"`bottom_level` shape {bl_a.shape} vs {bl_b.shape}"]
        ocean_a, ocean_b = bl_a > 0, bl_b > 0
        lines.append(f"ocean columns: A {int(ocean_a.sum())}, B {int(ocean_b.sum())} (of {bl_a.size})")
        to_land = np.argwhere(ocean_a & ~ocean_b)
        to_ocean = np.argwhere(~ocean_a & ocean_b)
        lines.append(f"ocean in A, land in B: {len(to_land)} cells{cell_list(to_land, ds_a)}")
        lines.append(f"land in A, ocean in B: {len(to_ocean)} cells{cell_list(to_ocean, ds_a)}")
        both = ocean_a & ocean_b
        dl = (bl_b.astype(int) - bl_a.astype(int))[both]
        dl = dl[dl != 0]
        lines.append(
            f"ocean in both, different `bottom_level`: {dl.size} cells"
            + (f" (B-A from {dl.min()} to {dl.max()} levels)" if dl.size else "")
        )
        if "top_level" in ds_a.variables and "top_level" in ds_b.variables:
            tl_a, tl_b = np.squeeze(ds_a["top_level"][:]), np.squeeze(ds_b["top_level"][:])
            lines.append(f"different `top_level`: {int(np.count_nonzero(tl_a != tl_b))} cells")
        for name in ("bathy_metry", "bathy_meter"):
            if name in ds_a.variables and name in ds_b.variables:
                d = np.abs(np.squeeze(ds_a[name][:]) - np.squeeze(ds_b[name][:]))[both]
                lines.append(
                    f"`{name}` over common ocean: {int(np.count_nonzero(d > 1e-3))} cells differ by > 1 mm, "
                    f"max {float(d.max()) if d.size else 0:.4g} m"
                )
    return lines


def cell_list(cells: np.ndarray, ds: netCDF4.Dataset, limit: int = 10) -> str:
    """Return ' at (j, i, lat, lon), ...' for the first ``limit`` cells, or '' if none."""
    if not len(cells):
        return ""
    lat = np.squeeze(ds["nav_lat"][:]) if "nav_lat" in ds.variables else None
    lon = np.squeeze(ds["nav_lon"][:]) if "nav_lon" in ds.variables else None
    items = []
    for j, i in cells[:limit]:
        pos = f"j={j} i={i}"
        if lat is not None and lon is not None:
            pos += f" ({lat[j, i]:.1f}N {lon[j, i]:.1f}E)"
        items.append(pos)
    more = f", ... (+{len(cells) - limit})" if len(cells) > limit else ""
    return ": " + ", ".join(items) + more


# ------------------------------------------------------------------------------------ GRIB, text


def compare_grib(path_a: Path, path_b: Path) -> list[str]:
    """Return a summary of ``grib_compare -f`` (all messages, values and keys)."""
    counts = [
        subprocess.run(["grib_count", str(p)], capture_output=True, text=True).stdout.strip() for p in (path_a, path_b)
    ]
    result = subprocess.run(["grib_compare", "-f", str(path_a), str(path_b)], capture_output=True, text=True)
    if result.returncode == 0:
        return []
    lines = [line.strip() for line in (result.stdout + result.stderr).splitlines() if line.strip()]
    messages = [line for line in lines if line.startswith("-- GRIB #")]
    keys = Counter()
    for line in lines:
        if match := re.match(r"\w+ \[(\w+)\]", line):
            keys[match.group(1)] += 1
    diffs = [f"messages: {counts[0]} vs {counts[1]}; {len(messages)} messages differ"]
    if keys:
        diffs.append("differing keys (number of messages): " + ", ".join(f"{k} ({n})" for k, n in keys.most_common()))
    diffs += [f"`{line}`" for line in lines[:MAX_DETAIL_LINES]]
    return diffs


def compare_text(path_a: Path, path_b: Path) -> list[str]:
    """Return the number of lines only in A and only in B, and the start of a unified diff."""
    text_a = path_a.read_text(errors="replace").splitlines()
    text_b = path_b.read_text(errors="replace").splitlines()
    diff = list(difflib.unified_diff(text_a, text_b, "A", "B", lineterm="", n=0))
    removed = sum(1 for line in diff[2:] if line.startswith("-"))
    added = sum(1 for line in diff[2:] if line.startswith("+"))
    return [f"{removed} lines only in A, {added} lines only in B"] + [
        f"`{line}`" for line in diff[2 : 2 + MAX_DETAIL_LINES]
    ]


def compare_file(path_a: Path, path_b: Path, rtol: float, atol: float) -> tuple[str, list[str], list[str]]:
    """Return (status, differences, NEMO domain notes) for two files with the same relative path."""
    try:
        if path_a.resolve() == path_b.resolve():
            return "identical", [], []
        if path_a.stat().st_size == path_b.stat().st_size and filecmp.cmp(path_a, path_b, shallow=False):
            return "identical", [], []
        kind_a, kind_b = file_kind(path_a), file_kind(path_b)
        if kind_a != kind_b:
            return "differ", [f"file type: {kind_a} vs {kind_b}"], []
        if kind_a == "netcdf":
            diffs = compare_netcdf(path_a, path_b, rtol, atol)
            notes = nemo_domain_summary(path_a, path_b) if path_a.name.startswith("domain_cfg") else []
            # Bytes differ but nothing measurable does: only ignored attributes or the layout on disk
            return ("equivalent" if not diffs else "differ"), diffs, notes
        if kind_a == "grib":
            diffs = compare_grib(path_a, path_b)
            return ("equivalent" if not diffs else "differ"), diffs, []
        if kind_a == "text":
            return "differ", compare_text(path_a, path_b), []
        return "differ", ["binary content differs"], []
    except (OSError, RuntimeError, ValueError) as err:
        return "error", [f"cannot be compared: {err}"], []


# ----------------------------------------------------------------------------------------- report


def grouped(paths: list[str], depth: int = 3) -> list[str]:
    """Return Markdown lines that list ``paths`` grouped by their first ``depth`` directories."""
    groups: dict[str, list[str]] = {}
    for rel in paths:
        parts = rel.split("/")
        groups.setdefault("/".join(parts[:depth]) if len(parts) > depth else "/".join(parts[:-1]) or ".", []).append(
            rel
        )
    lines = []
    for group, items in sorted(groups.items()):
        if len(items) > 8:
            lines.append(f"- `{group}/` ({len(items)} files), e.g. `{items[0]}`")
        else:
            lines += [f"- `{item}`" for item in items]
    return lines


def write_report(args: argparse.Namespace, files_a, files_b, unreadable, pairs, results, elapsed: float) -> str:
    """Return the Markdown report."""
    label_a, label_b = args.labels
    only_a = sorted(set(files_a) - {a for a, _ in pairs})
    only_b = sorted(set(files_b) - {b for _, b in pairs})
    status = Counter(r[0] for r in results.values())
    out = [
        f"# Tree comparison: {label_a} vs {label_b}",
        "",
        f"- **A** ({label_a}): `{args.tree_a}`",
        f"- **B** ({label_b}): `{args.tree_b}`",
        f"- filters: include {args.include or 'all'}, exclude {args.exclude or 'none'}; "
        f"renames {args.rename or 'none'}",
        f"- NetCDF tolerance: rtol={args.rtol}, atol={args.atol}; `history` and date attributes ignored",
        f"- run {time.strftime('%Y-%m-%d %H:%M')}, {elapsed:.0f} s",
        "",
        "## Summary",
        "",
        "| | files |",
        "|---|---|",
        f"| only in A ({label_a}) | {len(only_a)} |",
        f"| only in B ({label_b}) | {len(only_b)} |",
        f"| in both, identical bytes | {status['identical']} |",
        f"| in both, same content (bytes differ: ignored attributes, layout or encoding) | {status['equivalent']} |",
        f"| in both, **different** | {status['differ']} |",
        f"| in both, could not be compared | {status['error']} |",
        "",
    ]
    if unreadable:
        out += ["Directories that could not be read (skipped):", ""] + [f"- `{u}`" for u in unreadable] + [""]

    differ = [(pair, results[pair]) for pair in pairs if results[pair][0] in ("differ", "error")]
    domains = [(pair, results[pair]) for pair in pairs if results[pair][2]]
    if domains:
        out += ["## NEMO domains", ""]
        for (rel_a, rel_b), (state, _, notes) in domains:
            out += [f"### `{rel_a}`" + (f" vs `{rel_b}`" if rel_b != rel_a else ""), "", f"status: {state}", ""]
            out += [f"- {note}" for note in notes] + [""]
    out += ["## Files that differ", ""]
    if not differ:
        out += ["None.", ""]
    for (rel_a, rel_b), (state, diffs, _) in differ:
        out += [
            f"### `{rel_a}`" + (f" vs `{rel_b}`" if rel_b != rel_a else "") + (" (error)" if state == "error" else "")
        ]
        out += [""] + [f"- {d}" for d in diffs] + [""]
    equivalent = [rel_a for (rel_a, _), r in results.items() if r[0] == "equivalent"]
    if equivalent:
        out += ["## Same content, bytes differ", ""] + grouped(sorted(equivalent)) + [""]
    out += [f"## Only in A ({label_a})", ""] + (grouped(only_a) or ["None."]) + [""]
    out += [f"## Only in B ({label_b})", ""] + (grouped(only_b) or ["None."]) + [""]
    identical = sorted(rel_a for (rel_a, _), r in results.items() if r[0] == "identical")
    out += ["## Identical", ""] + (grouped(identical) or ["None."]) + [""]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare two EC-Earth input trees and write a Markdown report.")
    parser.add_argument("tree_a", type=Path, help="first tree (A)")
    parser.add_argument("tree_b", type=Path, help="second tree (B)")
    parser.add_argument("-o", "--output", type=Path, required=True, help="Markdown report to write")
    parser.add_argument(
        "--labels",
        nargs=2,
        default=["A", "B"],
        metavar=("LABEL_A", "LABEL_B"),
        help="short names of the two trees in the report",
    )
    parser.add_argument(
        "--include",
        action="append",
        default=[],
        metavar="GLOB",
        help="compare only relative paths matching GLOB (repeatable)",
    )
    parser.add_argument(
        "--exclude", action="append", default=[], metavar="GLOB", help="skip relative paths matching GLOB (repeatable)"
    )
    parser.add_argument(
        "--rename",
        action="append",
        default=[],
        metavar="PATH_A=PATH_B",
        help="pair a file of A with a file of B under another name (repeatable)",
    )
    parser.add_argument("--rtol", type=float, default=1e-6, help="relative tolerance for NetCDF values")
    parser.add_argument("--atol", type=float, default=0.0, help="absolute tolerance for NetCDF values")
    parser.add_argument("-l", "--loglevel", default="INFO", help="logging level (default: INFO)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=args.loglevel.upper(), format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    for root in (args.tree_a, args.tree_b):
        if not root.is_dir():
            parser.error(f"not a directory: {root}")
    if shutil.which("grib_compare") is None:
        parser.error("grib_compare (ecCodes) is not on PATH")

    start = time.time()
    files_a, unread_a = list_files(args.tree_a, args.include, args.exclude)
    files_b, unread_b = list_files(args.tree_b, args.include, args.exclude)
    unreadable = [f"A: {u}" for u in unread_a] + [f"B: {u}" for u in unread_b]
    renames = dict(item.split("=", 1) for item in args.rename)
    pairs = [(rel, renames.get(rel, rel)) for rel in sorted(files_a) if renames.get(rel, rel) in files_b]
    logger.info("A: %d files, B: %d files, %d in both", len(files_a), len(files_b), len(pairs))

    results = {}
    for n, (rel_a, rel_b) in enumerate(pairs, 1):
        results[(rel_a, rel_b)] = compare_file(files_a[rel_a], files_b[rel_b], args.rtol, args.atol)
        logger.info("[%d/%d] %s: %s", n, len(pairs), rel_a, results[(rel_a, rel_b)][0])

    args.output.write_text(write_report(args, files_a, files_b, unreadable, pairs, results, time.time() - start))
    logger.info("report written to %s", args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
