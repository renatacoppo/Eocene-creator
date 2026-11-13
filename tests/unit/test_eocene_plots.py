"""Unit tests for the Eocene plot helpers."""

import shutil
import subprocess
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402
import xarray as xr  # noqa: E402

from ecefast.periods.eocene.plots.helper_functions import load_grib_var_spec, plot_before_after  # noqa: E402

pytestmark = pytest.mark.unit


def field(values: np.ndarray) -> xr.DataArray:
    """A 1 x ny x nx field on a regular lon/lat grid."""
    ny, nx = values.shape
    coords = {"time": [0], "lat": np.linspace(-80, 80, ny), "lon": np.linspace(0, 350, nx)}
    return xr.DataArray(values[None], dims=("time", "lat", "lon"), coords=coords)


def test_plot_before_after_shared_scale():
    before, after = field(np.zeros((4, 6))), field(np.full((4, 6), 5.0))
    fig = plot_before_after(before, after, title="t", labels=("a", "b"))
    maps = fig.axes[:2]  # the two panels; their colorbars follow
    assert [ax.get_title() for ax in maps] == ["a", "b"]
    assert [ax.collections[0].get_clim() for ax in maps] == [(0.0, 5.0), (0.0, 5.0)]
    assert fig.get_suptitle() == "t"
    plt.close(fig)


def test_plot_before_after_override_scale():
    fig = plot_before_after(field(np.zeros((4, 6))), field(np.ones((4, 6))), vmin=-1, vmax=2)
    assert {ax.collections[0].get_clim() for ax in fig.axes[:2]} == {(-1, 2)}
    plt.close(fig)


def test_plot_before_after_rejects_3d():
    cube = xr.DataArray(np.zeros((2, 3, 4)), dims=("z", "y", "x"))
    with pytest.raises(ValueError, match="expected 2"):
        plot_before_after(cube, cube)


needs_cdo = pytest.mark.skipif(shutil.which("cdo") is None, reason="needs cdo")


@needs_cdo
def test_load_grib_var_spec_gridpoint(tmp_path: Path):
    path = tmp_path / "lsm.grb"
    subprocess.run(["cdo", "-s", "-f", "grb", "-setcode,172", "-const,1,r8x4", str(path)], check=True)
    da = load_grib_var_spec(str(path), "var172", grid="r8x4")
    assert da.name == "var172"
    assert da.sizes["lat"] == 4 and da.sizes["lon"] == 8
    np.testing.assert_allclose(da.values, 1.0)


@needs_cdo
def test_load_grib_var_spec_spectral(tmp_path: Path):
    """A spectral field goes to its Gaussian grid; the field is returned, not lat_bnds."""
    path = tmp_path / "z.grb"
    subprocess.run(["cdo", "-s", "-f", "grb", "-gp2sp", "-setcode,129", "-const,5,F16", str(path)], check=True)
    da = load_grib_var_spec(str(path), "var129")
    assert da.name == "var129"
    assert da.sizes["lat"] == 32 and da.sizes["lon"] == 64
    np.testing.assert_allclose(da.values, 5.0, rtol=1e-5)
