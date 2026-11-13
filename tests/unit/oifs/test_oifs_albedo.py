"""Unit tests for ``periods.eocene.oifs.albedo.albedo`` on tiny hand-made grids.

Expected values follow the code: each variable is replaced by its zonal mean over present-day land (latitudes with
no land take the value of the nearest latitude), polar bands are filled with the mean of a nearby band, then the
Eocene ocean gets 0.05 (diffuse albedo) or 0 (direct albedo, LAI, bare-soil albedo).
"""

import logging

import numpy as np
import pytest
import xarray as xr

from ecefast.periods.eocene.oifs.albedo import albedo

pytestmark = pytest.mark.unit

LAT_ASC = np.array([-40.0, -10.0, 0.0, 30.0])
LON = np.array([0.0, 90.0, 180.0, 270.0])


def field_descending(names: list[str], offsets: list[float], lat_asc: np.ndarray = LAT_ASC, lon=LON) -> xr.Dataset:
    """Dataset (time=1, lat descending, lon), as CDO writes it: value offset + 10*i + j, i on the ascending latitude."""
    i = np.arange(lat_asc.size)[:, None]
    j = np.arange(lon.size)[None, :]
    data = {}
    for name, offset in zip(names, offsets):
        values = (offset + 10.0 * i + j)[::-1][None]  # store with descending latitude
        data[name] = (("time", "lat", "lon"), values.astype("float32"))
    return xr.Dataset(data, coords={"time": [0.0], "lat": lat_asc[::-1], "lon": lon})


def present_day_mask() -> xr.DataArray:
    """Present-day land at the first two longitudes, except at lat=0 (no land on that row)."""
    lsm = np.zeros((LAT_ASC.size, LON.size))
    lsm[:, :2] = 1.0
    lsm[2, :] = 0.0
    return xr.DataArray(lsm, dims=("lat", "lon"), coords={"lat": LAT_ASC, "lon": LON})


def eocene_mask_dataset() -> xr.Dataset:
    """Eocene land at longitudes 0 and 180, on a finer 5-degree grid with descending latitude.

    The finer grid exercises the nearest-neighbour interpolation; it covers every field point, because
    ``interp(method="nearest")`` gives NaN (ocean) outside the range of the mask grid.
    """
    lat = np.arange(45.0, -51.0, -5.0)
    lon = np.arange(0.0, 360.0, 5.0)
    mask = np.zeros((lat.size, lon.size), dtype=int)
    mask[:, np.isin(lon, [0.0, 180.0])] = 1
    return xr.Dataset({"landsea_mask": (("lat", "lon"), mask)}, coords={"lat": lat, "lon": lon})


# Zonal mean over present-day land (j = 0, 1) of offset + 10*i + j is offset + 10*i + 0.5 on rows i = 0, 1, 3.
# Row i = 2 (lat 0) has no land: interpolate_na(method="nearest") takes lat -10 (10 degrees away, lat 30 is 30 away).
ZONAL = np.array([0.5, 10.5, 10.5, 30.5])
EOCENE_LAND = np.array([True, False, True, False])  # per longitude


def expected(offset: float, ocean_value: float) -> np.ndarray:
    """Expected (lat descending, lon) array: reconstructed zonal mean on Eocene land, ``ocean_value`` elsewhere."""
    recon = np.repeat((offset + ZONAL)[:, None], LON.size, axis=1)
    return np.where(EOCENE_LAND[None, :], recon, ocean_value)[::-1]


def test_albedo_reconstruction_and_eocene_mask() -> None:
    field = field_descending(["al", "aluvpi", "lai_lv"], [0.0, 100.0, 200.0])

    result = albedo(
        field, lsm_present=present_day_mask(), landsea=eocene_mask_dataset(), var=["al", "aluvpi", "lai_lv"]
    )

    np.testing.assert_allclose(result["al"].values[0], expected(0.0, 0.05))  # diffuse albedo: 0.05 over ocean
    np.testing.assert_allclose(result["aluvpi"].values[0], expected(100.0, 0.0))  # direct albedo: 0 over ocean
    np.testing.assert_allclose(result["lai_lv"].values[0], expected(200.0, 0.0))  # LAI: 0 over ocean
    assert result["al"].dims == ("time", "lat", "lon")
    np.testing.assert_array_equal(result["lat"].values, LAT_ASC[::-1])


def test_albedo_bare_soil_codes_zeroed_over_ocean() -> None:
    codes = ["code117", "code118", "code119", "code120"]
    field = field_descending(codes, [0.0, 1000.0, 2000.0, 3000.0])

    result = albedo(field, lsm_present=present_day_mask(), landsea=eocene_mask_dataset()["landsea_mask"], var=codes)

    for code, offset in zip(codes, [0.0, 1000.0, 2000.0, 3000.0]):
        np.testing.assert_allclose(result[code].values[0], expected(offset, 0.0))


def test_albedo_polar_bands() -> None:
    """South of 52S takes the mean of 52S-46S, north of 75N the mean of 70N-75N.

    Rows at -70, -50, 72, 80 with all land and values 10*i + j (j = 0, 1): zonal means 0.5, 10.5, 20.5, 30.5;
    -70 gets the -50 row (10.5), 80 gets the 72 row (20.5).
    """
    lat_asc = np.array([-70.0, -50.0, 72.0, 80.0])
    lon = np.array([0.0, 180.0])
    field = field_descending(["al"], [0.0], lat_asc=lat_asc, lon=lon)
    land = xr.DataArray(np.ones((4, 2)), dims=("lat", "lon"), coords={"lat": lat_asc, "lon": lon})

    result = albedo(field, lsm_present=land, landsea=land, var=["al"])

    rows = result["al"].values[0][::-1, 0]  # back to ascending latitude
    np.testing.assert_allclose(rows, [10.5, 10.5, 20.5, 20.5])


def test_albedo_requires_both_masks() -> None:
    field = field_descending(["al"], [0.0])
    with pytest.raises(ValueError, match="lsm_present"):
        albedo(field, landsea=present_day_mask(), var=["al"])
    with pytest.raises(ValueError, match="landsea"):
        albedo(field, lsm_present=present_day_mask(), var=["al"])


def test_albedo_warns_on_unknown_variables(caplog: pytest.LogCaptureFixture) -> None:
    field = field_descending(["al"], [0.0])
    with caplog.at_level(logging.WARNING):
        albedo(field, lsm_present=present_day_mask(), landsea=eocene_mask_dataset(), var=["al", "tsn"])
    assert "tsn" in caplog.text
