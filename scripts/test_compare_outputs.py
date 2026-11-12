#!/usr/bin/env python3
"""Self-test of compare_outputs.py on tiny synthetic files.

Run with ``python scripts/test_compare_outputs.py`` (or ``pytest scripts/test_compare_outputs.py``).
The GRIB case is skipped when ``cdo`` or ``grib_compare`` is not on PATH.
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import xarray as xr

sys.path.insert(0, str(Path(__file__).parent))
import compare_outputs  # noqa: E402

HAS_GRIB_TOOLS = shutil.which("cdo") is not None and shutil.which("grib_compare") is not None


def make_dataset() -> xr.Dataset:
    """A tiny dataset with a float64 field, a NaN, a coordinate and attributes."""
    sst = np.arange(6, dtype="float64").reshape(2, 3) + 270.0
    sst[0, 0] = np.nan
    return xr.Dataset(
        {"sst": (("lat", "lon"), sst, {"units": "K", "long_name": "sea surface temperature"})},
        coords={"lat": ("lat", [-10.0, 10.0], {"units": "degrees_north"}), "lon": ("lon", [0.0, 120.0, 240.0])},
        attrs={"title": "synthetic", "history": "created by the self-test"},
    )


def make_tree(root: Path, ds: xr.Dataset | None = None, grib_value: float | None = None) -> Path:
    """Write a small output tree: one NetCDF file, one text file and optionally one GRIB file."""
    (root / "nemo").mkdir(parents=True)
    (ds if ds is not None else make_dataset()).to_netcdf(root / "nemo" / "field.nc")
    (root / "namelist.txt").write_text("&nam\n  x = 1\n/\n")
    (root / "BASELINE.txt").write_text(f"ignored {root.name}\n")
    if grib_value is not None:
        (root / "oifs").mkdir()
        subprocess.run(
            ["cdo", "-s", "-f", "grb", f"-const,{grib_value},r4x2", str(root / "oifs" / "ICMGGtest")], check=True
        )
    return root


def ndiff(base: Path, new: Path) -> int:
    return compare_outputs.compare_trees(base, new)


def test_identical(tmp_path: Path) -> None:
    base = make_tree(tmp_path / "base")
    assert ndiff(base, base) == 0
    assert ndiff(base, make_tree(tmp_path / "new")) == 0  # BASELINE.txt differs but is ignored


def test_value_beyond_tolerance(tmp_path: Path) -> None:
    ds = make_dataset()
    ds["sst"][1, 1] = ds["sst"][1, 1] * (1 + 1e-4)
    assert ndiff(make_tree(tmp_path / "base"), make_tree(tmp_path / "new", ds)) == 1


def test_value_within_tolerance(tmp_path: Path) -> None:
    ds = make_dataset()
    ds["sst"][1, 1] = ds["sst"][1, 1] * (1 + 1e-8)
    assert ndiff(make_tree(tmp_path / "base"), make_tree(tmp_path / "new", ds)) == 0


def test_history_ignored(tmp_path: Path) -> None:
    ds = make_dataset()
    ds.attrs["history"] = "a different history"
    ds["sst"].attrs["history"] = "variable history"
    assert ndiff(make_tree(tmp_path / "base"), make_tree(tmp_path / "new", ds)) == 0


def test_other_attribute(tmp_path: Path) -> None:
    ds = make_dataset()
    ds["sst"].attrs["units"] = "degC"
    assert ndiff(make_tree(tmp_path / "base"), make_tree(tmp_path / "new", ds)) == 1
    ds = make_dataset()
    ds.attrs["title"] = "changed"
    assert ndiff(make_tree(tmp_path / "base2"), make_tree(tmp_path / "new2", ds)) == 1


def test_dtype_and_variable_order(tmp_path: Path) -> None:
    ds = make_dataset()
    ds["sst"] = ds["sst"].astype("float32")
    assert ndiff(make_tree(tmp_path / "base"), make_tree(tmp_path / "new", ds)) == 1
    ds = make_dataset()
    ds["extra"] = ds["sst"] * 0
    assert ndiff(make_tree(tmp_path / "base2"), make_tree(tmp_path / "new2", ds)) == 1


def test_missing_extra_and_bytes(tmp_path: Path) -> None:
    base = make_tree(tmp_path / "base")
    new = make_tree(tmp_path / "new")
    (new / "nemo" / "field.nc").unlink()
    (new / "extra.txt").write_text("extra\n")
    (new / "namelist.txt").write_text("&nam\n  x = 2\n/\n")
    assert ndiff(base, new) == 3


def test_exit_code(tmp_path: Path) -> None:
    base = make_tree(tmp_path / "base")
    new = make_tree(tmp_path / "new")
    assert compare_outputs.main([str(base), str(new)]) == 0
    (new / "namelist.txt").write_text("changed\n")
    assert compare_outputs.main([str(base), str(new)]) == 1


def test_grib(tmp_path: Path) -> None:
    if not HAS_GRIB_TOOLS:
        print("SKIP test_grib: cdo or grib_compare not on PATH")
        return
    base = make_tree(tmp_path / "base", grib_value=1.0)
    assert ndiff(base, make_tree(tmp_path / "same", grib_value=1.0)) == 0
    assert ndiff(base, make_tree(tmp_path / "new", grib_value=2.0)) == 1


def main() -> int:
    import logging

    logging.basicConfig(level="INFO", format="  %(message)s")
    tests = [obj for name, obj in globals().items() if name.startswith("test_") and callable(obj)]
    failed = 0
    for test in tests:
        print(test.__name__)
        with tempfile.TemporaryDirectory() as tmp:
            try:
                test(Path(tmp))
            except AssertionError:
                failed += 1
                print(f"FAIL {test.__name__}")
    print(f"{len(tests) - failed}/{len(tests)} tests passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
