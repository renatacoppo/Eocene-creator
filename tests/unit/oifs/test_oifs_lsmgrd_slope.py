"""Unit tests for ``lsmgrd.lsmgrd`` and ``subgrid_orog.compute_slope`` on tiny hand-made grids."""

import logging

import numpy as np
import pytest
import xarray as xr

from ecefast.paleo.eocene.oifs.lsmgrd import lsmgrd
from ecefast.paleo.eocene.oifs.subgrid_orog import compute_slope

pytestmark = pytest.mark.unit

LAT_DESC = np.array([60.0, 20.0, -20.0, -60.0])
LON = np.array([0.0, 120.0, 240.0])


def grib_like(name: str, value: float = 1.0) -> xr.Dataset:
    data = np.full((1, LAT_DESC.size, LON.size), value, dtype="float32")
    return xr.Dataset(
        {name: (("time", "lat", "lon"), data, {"long_name": name})},
        coords={"time": [0.0], "lat": LAT_DESC, "lon": LON},
    )


# --- lsmgrd --------------------------------------------------------------------------------------------------------


def eocene_mask() -> xr.DataArray:
    """Land (1) north of the equator at lon 0 and everywhere at lon 240, on a finer ascending grid (nearest interp)."""
    lat = np.arange(-80.0, 81.0, 10.0)
    lon = np.arange(0.0, 360.0, 30.0)
    mask = np.zeros((lat.size, lon.size))
    mask[lat > 0, 0] = 1.0
    mask[:, lon == 240.0] = 1.0
    return xr.DataArray(mask, dims=("lat", "lon"), coords={"lat": lat, "lon": lon})


def test_lsmgrd_land_3_ocean_0() -> None:
    field = grib_like("lsmgrd", value=7.0)

    result = lsmgrd(field, var=["lsmgrd"], landsea=eocene_mask())

    # rows in the field order (60, 20, -20, -60), columns lon 0, 120, 240
    expected = np.array([[3, 0, 3], [3, 0, 3], [0, 0, 3], [0, 0, 3]])
    np.testing.assert_array_equal(result["lsmgrd"].values[0], expected)
    assert result["lsmgrd"].dims == ("time", "lat", "lon")
    assert result["lsmgrd"].attrs == {"long_name": "lsmgrd"}


def test_lsmgrd_accepts_a_dataset_mask() -> None:
    mask = eocene_mask().sortby("lat", ascending=False).to_dataset(name="landsea_mask")
    result = lsmgrd(grib_like("lsmgrd"), landsea=mask)
    assert set(np.unique(result["lsmgrd"].values)) == {0, 3}


def test_lsmgrd_errors() -> None:
    with pytest.raises(ValueError, match="landsea"):
        lsmgrd(grib_like("lsmgrd"))
    with pytest.raises(ValueError, match="lsmgrd"):
        lsmgrd(grib_like("lsm"), landsea=eocene_mask())


# --- compute_slope -------------------------------------------------------------------------------------------------

A, B = 4.376786e-05, 2.476405e-04  # the defaults of compute_slope


def sd_field() -> xr.DataArray:
    sd = np.array([[0.0, 100.0, 1000.0]] * LAT_DESC.size)
    return xr.DataArray(sd, dims=("lat", "lon"), coords={"lat": LAT_DESC, "lon": LON})


def test_compute_slope_linear_transfer() -> None:
    """slope = a * sd + b: sd = 0 gives b, sd = 1000 gives 1000 a + b = 0.0440155."""
    result = compute_slope(grib_like("slor"), var=["slor"], sd_eoc=sd_field())

    expected_row = [B, 100 * A + B, 1000 * A + B]
    np.testing.assert_allclose(result["slor"].values[0], [expected_row] * LAT_DESC.size, rtol=1e-6)
    np.testing.assert_allclose(result["slor"].values[0, 0, 2], 0.0440155, rtol=1e-5)
    assert result["slor"].shape == (1, LAT_DESC.size, LON.size)


def test_compute_slope_custom_coefficients_and_no_time() -> None:
    field = xr.Dataset({"slor": (("lat", "lon"), np.zeros((LAT_DESC.size, LON.size)))})
    result = compute_slope(field, var=["slor"], sd_eoc=sd_field(), a=2.0, b=1.0)
    np.testing.assert_allclose(result["slor"].values[:, 2], 2001.0)


def test_compute_slope_input_with_time_and_same_shape() -> None:
    sd = sd_field().expand_dims("time")
    result = compute_slope(grib_like("slor"), var=["slor"], sd_eoc=sd, a=1.0, b=0.0)
    np.testing.assert_allclose(result["slor"].values, sd.values)


@pytest.mark.xfail(strict=True, reason="subgrid_orog.py logs with a stray argument and no placeholder (logging error)")
def test_compute_slope_debug_log_is_well_formed(
    capsys: pytest.CaptureFixture, caplog: pytest.LogCaptureFixture
) -> None:
    """``logger.debug("Computed new slope (before expanding dims):", new_slope.shape)`` has no ``%s``.

    At DEBUG level the logging module cannot format the record and prints "--- Logging error ---" to stderr.
    """
    with caplog.at_level(logging.DEBUG, logger="ecefast"):
        compute_slope(grib_like("slor"), var=["slor"], sd_eoc=sd_field())
    assert "Logging error" not in capsys.readouterr().err
