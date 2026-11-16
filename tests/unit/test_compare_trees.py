"""Self-test of scripts/compare_trees.py on tiny synthetic trees.

Run with ``pytest tests/unit/test_compare_trees.py``.
"""

import sys
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
import compare_trees  # noqa: E402

pytestmark = pytest.mark.unit


def make_domain(bottom_level: np.ndarray, e3t_1d: np.ndarray | None = None) -> xr.Dataset:
    """A tiny ``domain_cfg.nc``: bottom level, bathymetry, coordinates and the 1D vertical grid."""
    ny, nx = bottom_level.shape
    lat, lon = np.meshgrid(np.linspace(-10, 10, ny), np.linspace(0, 40, nx), indexing="ij")
    e3t = e3t_1d if e3t_1d is not None else np.array([10.0, 20.0, 30.0])
    return xr.Dataset(
        {
            "bottom_level": (("t", "y", "x"), bottom_level[None].astype("int32")),
            "top_level": (("t", "y", "x"), (bottom_level > 0)[None].astype("int32")),
            "bathy_metry": (("t", "y", "x"), (bottom_level * 10.0)[None]),
            "nav_lat": (("y", "x"), lat),
            "nav_lon": (("y", "x"), lon),
            "e3t_1d": (("t", "z"), e3t[None]),
        },
        attrs={"history": "made by the self-test"},
    )


def make_tree(root: Path, bottom_level: np.ndarray, namelist: str = "x = 1\n", extra: str | None = None) -> Path:
    """A small tree: a NEMO domain, a text file and optionally one more file."""
    (root / "nemo" / "domain").mkdir(parents=True)
    make_domain(bottom_level).to_netcdf(root / "nemo" / "domain" / "domain_cfg.nc")
    (root / "namelist").write_text(namelist)
    if extra:
        (root / extra).write_text("extra\n")
    return root


BOTTOM = np.array([[0, 1, 2], [3, 3, 0]])


def report(tmp_path: Path, a: Path, b: Path, *options: str) -> str:
    output = tmp_path / "report.md"
    assert compare_trees.main([str(a), str(b), "-o", str(output), "-l", "WARNING", *options]) == 0
    return output.read_text()


def test_identical_trees(tmp_path: Path) -> None:
    a = make_tree(tmp_path / "a", BOTTOM)
    text = report(tmp_path, a, a)
    assert "| in both, identical bytes | 2 |" in text
    assert "| in both, **different** | 0 |" in text


def test_files_only_in_one_tree(tmp_path: Path) -> None:
    a = make_tree(tmp_path / "a", BOTTOM, extra="only_a.txt")
    b = make_tree(tmp_path / "b", BOTTOM, extra="only_b.txt")
    text = report(tmp_path, a, b)
    assert "| only in A (A) | 1 |" in text and "| only in B (B) | 1 |" in text
    assert "- `only_a.txt`" in text.split("## Only in A")[1].split("## Only in B")[0]
    assert "- `only_b.txt`" in text.split("## Only in B")[1]


def test_domain_differences(tmp_path: Path) -> None:
    changed = BOTTOM.copy()
    changed[0, 1] = 0  # ocean -> land
    changed[1, 2] = 2  # land -> ocean
    changed[1, 0] = 1  # ocean in both, other bottom level
    a = make_tree(tmp_path / "a", BOTTOM)
    b = make_tree(tmp_path / "b", changed, namelist="x = 2\n")
    text = report(tmp_path, a, b, "--labels", "new", "old")
    assert "| in both, **different** | 2 |" in text
    assert "ocean columns: A 4, B 4 (of 6)" in text
    assert "ocean in A, land in B: 1 cells: j=0 i=1" in text
    assert "land in A, ocean in B: 1 cells: j=1 i=2" in text
    assert "ocean in both, different `bottom_level`: 1 cells (B-A from -2 to -2 levels)" in text
    assert "vertical grid `e3t_1d`: 3 levels, max |A-B| = 0 m" in text
    assert "'bottom_level': 3/6 points differ" in text
    assert "1 lines only in A, 1 lines only in B" in text  # namelist


def test_history_is_ignored(tmp_path: Path) -> None:
    a = make_tree(tmp_path / "a", BOTTOM)
    b = make_tree(tmp_path / "b", BOTTOM)
    ds = make_domain(BOTTOM)
    ds.attrs["history"] = "another history"
    ds.to_netcdf(b / "nemo" / "domain" / "domain_cfg.nc")
    text = report(tmp_path, a, b)
    assert "| in both, **different** | 0 |" in text


def test_rename_and_include(tmp_path: Path) -> None:
    a = make_tree(tmp_path / "a", BOTTOM)
    b = make_tree(tmp_path / "b", BOTTOM)
    (b / "nemo" / "domain" / "domain_cfg.nc").rename(b / "nemo" / "domain" / "domain_cfg.nc.orig")
    text = report(
        tmp_path, a, b, "--include", "nemo/*", "--rename", "nemo/domain/domain_cfg.nc=nemo/domain/domain_cfg.nc.orig"
    )
    assert "| only in A (A) | 0 |" in text and "| only in B (B) | 0 |" in text
    assert "| in both, identical bytes | 1 |" in text
    assert "namelist" not in text
