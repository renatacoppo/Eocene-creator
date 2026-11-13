"""Unit tests for the cell corners of the OIFS reduced Gaussian grids (``ecefast.components.oifs.corners``)."""

from pathlib import Path

import netCDF4 as nc
import numpy as np
import pytest

from ecefast.components.oifs import corners
from ecefast.components.oifs.corners import reduced_grid_corners, write_corner_grid

pytestmark = pytest.mark.unit

# four equally spaced bands, two points at the poles' bands and four at the equator's
LAT = np.array([60.0, 20.0, -20.0, -60.0])
REDUCED_POINTS = np.array([2, 4, 4, 2])


def test_corners_lie_between_bands_and_points() -> None:
    lons, lats, corners_lon, corners_lat = reduced_grid_corners(LAT, REDUCED_POINTS)
    assert lons.shape == lats.shape == (12,)
    assert corners_lon.shape == corners_lat.shape == (12, 4)
    np.testing.assert_array_equal(lats, [60, 60, 20, 20, 20, 20, -20, -20, -20, -20, -60, -60])
    np.testing.assert_array_equal(lons[:6], [0, 180, 0, 90, 180, -90])
    # upper, upper, lower, lower latitudes of each band
    np.testing.assert_array_equal(corners_lat[0], [80, 80, 40, 40])
    np.testing.assert_array_equal(corners_lat[2], [40, 40, 0, 0])
    np.testing.assert_array_equal(corners_lat[-1], [-40, -40, -80, -80])
    # left, right, right, left longitudes, in (-180, 180]
    np.testing.assert_array_equal(corners_lon[0], [-90, 90, 90, -90])
    np.testing.assert_array_equal(corners_lon[1], [90, -90, -90, 90])


def test_latitudes_are_not_modified() -> None:
    lat = LAT.copy()
    reduced_grid_corners(lat, REDUCED_POINTS)
    np.testing.assert_array_equal(lat, LAT)


def test_mismatched_bands_raise() -> None:
    with pytest.raises(ValueError, match="does not match"):
        reduced_grid_corners(LAT, REDUCED_POINTS[:-1])


@pytest.mark.parametrize("masked", [False, True], ids=["grid", "masked"])
def test_write_corner_grid(tmp_path: Path, masked: bool) -> None:
    grid = reduced_grid_corners(LAT, REDUCED_POINTS)
    mask = np.arange(12, dtype="f4") if masked else None
    outfile = tmp_path / "TL3_grid.nc"
    write_corner_grid(str(outfile), *grid, mask=mask)
    assert [p.name for p in tmp_path.iterdir()] == ["TL3_grid.nc"]
    with nc.Dataset(outfile) as ds:
        field = "lsm" if masked else "lml"
        assert list(ds.variables) == ["clon", "clat", field, "clon_bnds", "clat_bnds"]
        assert dict(ds.dimensions.items()).keys() == {"rgrid", "nv"}
        assert ds["clon"].bounds == "clon_bnds" and ds["clat"].standard_name == "latitude"
        assert ds[field].coordinates == "clat clon"
        np.testing.assert_allclose(ds["clat"][:], np.deg2rad(grid[1]))
        np.testing.assert_allclose(ds["clon_bnds"][:], np.deg2rad(grid[2]))
        if masked:
            np.testing.assert_array_equal(ds["lsm"][:], mask)


@pytest.mark.parametrize("masked", [False, True], ids=["grid", "with-masked"])
def test_create_corner_grid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, masked: bool) -> None:
    mask = np.arange(12, dtype="f4")
    monkeypatch.setattr(corners, "read_reduced_grid", lambda *args: (LAT, REDUCED_POINTS, mask))
    masked_outfile = str(tmp_path / "TL3_grid_masked.nc") if masked else None
    corners.create_corner_grid("ICMGGECE4INIT", "L", 3, str(tmp_path / "TL3_grid.nc"), str(tmp_path), masked_outfile)
    expected = ["TL3_grid.nc", "TL3_grid_masked.nc"] if masked else ["TL3_grid.nc"]
    assert sorted(p.name for p in tmp_path.iterdir()) == expected
    with nc.Dataset(tmp_path / "TL3_grid.nc") as ds:
        assert "lml" in ds.variables
    if masked:
        with nc.Dataset(tmp_path / "TL3_grid_masked.nc") as ds:
            np.testing.assert_array_equal(ds["lsm"][:], mask)
