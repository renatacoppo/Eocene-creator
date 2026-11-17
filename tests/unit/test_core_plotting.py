"""Unit tests of the shared plotting helpers (``ecefast.core.plotting``)."""

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from ecefast.core.plotting import (
    load_grib,
    plot_comparison,
    sample_nearest,
    save_figure,
    symmetric_limit,
)

pytestmark = pytest.mark.unit


def field(values: np.ndarray) -> xr.DataArray:
    """A 1 x ny x nx field on a regular lon/lat grid."""
    ny, nx = values.shape
    coords = {"time": [0], "lat": np.linspace(-80, 80, ny), "lon": np.linspace(0, 350, nx)}
    return xr.DataArray(values[None], dims=("time", "lat", "lon"), coords=coords)


def test_plot_comparison_shared_scale_and_difference():
    reference, test = field(np.zeros((4, 6))), field(np.full((4, 6), 5.0))
    fig = plot_comparison(reference, test, labels=("a", "b"), title="t")
    maps = [ax for ax in fig.axes if ax.get_title()]
    assert [ax.get_title() for ax in maps] == ["a", "b", "b - a"]
    assert [ax.collections[0].get_clim() for ax in maps[:2]] == [(0.0, 5.0), (0.0, 5.0)]
    assert maps[2].collections[0].get_clim() == (-5.0, 5.0)  # centred on 0
    assert fig.get_suptitle() == "t"


def test_plot_comparison_override_scale():
    fig = plot_comparison(field(np.zeros((4, 6))), field(np.ones((4, 6))), vmin=-1, vmax=2)
    assert {ax.collections[0].get_clim() for ax in fig.axes[:2]} == {(-1, 2)}


def test_plot_comparison_difference_only_on_same_surface():
    reference, test = field(np.zeros((4, 6))), field(np.ones((4, 6)))
    same = xr.ones_like(reference, dtype=bool)
    same[0, 0, 0] = False
    fig = plot_comparison(reference, test, same_surface=same)
    difference = [ax for ax in fig.axes if "same surface type" in ax.get_title()][0]
    values = difference.collections[0].get_array()
    assert np.ma.is_masked(values) and np.ma.count_masked(values) == 1


def test_plot_comparison_categories_without_difference():
    categories = {0: ("none", "#ffffff"), 1: ("forest", "#00aa00"), 2: ("grass", "#aaff00"), 3: ("ice", "#ffffff")}
    reference, test = field(np.zeros((4, 6))), field(np.ones((4, 6)))
    fig = plot_comparison(reference, test, categories=categories)
    maps = [ax for ax in fig.axes if ax.get_title()]
    assert len(maps) == 2  # no difference
    colorbar = [ax for ax in fig.axes if not ax.get_title()][0]
    labels = [t.get_text() for t in colorbar.get_yticklabels()]
    assert labels == ["none", "forest"]  # only the classes found in the fields


def test_plot_comparison_robust_scales():
    """Robust scales ignore a few very large values (2nd and 98th percentiles)."""
    values = np.linspace(0.0, 1.0, 100).reshape(4, 25)
    values[0, 0] = 1000.0
    fig = plot_comparison(field(np.zeros((4, 25))), field(values), robust=True)
    maps = [ax for ax in fig.axes if ax.get_title()]
    assert maps[0].collections[0].get_clim()[1] < 2.0
    assert maps[2].collections[0].get_clim()[1] < 2.0


def test_plot_comparison_rejects_3d():
    cube = xr.DataArray(np.zeros((2, 3, 4)), dims=("z", "y", "x"))
    with pytest.raises(ValueError, match="expected 2"):
        plot_comparison(cube, cube)


def test_sample_nearest_between_grids_across_the_dateline():
    lon, lat = np.meshgrid([0.0, 90.0, 180.0, 270.0], [-45.0, 45.0])
    values = np.arange(8).reshape(2, 4)
    sampled = sample_nearest(
        lon, lat, values, np.array([[359.0, 91.0], [-1.0, 269.0]]), np.array([[40, 40], [-40, -40]])
    )
    np.testing.assert_array_equal(sampled, [[4, 5], [0, 3]])


def test_symmetric_limit():
    assert symmetric_limit(np.array([-3.0, 2.0, np.nan])) == 3.0
    assert symmetric_limit(np.array([-3.0, 1.0, 1.0, 1.0, 1.0]), 50) == 1.0
    assert symmetric_limit(np.array([np.nan])) == 1.0
    assert symmetric_limit(np.zeros(3)) == 1.0


def test_save_figure_creates_directory(tmp_path: Path):
    fig = plot_comparison(field(np.zeros((4, 6))), field(np.ones((4, 6))))
    path = tmp_path / "a" / "b.png"
    save_figure(fig, path)
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert [p.name for p in path.parent.iterdir()] == ["b.png"]


needs_cdo = pytest.mark.skipif(shutil.which("cdo") is None, reason="needs cdo")


@needs_cdo
def test_load_grib_gridpoint(tmp_path: Path):
    path = tmp_path / "lsm.grb"
    subprocess.run(["cdo", "-s", "-f", "grb", "-setcode,172", "-const,1,r8x4", str(path)], check=True)
    ds = load_grib(str(path), grid="r8x4")
    assert list(ds.data_vars) == ["var172"]
    assert ds.sizes["lat"] == 4 and ds.sizes["lon"] == 8
    np.testing.assert_allclose(ds["var172"].values, 1.0)


@needs_cdo
def test_load_grib_selects_names(tmp_path: Path):
    parts = [tmp_path / "a.grb", tmp_path / "b.grb"]
    for part, code in zip(parts, (172, 30)):
        subprocess.run(["cdo", "-s", "-f", "grb", f"-setcode,{code}", "-const,1,r8x4", str(part)], check=True)
    path = tmp_path / "two.grb"
    subprocess.run(["cdo", "-s", "merge", *map(str, parts), str(path)], check=True)
    assert list(load_grib(str(path), ["var30"], grid="r8x4").data_vars) == ["var30"]


@needs_cdo
def test_load_grib_spectral(tmp_path: Path):
    """A spectral field goes to its Gaussian grid; the field is returned, not lat_bnds."""
    path = tmp_path / "z.grb"
    subprocess.run(["cdo", "-s", "-f", "grb", "-gp2sp", "-setcode,129", "-const,5,F16", str(path)], check=True)
    ds = load_grib(str(path))
    assert list(ds.data_vars) == ["var129"]
    assert ds.sizes["lat"] == 32 and ds.sizes["lon"] == 64
    np.testing.assert_allclose(ds["var129"].values, 5.0, rtol=1e-5)
