"""Unit tests for the helpers of the NEMO ``woa-pi`` ocean initial state."""

from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from ecefast.periods.eocene.nemo.eoceneNEMO import present_day_ocean_mask, woa_zonal_mean

pytestmark = pytest.mark.unit


def write_domain(path: Path, glamt: np.ndarray, gphit: np.ndarray, bottom_level: np.ndarray) -> Path:
    """A minimal present-day NEMO domain file: bottom_level, glamt, gphit with a time_counter axis."""
    dims = ("time_counter", "y", "x")
    xr.Dataset(
        {
            "bottom_level": (dims, bottom_level[np.newaxis].astype("int32")),
            "glamt": (dims, glamt[np.newaxis]),
            "gphit": (dims, gphit[np.newaxis]),
        }
    ).to_netcdf(path)
    return path


def test_present_day_ocean_mask_same_grid(tmp_path: Path) -> None:
    lon, lat = np.meshgrid([0.0, 120.0, 240.0], [-30.0, 30.0])
    bottom = np.array([[0, 1, 3], [2, 0, 1]])
    domain = write_domain(tmp_path / "domain_cfg.nc", lon, lat, bottom)

    mask = present_day_ocean_mask(domain, lon, lat, nz=3)

    assert mask.dims == ("z", "y", "x")
    assert mask.dtype == bool
    # level k (0-based) is ocean where bottom_level >= k + 1
    expected = np.stack([bottom >= 1, bottom >= 2, bottom >= 3])
    np.testing.assert_array_equal(mask.values, expected)


def test_present_day_ocean_mask_nearest_across_dateline(tmp_path: Path) -> None:
    # domain longitudes in [-180, 180), target in [0, 360): 179.5 is nearest to -179 (1.5 deg away)
    lon_dom = np.array([[-179.0, 0.0, 90.0]])
    lat_dom = np.zeros((1, 3))
    domain = write_domain(tmp_path / "domain_cfg.nc", lon_dom, lat_dom, np.array([[2, 0, 1]]))

    lon_tgt = np.array([[179.5, 359.0, 91.0]])
    mask = present_day_ocean_mask(domain, lon_tgt, np.zeros((1, 3)), nz=2)

    np.testing.assert_array_equal(mask.values, [[[True, False, True]], [[True, False, False]]])


def test_woa_zonal_mean() -> None:
    # (time_counter=1, z=3, y=3, x=2), value = 100 z + 10 y + x
    z, y, x = np.meshgrid(np.arange(3), np.arange(3), np.arange(2), indexing="ij")
    thetao = xr.DataArray((100.0 * z + 10.0 * y + x)[np.newaxis], dims=("time_counter", "z", "y", "x"))
    land, both, east, west = [False, False], [True, True], [False, True], [True, False]
    ocean = xr.DataArray(
        np.array(
            [
                [land, east, both],  # z=0
                [land, both, both],  # z=1
                [land, land, west],  # z=2
            ]
        ),
        dims=("z", "y", "x"),
    )

    zm = woa_zonal_mean(thetao, ocean)

    # y=1: z0 only x=1 (11), z1 mean of 110 and 111, z2 all land -> nearest level (z1)
    # y=2: z0 and z1 means, z2 only x=0 (220)
    # y=0: all land at every level (Antarctica) -> nearest latitude (y=1)
    expected_zy = np.array(
        [
            [11.0, 11.0, 20.5],
            [110.5, 110.5, 120.5],
            [110.5, 110.5, 220.0],
        ]
    )
    assert zm.dims == thetao.dims
    assert zm.shape == thetao.shape
    np.testing.assert_allclose(zm.values, np.broadcast_to(expected_zy[np.newaxis, :, :, np.newaxis], thetao.shape))


def test_woa_zonal_mean_ignores_nan_in_ocean() -> None:
    thetao = xr.DataArray(np.array([[[[1.0, np.nan, 3.0]]]]), dims=("time_counter", "z", "y", "x"))
    ocean = xr.DataArray(np.ones((1, 1, 3), dtype=bool), dims=("z", "y", "x"))

    zm = woa_zonal_mean(thetao, ocean)

    np.testing.assert_allclose(zm.values, 2.0)
