"""Unit tests for the array helpers of ``paleo.eocene.oifs.fields``: modify_value, replace_value, regrid_dataset."""

import numpy as np
import pytest
import xarray as xr
from oifs_helpers import needs_cdo

from ecefast.paleo.eocene.oifs.fields import modify_value, regrid_dataset, replace_value

pytestmark = pytest.mark.unit

LAT = np.array([45.0, 15.0, -15.0, -45.0])  # descending, as CDO writes Gaussian grids
LON = np.array([0.0, 90.0, 180.0, 270.0, 300.0])


def grib_like_dataset(*names: str) -> xr.Dataset:
    """A dataset shaped like a GRIB field converted by CDO: (time=1, lat, lon), float32, distinct values."""
    values = np.arange(LAT.size * LON.size, dtype="float32").reshape(1, LAT.size, LON.size)
    coords = {"time": [0.0], "lat": LAT, "lon": LON}
    return xr.Dataset(
        {name: (("time", "lat", "lon"), values + 100 * i, {"units": "1"}) for i, name in enumerate(names)},
        coords=coords,
    )


# --- modify_value --------------------------------------------------------------------------------------------------


def test_modify_value_sets_listed_variables_only() -> None:
    field = grib_like_dataset("q", "cc", "t")
    untouched = field["t"].values.copy()

    result = modify_value(field, var=["q", "cc", "not_in_file"], newvalue=0.0)

    assert result is field
    assert np.all(result["q"].values == 0.0)
    assert np.all(result["cc"].values == 0.0)
    np.testing.assert_array_equal(result["t"].values, untouched)
    # shape, dims and attributes are kept: only .data is replaced
    assert result["q"].dims == ("time", "lat", "lon")
    assert result["q"].attrs == {"units": "1"}


def test_modify_value_dtype_follows_newvalue() -> None:
    """np.full(shape, newvalue) takes the dtype of ``newvalue``: a float32 field becomes float64 (or int64).

    The GRIB packing hides this; create_init passes floats (1.0, 2.0, 0.0) for isor, slt and the zeroed fields.
    """
    field = grib_like_dataset("slt")
    assert modify_value(field, var=["slt"], newvalue=2.0)["slt"].dtype == np.float64
    field = grib_like_dataset("slt")
    assert modify_value(field, var=["slt"], newvalue=2)["slt"].dtype.kind == "i"


# --- replace_value -------------------------------------------------------------------------------------------------


def test_replace_value_adds_time_and_transposes() -> None:
    field = grib_like_dataset("lsm", "al")
    al_before = field["al"].values.copy()
    # new field given as (lon, lat) without time: replace_value expands time and transposes to (time, lat, lon)
    new = xr.DataArray(
        np.outer(np.arange(LON.size), np.ones(LAT.size)), dims=("lon", "lat"), coords={"lon": LON, "lat": LAT}
    )

    result = replace_value(field, var=["lsm"], newfield=new)

    expected = new.transpose("lat", "lon").values[None]
    np.testing.assert_array_equal(result["lsm"].values, expected)
    np.testing.assert_array_equal(result["al"].values, al_before)


def test_replace_value_keeps_existing_time_dimension() -> None:
    field = grib_like_dataset("sdor")
    new = xr.DataArray(np.full((1, LAT.size, LON.size), 7.0), dims=("time", "lat", "lon"))
    assert np.all(replace_value(field, var=["sdor"], newfield=new)["sdor"].values == 7.0)


def test_replace_value_assigns_by_position_not_by_coordinate() -> None:
    """The new field is copied by position: its coordinates are not aligned with the field.

    A new field with ascending latitude lands upside down on a field with descending latitude. In the workflow both
    come out of CDO with the same Gaussian latitude order, so this does not happen; the test pins the behaviour.
    """
    field = grib_like_dataset("lsm")
    ascending = xr.DataArray(
        np.repeat(np.arange(LAT.size, dtype=float)[:, None], LON.size, axis=1),
        dims=("lat", "lon"),
        coords={"lat": LAT[::-1], "lon": LON},
    )
    result = replace_value(field, var=["lsm"], newfield=ascending)
    # first row of the result (lat=45) holds the first row of the new field (its lat=-45)
    np.testing.assert_array_equal(result["lsm"].values[0, :, 0], [0.0, 1.0, 2.0, 3.0])


# --- regrid_dataset ------------------------------------------------------------------------------------------------


def lonlat_dataset(lat: np.ndarray, lon: np.ndarray, values: np.ndarray, name: str = "v") -> xr.Dataset:
    coords = {
        "lat": ("lat", lat, {"units": "degrees_north", "standard_name": "latitude"}),
        "lon": ("lon", lon, {"units": "degrees_east", "standard_name": "longitude"}),
    }
    return xr.Dataset({name: (("lat", "lon"), values)}, coords=coords)


@needs_cdo
def test_regrid_dataset_constant_field_stays_constant() -> None:
    """Bilinear weights sum to one, so a constant field is still the same constant on the target grid."""
    src_lat, src_lon = np.arange(-80.0, 81.0, 20.0), np.arange(0.0, 360.0, 20.0)
    source = lonlat_dataset(src_lat, src_lon, np.full((src_lat.size, src_lon.size), 3.5))
    ref_lat, ref_lon = np.array([-30.0, 10.0, 50.0]), np.array([5.0, 95.0, 185.0, 275.0])
    reference = lonlat_dataset(ref_lat, ref_lon, np.zeros((3, 4)), name="grid")

    result = regrid_dataset(source, reference)

    assert isinstance(result, xr.Dataset)
    assert result["v"].shape == (3, 4)
    np.testing.assert_allclose(result["lat"].values, ref_lat)
    np.testing.assert_allclose(result["lon"].values, ref_lon)
    np.testing.assert_allclose(result["v"].values, 3.5)


@needs_cdo
def test_regrid_dataset_bilinear_on_linear_field() -> None:
    """Bilinear interpolation is exact for a field linear in latitude: v = lat, sampled between source points."""
    src_lat, src_lon = np.arange(-80.0, 81.0, 20.0), np.arange(0.0, 360.0, 30.0)
    source = lonlat_dataset(src_lat, src_lon, np.repeat(src_lat[:, None], src_lon.size, axis=1))
    ref_lat = np.array([-50.0, -5.0, 35.0])
    reference = lonlat_dataset(ref_lat, np.array([15.0, 200.0]), np.zeros((3, 2)))

    result = regrid_dataset(source["v"], reference)

    np.testing.assert_allclose(result.values, np.repeat(ref_lat[:, None], 2, axis=1), atol=1e-6)


@needs_cdo
def test_regrid_dataset_dataarray_in_dataarray_out() -> None:
    lat, lon = np.array([-45.0, 45.0]), np.array([0.0, 90.0, 180.0, 270.0])
    data = lonlat_dataset(lat, lon, np.arange(8.0).reshape(2, 4))["v"]
    reference = lonlat_dataset(lat, lon, np.zeros((2, 4)))["v"].rename(None)

    named = regrid_dataset(data, reference, method="remapnn")
    unnamed = regrid_dataset(data.rename(None), reference, method="remapnn")

    # nearest neighbour on the same grid is the identity
    assert isinstance(named, xr.DataArray) and named.name == "v"
    np.testing.assert_array_equal(named.values, data.values)
    # an unnamed DataArray is written as "var" and comes back with that name
    assert unnamed.name == "var"
    np.testing.assert_array_equal(unnamed.values, data.values)
