"""Tests for ``generate_subbasin_masks`` on a tiny synthetic ``mesh_mask_<name>.nc``.

The raw DOMAINcfg output exists only on Atos; the file here has only what the function reads: ``tmask``
(time, level, y, x) and ``glamt``/``gphit`` (time, y, x), on a regular 10-degree grid with two land strips.
"""

import logging
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from ecefast.components.nemo.domain.subbasins import generate_subbasin_masks

pytestmark = pytest.mark.unit

LON = np.arange(-175.0, 180.0, 10.0)  # 36 columns, cell centres
LAT = np.arange(-75.0, 90.0, 10.0)  # 17 rows
MASKS = ["atlmsk", "pacmsk", "indmsk", "indpacmsk", "glomsk"]


def write_mesh_mask(path: Path) -> np.ndarray:
    """Write the synthetic mesh_mask and return its surface ocean mask (y, x)."""
    lon, lat = np.meshgrid(LON, LAT)
    surface = np.ones(lon.shape, dtype="int8")
    surface[:, (LON > 0) & (LON < 20)] = 0  # a meridional land strip
    surface[lat < -70] = 0  # Antarctica
    surface[(lat > 30) & (lon > 100) & (lon < 140)] = 0  # a continent
    tmask = np.stack([surface, surface * (lat < 40)])[None]  # two levels: the second shallower in the north
    xr.Dataset(
        {
            "tmask": (("time_counter", "nav_lev", "y", "x"), tmask),
            "glamt": (("time_counter", "y", "x"), lon[None]),
            "gphit": (("time_counter", "y", "x"), lat[None]),
        }
    ).to_netcdf(path)
    return surface


@pytest.fixture
def masks(tmp_path: Path) -> tuple[xr.Dataset, np.ndarray]:
    ocean = write_mesh_mask(tmp_path / "mesh_mask_test.nc")
    generate_subbasin_masks(str(tmp_path), str(tmp_path / "out"), "test")
    with xr.open_dataset(tmp_path / "out" / "subbasins.nc") as ds:
        return ds.load(), ocean


def test_variables_and_coordinates(masks) -> None:
    ds, _ = masks
    assert list(ds.data_vars) == MASKS
    for var in MASKS:
        assert ds[var].dims == ("y", "x")
        assert ds[var].attrs["units"] == "1"
    np.testing.assert_array_equal(ds["navlon"].values[0], LON)
    np.testing.assert_array_equal(ds["navlat"].values[:, 0], LAT)


def test_masks_are_binary_on_ocean_only(masks) -> None:
    ds, ocean = masks
    for var in MASKS:
        values = ds[var].values
        assert set(np.unique(values)) <= {0, 1}, var
        assert not values[ocean == 0].any(), f"{var} has land points"


def test_global_is_ocean_and_basins_are_disjoint(masks) -> None:
    ds, ocean = masks
    np.testing.assert_array_equal(ds["glomsk"].values, ocean)
    basins = ds["atlmsk"].values + ds["pacmsk"].values + ds["indmsk"].values
    assert basins.max() == 1
    np.testing.assert_array_equal(ds["indpacmsk"].values, ds["pacmsk"].values + ds["indmsk"].values)


@pytest.mark.parametrize(
    "lon, lat, var",
    [(-35.0, 5.0, "atlmsk"), (-145.0, 5.0, "pacmsk"), (165.0, -15.0, "pacmsk"), (75.0, -25.0, "indmsk")],
)
def test_points_in_their_basin(masks, lon: float, lat: float, var: str) -> None:
    ds, _ = masks
    j, i = int(np.flatnonzero(LAT == lat)[0]), int(np.flatnonzero(LON == lon)[0])
    assert ds[var].values[j, i] == 1


def test_logs_statistics(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    write_mesh_mask(tmp_path / "mesh_mask_test.nc")
    with caplog.at_level(logging.INFO, logger="ecefast"):
        generate_subbasin_masks(str(tmp_path), str(tmp_path / "out"), "test")
    assert "Unassigned points" in caplog.text


def test_global_only(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """``regional=False`` (paleo bathymetries): only ``glomsk``, equal to the ocean mask, same coordinates."""
    ocean = write_mesh_mask(tmp_path / "mesh_mask_test.nc")
    with caplog.at_level(logging.INFO, logger="ecefast"):
        generate_subbasin_masks(str(tmp_path), str(tmp_path / "out"), "test", regional=False)
    assert "Global mask only for test" in caplog.text
    with xr.open_dataset(tmp_path / "out" / "subbasins.nc") as ds:
        assert list(ds.data_vars) == ["glomsk"]
        assert ds["glomsk"].dims == ("y", "x")
        assert ds["glomsk"].attrs == {"long_name": "Global ocean mask", "units": "1"}
        assert ds["glomsk"].dtype == np.int64
        np.testing.assert_array_equal(ds["glomsk"].values, ocean)
        np.testing.assert_array_equal(ds["navlon"].values[0], LON)
