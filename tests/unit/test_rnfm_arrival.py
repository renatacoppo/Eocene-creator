"""Unit tests for the runoff-mapper arrival points that fit the OASIS weights (components/rnfm/arrival.py)."""

from pathlib import Path

import netCDF4
import numpy as np
import pytest
import xarray as xr

from ecefast.components.rnfm.arrival import (
    MAX_SPREAD_KM,
    SEA,
    TARGET_ERROR,
    fix_arrival_ids,
    fix_runoff_maps,
    read_transfer_factors,
    transfer_factors,
    unit_vectors,
    write_runoff_maps,
)

pytestmark = pytest.mark.unit

# a 2 degree regular grid around the equator: neighbouring cells are about 220 km apart
LAT = np.linspace(-9.0, 9.0, 10)
LON = np.arange(0.0, 360.0, 2.0)
SHAPE = (LAT.size, LON.size)
LAKE = -1


def grid() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Arrival ids (all sea), transfer factors (all 0), cell areas and unit vectors of the synthetic grid."""
    ids = np.full(SHAPE, SEA, dtype=np.int32)
    area = np.cos(np.deg2rad(LAT))[:, None].repeat(LON.size, axis=1)
    return ids, np.zeros(SHAPE), area, unit_vectors(LAT, LON)


def fraction(ids: np.ndarray, basin: int, factors: np.ndarray, area: np.ndarray) -> float:
    cells = ids == basin
    return float((factors[cells] * area[cells]).sum() / area[cells].sum())


# --- transfer factors ----------------------------------------------------------------------------------------------


def test_transfer_factors_ignore_padding_links() -> None:
    src = np.array([1, 2, 2, 0])  # 1-based; the last link is OASIS padding
    dst = np.array([1, 1, 2, 0])
    weights = np.array([0.5, 0.5, 1.0, 9.0])
    factors = transfer_factors(src, dst, weights, np.array([1.0, 2.0, 1.0]), np.array([3.0, 1.0]))
    np.testing.assert_allclose(factors, [1.5, (0.5 * 3 + 1.0) / 2.0, 0.0])


def test_read_transfer_factors(tmp_path: Path) -> None:
    rmp = xr.Dataset(
        {
            "src_address": ("num_links", np.array([1, 4], dtype=np.int32)),
            "dst_address": ("num_links", np.array([1, 2], dtype=np.int32)),
            "remap_matrix": (("num_links", "num_wgts"), np.array([[1.0], [0.5]])),
        }
    )
    areas = xr.Dataset(
        {
            "SRC.srf": (("y_SRC", "x_SRC"), np.full((2, 2), 2.0)),
            "DST.srf": (("y_DST", "x_DST"), np.array([[4.0, 4.0]])),
        }
    )
    rmp.to_netcdf(tmp_path / "rmp.nc")
    areas.to_netcdf(tmp_path / "areas.nc")
    factors = read_transfer_factors(str(tmp_path / "rmp.nc"), str(tmp_path / "areas.nc"), "SRC", "DST")
    np.testing.assert_allclose(factors, [[2.0, 0.0], [0.0, 1.0]])


# --- arrival cells -------------------------------------------------------------------------------------------------


def test_basin_within_max_error_is_kept() -> None:
    ids, factors, area, points = grid()
    ids[4, 10:12] = 1
    factors[4, 10:12] = [1.2, 0.6]
    new, changes = fix_arrival_ids(ids, factors, area, points, max_error=0.5)
    np.testing.assert_array_equal(new, ids)
    assert changes == []


def test_lost_basin_moves_to_nearest_deliverable_sea_cell() -> None:
    ids, factors, area, points = grid()
    ids[4, 10:12] = 1  # its sea is not in the target grid: nothing delivers
    factors[4, 14] = 1.0  # nearest deliverable sea cell (3 cells east of 4, 11)
    ids[4, 13], factors[4, 13] = LAKE, 1.0  # nearer, but a lake
    ids[4, 12], factors[4, 12] = 2, 1.0  # nearer, but another basin's
    new, changes = fix_arrival_ids(ids, factors, area, points, max_error=0.5)
    assert np.argwhere(new == 1).tolist() == [[4, 14]]
    assert (new[4, 10:12] == SEA).all()
    assert (new[4, 12], new[4, 13]) == (2, LAKE)
    (change,) = changes
    assert (change.basin, change.before, change.after, change.cells_before, change.cells_after) == (1, 0.0, 1.0, 2, 1)
    assert change.moved_km == pytest.approx(3 * 2 * np.pi * 6371.0 / 180.0, rel=1e-3)
    assert (change.lat, change.lon) == pytest.approx((LAT[4], LON[14]))


def test_partly_lost_basin_keeps_its_delivering_cells_and_is_balanced() -> None:
    ids, factors, area, points = grid()
    ids[4, 10:12] = 1
    factors[4, 10] = 0.5  # the other cell delivers nothing: the basin delivers 0.25
    factors[5, 10] = 0.2  # nearest, but takes the basin further from 1
    factors[4, 12] = 1.5  # brings it to 1
    new, changes = fix_arrival_ids(ids, factors, area, points, max_error=0.5)
    assert sorted(map(tuple, np.argwhere(new == 1).tolist())) == [(4, 10), (4, 12)]
    assert new[4, 11] == SEA
    assert changes[0].moved_km == 0.0
    assert abs(fraction(new, 1, factors, area) - 1.0) <= TARGET_ERROR


def test_over_delivering_basin_is_diluted() -> None:
    ids, factors, area, points = grid()
    ids[4, 10] = 1
    factors[4, 10] = 2.0
    factors[4, 9] = factors[4, 11] = 0.5
    new, _ = fix_arrival_ids(ids, factors, area, points, max_error=0.5)
    assert sorted(map(tuple, np.argwhere(new == 1).tolist())) == [(4, 9), (4, 10), (4, 11)]
    assert fraction(new, 1, factors, area) == pytest.approx(1.0)


def test_small_max_error_rebuilds_more_basins() -> None:
    ids, factors, area, points = grid()
    ids[4, 10] = 1
    factors[4, 10] = 1.2
    factors[4, 11] = 0.8
    assert fix_arrival_ids(ids, factors, area, points, max_error=0.5)[1] == []
    new, changes = fix_arrival_ids(ids, factors, area, points, max_error=TARGET_ERROR)
    assert [c.basin for c in changes] == [1]
    assert fraction(new, 1, factors, area) == pytest.approx(1.0)


def test_basin_without_any_deliverable_cell_is_an_error() -> None:
    ids, factors, area, points = grid()
    ids[4, 10] = 3
    with pytest.raises(ValueError, match="calving_point_id: basin 3 cannot be rebuilt: no free ocean cell"):
        fix_arrival_ids(ids, factors, area, points, max_error=0.5, variable="calving_point_id")


def test_basin_that_cannot_be_balanced_nearby_is_an_error() -> None:
    ids, factors, area, points = grid()
    ids[4, 10] = 1
    factors[4, 11] = 3.0  # only over-delivering cells nearby
    factors[4, 0] = 0.1  # the cell that would balance it is too far
    assert 10 * 2 * np.pi * 6371.0 / 180.0 > MAX_SPREAD_KM
    with pytest.raises(ValueError, match=f"basin 1 cannot be rebuilt: delivers 3.000 .* {MAX_SPREAD_KM:.0f} km"):
        fix_arrival_ids(ids, factors, area, points, max_error=0.5)


# --- runoff_maps.nc ------------------------------------------------------------------------------------------------


def maps_file(path: Path) -> Path:
    """A runoff_maps.nc laid out as the EC-Earth one: lon before lat, coordinates first, CDO history."""
    ids, *_ = grid()
    drainage = ids.copy()
    drainage[:2] = 1  # land of basin 1
    arrival = ids.copy()
    arrival[4, 10:12] = 1
    with netCDF4.Dataset(path, "w") as nc:
        nc.createDimension("lon", LON.size)
        nc.createDimension("lat", LAT.size)
        nc.createVariable("lon", "f8", ("lon",))[:] = LON
        nc.createVariable("lat", "f8", ("lat",))[:] = LAT
        for name, values in [
            ("drainage_basin_id", drainage),
            ("arrival_point_id", arrival),
            ("calving_point_id", arrival),
        ]:
            var = nc.createVariable(name, "i4", ("lat", "lon"))
            var.CDI_grid_type = "gaussian"
            var[:] = values
        nc.history = "cdo aexpr"
        nc.CDO = "Climate Data Operators"
    return path


def test_fix_runoff_maps_moves_arrival_and_calving_only(tmp_path: Path) -> None:
    maps = xr.load_dataset(maps_file(tmp_path / "runoff_maps.nc"))
    drainage = maps["drainage_basin_id"].values.copy()
    _, factors, area, _ = grid()
    factors[4, 14] = 1.0
    changes = fix_runoff_maps(maps, factors, area, max_error=0.5)
    assert [(c.variable, c.basin) for c in changes] == [("arrival_point_id", 1), ("calving_point_id", 1)]
    np.testing.assert_array_equal(maps["drainage_basin_id"].values, drainage)
    for name in ("arrival_point_id", "calving_point_id"):
        assert np.argwhere(maps[name].values == 1).tolist() == [[4, 14]]
    assert maps.attrs["history"].startswith("cdo aexpr\necefast: arrival and calving points")


def test_fix_runoff_maps_refuses_other_grid(tmp_path: Path) -> None:
    maps = xr.load_dataset(maps_file(tmp_path / "runoff_maps.nc"))
    with pytest.raises(ValueError, match="different grids"):
        fix_runoff_maps(maps, np.zeros((2, 2)), np.ones((2, 2)), max_error=0.5)


def test_write_runoff_maps_keeps_the_layout(tmp_path: Path) -> None:
    template = maps_file(tmp_path / "runoff_maps.nc")
    maps = xr.load_dataset(template)
    _, factors, area, _ = grid()
    factors[4, 14] = 1.0
    fix_runoff_maps(maps, factors, area, max_error=0.5)
    write_runoff_maps(str(template), maps, str(tmp_path / "new.nc"))
    with netCDF4.Dataset(template) as old, netCDF4.Dataset(tmp_path / "new.nc") as new:
        assert list(new.dimensions) == list(old.dimensions) == ["lon", "lat"]
        assert list(new.variables) == list(old.variables)
        assert new["arrival_point_id"].dtype == np.int32
        assert new["arrival_point_id"].CDI_grid_type == "gaussian"
        assert new.CDO == old.CDO
        assert new.history == maps.attrs["history"]
        np.testing.assert_array_equal(new["calving_point_id"][:], maps["calving_point_id"].values)
