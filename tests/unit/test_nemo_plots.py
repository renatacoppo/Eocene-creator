"""Unit tests of the NEMO domain checks and maps (``ecefast.components.nemo.plots``)."""

import shutil
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from ecefast.components.nemo.bathymetry import BathymetryProcessor
from ecefast.components.nemo.bathymetry.geography import F_PIVOT, T_PIVOT
from ecefast.core.steps import PipelineError
from ecefast.components.nemo.plots import (
    OCEAN_FIELD,
    write_cell_bounds,
    BOTH_LAND,
    BOTH_OCEAN,
    ISOLATED,
    LAND,
    ONLY_OTHER,
    ONLY_TEST,
    PASSAGE,
    INLET,
    Domain,
    agreement_counts,
    compare_forcing,
    domain_classes,
    domain_summary,
    forcing_files,
    mask_agreement,
    minimum_depth_cells,
    fill_empty_cells,
    ocean_on,
    ocean_basins,
    ocean_inlets,
    plot_agreement,
    plot_domain,
    plot_same_grid,
    read_domain,
    write_source_ocean,
)

pytestmark = pytest.mark.unit

needs_cdo = pytest.mark.skipif(shutil.which("cdo") is None, reason="needs cdo")


def grid(ny: int, nx: int) -> tuple[np.ndarray, np.ndarray]:
    """Regular T-point coordinates ``(y, x)``: 10 degree cells."""
    lon, lat = np.meshgrid(5.0 + 10.0 * np.arange(nx), -85.0 + 10.0 * np.arange(ny))
    return lon, lat


def mask(rows: list[str]) -> np.ndarray:
    """Ocean mask from strings, ``o`` ocean, ``.`` land, first string the southern row."""
    return np.array([[c == "o" for c in row] for row in rows])


def domain(ocean: np.ndarray, depth: float = 1000.0, label: str = "test") -> Domain:
    lon, lat = grid(*ocean.shape)
    values = xr.DataArray(np.where(ocean, depth, np.nan), dims=("y", "x"))
    return Domain(label, "domain_cfg.nc", lon, lat, ocean, values, T_PIVOT)


def test_ocean_basins_numbered_by_size():
    ocean = mask(["oo.o.", "oo...", "....o", "....."])
    basins = ocean_basins(ocean, T_PIVOT)
    # largest first; basins of the same size in grid order
    np.testing.assert_array_equal(
        basins, [[0, 0, -1, 1, -1], [0, 0, -1, -1, -1], [-1, -1, -1, -1, 2], [-1, -1, -1, -1, -1]]
    )


def test_ocean_basins_across_the_east_west_period():
    ocean = mask(["o..o", "...."])
    assert set(ocean_basins(ocean, T_PIVOT)[ocean]) == {0}


@pytest.mark.parametrize(("jperio", "basins"), [(T_PIVOT, [0, 1]), (F_PIVOT, [0])])
def test_ocean_basins_across_the_north_fold(jperio: int, basins: list[int]):
    """Two cells of the top row: neighbours across an F-point fold ((i, top) and (nx - 1 - i, top)), not across a
    T-point fold, where (i, top) is the same cell as (-i, top)."""
    ocean = mask(["......", "......", ".o..o."])
    assert sorted(set(ocean_basins(ocean, jperio)[ocean])) == basins


def test_ocean_basins_across_the_t_point_fold_row():
    """T-point fold: the northern neighbour of (i, top) is (-i, top - 1)."""
    ocean = mask(["....", ".o..", "...o"])
    assert set(ocean_basins(ocean, T_PIVOT)[ocean]) == {0}


def test_ocean_basins_diagonal_cells_are_not_connected():
    ocean = mask(["o...", ".o.."])
    assert sorted(ocean_basins(ocean, T_PIVOT)[ocean]) == [0, 1]


def test_ocean_inlets_follow_a_dead_end_to_its_mouth():
    """An open sea in the south with a channel to the north, three cells long, and a notch of one cell."""
    ocean = mask(["oooooo", "oooooo", ".o..o.", ".o....", ".o...."])
    inlets = ocean_inlets(ocean, T_PIVOT)
    # the longest first; the cells of the open sea at the mouths are not part of them
    np.testing.assert_array_equal(inlets[:, 1], [-1, -1, 0, 0, 0])
    assert inlets[2, 4] == 1
    assert (inlets >= 0).sum() == 4


def test_ocean_inlets_leave_passages_and_wide_dead_ends():
    # a strait between two seas has ocean at both ends
    strait = mask(["oooo", "oooo", ".o..", "oooo", "oooo"])
    assert (ocean_inlets(strait, T_PIVOT) == -1).all()
    # a dead end two cells wide
    wide = mask(["oooooo", "oooooo", ".oo...", ".oo..."])
    assert (ocean_inlets(wide, T_PIVOT) == -1).all()


def test_ocean_inlets_across_the_east_west_period():
    """A cell of the first column with ocean in the last column is not a dead end."""
    ocean = mask(["o..o", "o..o", "o..o"])
    assert (ocean_inlets(ocean, T_PIVOT) == -1).all()


def test_ocean_inlets_count_the_copies_of_a_fold_cell_once():
    """A channel whose tip is on a T-point fold row, (1, top) and (3, top) the same cell: one inlet, on both
    copies."""
    ocean = mask(["oooo", "oooo", ".o..", ".o.o"])
    inlets = ocean_inlets(ocean, T_PIVOT)
    assert inlets[3, 1] == inlets[3, 3] == inlets[2, 1] == 0
    assert (inlets >= 0).sum() == 3


def test_domain_summary_describes_the_inlets_of_the_main_basin():
    ocean = mask(["oooooo", "oooooo", ".o..o.", ".o....", ".o....", "......", "...oo."])
    test = domain(ocean)
    classes, basins, inlets = domain_classes(test)
    assert classes[3, 1] == INLET and classes[2, 4] == INLET
    assert (classes[6, 3:5] == ISOLATED).all()  # a basin of two cells, not an inlet
    summary = domain_summary(test, basins, inlets, classes)
    assert summary["inlets"] == 2 and summary["inlet_cells"] == 4 and summary["one_cell_passages"] == 0
    assert summary["longest_inlets"] == [
        {"cells": 3, "j": 2, "i": 1, "lon": 15.0, "lat": -65.0},
        {"cells": 1, "j": 2, "i": 4, "lon": 45.0, "lat": -65.0},
    ]
    plot_domain(test, classes)


def test_domain_classes_and_summary():
    ocean = mask(["oooooo", "oooooo", "..o...", "oooooo", "oooooo", "......", "....o."])
    test = domain(ocean)
    classes, basins, inlets = domain_classes(test)
    assert classes[2, 2] == PASSAGE
    assert classes[6, 4] == ISOLATED
    assert classes[5, 0] == LAND
    summary = domain_summary(test, basins, inlets, classes)
    assert summary["inlets"] == 0 and summary["inlet_cells"] == 0 and summary["longest_inlets"] == []
    assert summary["ocean_cells"] == 26 and summary["basins"] == 2
    assert summary["one_cell_passages"] == 1
    assert summary["other_basins"] == [{"cells": 1, "j": 6, "i": 4, "lon": 45.0, "lat": -25.0}]
    plot_domain(test, classes)


def test_minimum_depth_cells():
    test = domain(mask(["oo..", "oooo"]))
    test.depth.values[0, 0] = 30.0
    test.depth.values[1, 3] = 30.0004  # the same depth, within the rounding tolerance
    minimum, shallowest = minimum_depth_cells(test)
    assert minimum == 30.0
    np.testing.assert_array_equal(shallowest, mask(["o...", "...o"]))
    classes, basins, inlets = domain_classes(test)
    summary = domain_summary(test, basins, inlets, classes)
    assert summary["minimum_depth"] == 30.0 and summary["minimum_depth_cells"] == 2
    assert len(plot_domain(test, classes).axes) == 6  # three maps and their colour bars


def test_minimum_depth_cells_without_ocean():
    minimum, shallowest = minimum_depth_cells(domain(mask(["....", "...."])))
    assert np.isnan(minimum) and not shallowest.any()


def test_mask_agreement_and_counts():
    test, other = np.array([True, True, False, False]), np.array([True, False, True, False])
    agreement = mask_agreement(test, other)
    np.testing.assert_array_equal(agreement, [BOTH_OCEAN, ONLY_TEST, ONLY_OTHER, BOTH_LAND])
    assert agreement_counts(agreement) == {
        "land_in_both": 1,
        "ocean_in_both": 1,
        "ocean_only_in_test": 1,
        "ocean_only_in_other": 1,
    }


def test_plot_same_grid():
    test = domain(mask(["oo..", "oooo"]), depth=1000.0)
    other = domain(mask(["o...", "oooo"]), depth=400.0, label="other")
    fig, counts = plot_same_grid(test, other)
    assert counts["ocean_only_in_test"] == 1 and counts["ocean_in_both"] == 5
    assert counts["largest_depth_difference"] == 600.0
    assert fig.get_suptitle() == "test vs other"
    with pytest.raises(ValueError, match="different grids"):
        plot_same_grid(test, domain(mask(["oo", "oo"])))


def write_nemo_grid(path: Path, depth: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """A domain file with T points on a 2 degree grid (3 x 4) and U, V, F points one degree to the east and north."""
    lon, lat = np.meshgrid(np.arange(0.0, 8.0, 2.0), np.arange(-2.0, 4.0, 2.0))
    shifts = {"t": (0.0, 0.0), "u": (1.0, 0.0), "v": (0.0, 1.0), "f": (1.0, 1.0)}
    fields = {f"glam{point}": (("y", "x"), lon + dx) for point, (dx, _) in shifts.items()}
    fields |= {f"gphi{point}": (("y", "x"), lat + dy) for point, (_, dy) in shifts.items()}
    fields |= {"e1t": (("y", "x"), np.ones(lon.shape)), "e2t": (("y", "x"), np.ones(lon.shape))}
    if depth is not None:
        fields["bathy_metry"] = (("y", "x"), depth)
    xr.Dataset(fields).to_netcdf(path)
    return lon, lat


def test_write_cell_bounds(tmp_path: Path):
    """The corners of a T cell are the F points around it."""
    path = tmp_path / "domain_cfg.nc"
    lon, _ = write_nemo_grid(path)
    write_cell_bounds(str(path), str(tmp_path / "cells.nc"))
    with xr.open_dataset(tmp_path / "cells.nc") as cells:
        np.testing.assert_array_equal(cells["lon"].values, lon)
        assert cells["lon_bnds"].shape == cells["lat_bnds"].shape == (3, 4, 4)
        assert cells["lon"].attrs["bounds"] == "lon_bnds"
        np.testing.assert_allclose(sorted(cells["lon_bnds"].values[1, 2]), [3.0, 3.0, 5.0, 5.0])
        np.testing.assert_allclose(sorted(cells["lat_bnds"].values[1, 2]), [-1.0, -1.0, 1.0, 1.0])
        assert OCEAN_FIELD not in cells
    assert [p.name for p in tmp_path.iterdir() if p.name != "domain_cfg.nc"] == ["cells.nc"]


def test_write_cell_bounds_with_the_ocean_mask(tmp_path: Path):
    path = tmp_path / "domain_cfg.nc"
    write_nemo_grid(path)
    ocean = mask(["oo..", "oooo", "...."])
    write_cell_bounds(str(path), str(tmp_path / "cells.nc"), ocean)
    with xr.open_dataset(tmp_path / "cells.nc") as cells:
        np.testing.assert_array_equal(cells[OCEAN_FIELD].values, ocean)
        assert cells[OCEAN_FIELD].dims == cells["lat"].dims


def test_fill_empty_cells_takes_the_nearest_cell():
    test = domain(mask(["oooo", "oooo"]))
    values = np.array([[0.0, 1.0, 1.0, 0.0], [np.nan, 1.0, 1.0, 0.25]])
    filled = fill_empty_cells(test, values)
    # at 75 S the cell to the east is nearer than the one to the south
    np.testing.assert_array_equal(filled, [[0.0, 1.0, 1.0, 0.0], [1.0, 1.0, 1.0, 0.25]])
    assert fill_empty_cells(test, filled) is filled


@needs_cdo
def test_ocean_on_remaps_conservatively(tmp_path: Path):
    """A 1 degree source onto the 2 degree cells: ocean where it covers at least half of a cell."""
    path = tmp_path / "domain_cfg.nc"
    lon, lat = write_nemo_grid(path)
    cells = tmp_path / "cells.nc"
    write_cell_bounds(str(path), str(cells))
    ocean = np.ones((180, 360), dtype="f4")
    ocean[:, 1] = 0.0  # 1 E to 2 E: a quarter of the cells centred on 2 E
    ocean[:, 3:5] = 0.0  # 3 E to 5 E: the cells centred on 4 E
    source = tmp_path / "source.nc"
    coords = {"lat": ("lat", np.arange(-89.5, 90.0), {"units": "degrees_north"})}
    coords["lon"] = ("lon", np.arange(0.5, 360.0), {"units": "degrees_east"})
    xr.Dataset({OCEAN_FIELD: (("lat", "lon"), ocean)}, coords=coords).to_netcdf(source)
    ocean = np.ones(lon.shape, dtype=bool)
    test = Domain("test", str(path), lon, lat, ocean, xr.DataArray(lon, dims=("y", "x")), T_PIVOT)
    remapped = ocean_on(test, str(source), str(cells))
    np.testing.assert_array_equal(remapped[1], [True, True, False, True])
    _, counts = plot_agreement(test, remapped, "other", "title")
    assert counts["ocean_only_in_test"] == int((~remapped).sum()) and counts["ocean_only_in_other"] == 0


def test_read_domain(tmp_path: Path):
    lon, lat = grid(2, 3)
    bottom = np.array([[0, 3, 5], [2, 0, 0]])
    path = tmp_path / "domain_cfg.nc"
    xr.Dataset(
        {
            "glamt": (("t", "y", "x"), lon[None]),
            "gphit": (("t", "y", "x"), lat[None]),
            "bottom_level": (("t", "y", "x"), bottom[None]),
            "bathy_metry": (("t", "y", "x"), np.where(bottom > 0, 100.0, 0.0)[None]),
            "jperio": ((), np.int32(F_PIVOT)),
        }
    ).to_netcdf(path)
    test = read_domain(str(path), "test")
    np.testing.assert_array_equal(test.ocean, bottom > 0)
    assert np.isnan(test.depth.values[0, 0]) and test.depth.values[0, 1] == 100.0
    assert test.depth.attrs["units"] == "m"
    assert test.jperio == F_PIVOT


@pytest.mark.parametrize("jperio", [None, 1])
def test_read_domain_needs_a_north_fold(tmp_path: Path, jperio: int | None):
    lon, lat = grid(2, 3)
    path = tmp_path / "domain_cfg.nc"
    fields = {"glamt": (("y", "x"), lon), "gphit": (("y", "x"), lat), "bathy_metry": (("y", "x"), lon)}
    if jperio is not None:
        fields["jperio"] = ((), np.int32(jperio))
    xr.Dataset(fields).to_netcdf(path)
    with pytest.raises(PipelineError, match=f"north fold jperio={jperio}, the plots handle 4"):
        read_domain(str(path), "test")


@pytest.mark.parametrize("name", ["Bathymetry", "bathymetry"])
def test_read_domain_other_bathymetry_names(tmp_path: Path, name: str):
    """A bathymetry file (``bathy_meter.nc`` style): other depth name, ``nav_lon``/``nav_lat``, no
    ``bottom_level``: ocean where the depth is above 0."""
    lon, lat = grid(2, 3)
    path = tmp_path / "bathy_meter.nc"
    xr.Dataset(
        {
            "nav_lon": (("y", "x"), lon),
            "nav_lat": (("y", "x"), lat),
            name: (("t", "y", "x"), np.array([[[0.0, 50.0, np.nan], [10.0, 0.0, 4000.0]]])),
            "jperio": ((), np.int32(T_PIVOT)),
        }
    ).to_netcdf(path)
    test = read_domain(str(path), "test")
    np.testing.assert_array_equal(test.ocean, [[False, True, False], [True, False, True]])
    np.testing.assert_array_equal(test.lon, lon)
    assert test.depth.values[1, 2] == 4000.0


def test_read_domain_without_bathymetry(tmp_path: Path):
    lon, lat = grid(2, 3)
    path = tmp_path / "domain_cfg.nc"
    xr.Dataset({"glamt": (("y", "x"), lon), "gphit": (("y", "x"), lat)}).to_netcdf(path)
    with pytest.raises(PipelineError, match="no bathymetry variable .looked for bathy_metry, Bathymetry"):
        read_domain(str(path), "test")


def test_forcing_files():
    assert forcing_files("/tree") == {
        "Goutorbe_ghflux": "/tree/nemo/initial/Goutorbe_ghflux.nc",
        "zdfiwm_forcing_r720x360": "/tree/nemo/initial/zdfiwm_forcing_r720x360.nc",
    }


def test_compare_forcing(tmp_path: Path):
    coords = {"lat": [-45.0, 45.0], "lon": [0.0, 120.0, 240.0]}
    trees = {}
    for tree, power in (("ref", 1e-3), ("test", 0.0)):
        trees[tree] = {}
        for name in ("Goutorbe_ghflux", "zdfiwm_forcing_r720x360"):
            path = tmp_path / tree / f"{name}.nc"
            path.parent.mkdir(exist_ok=True)
            values = (
                {"gh_flux": np.full((2, 3), 80.0)}
                if name == "Goutorbe_ghflux"
                else {"power_bot": np.full((2, 3), power)}
            )
            xr.Dataset({k: (("lat", "lon"), v) for k, v in values.items()}, coords=coords).to_netcdf(path)
            trees[tree][name] = str(path)
    summary = compare_forcing(trees["ref"], trees["test"], str(tmp_path / "plots"), ("reference", "eocene"))
    assert summary["Goutorbe_ghflux"]["unchanged"] == ["gh_flux"]
    assert summary["zdfiwm_forcing_r720x360"]["changed"] == {"power_bot": 0.001}
    assert [p.name for p in (tmp_path / "plots").rglob("*.png")] == ["power_bot.png"]


class Elevation(BathymetryProcessor):
    variable = "topo"
    mask_type = "negative_elevation"


class Depth(BathymetryProcessor):
    variable = "bathy_metry"
    mask_type = "positive_depth"


def test_write_source_ocean_regular_grid(tmp_path: Path):
    path = tmp_path / "topo.nc"
    xr.Dataset(
        {"topo": (("lat", "lon"), np.array([[-100.0, 50.0, 0.0], [-1.0, np.nan, 10.0]]))},
        coords={"lat": [-10.0, 10.0], "lon": [0.0, 120.0, 240.0]},
    ).to_netcdf(path)
    write_source_ocean(Elevation, str(path), str(tmp_path / "ocean.nc"))
    with xr.open_dataset(tmp_path / "ocean.nc") as ds:
        np.testing.assert_array_equal(ds[OCEAN_FIELD].values, [[1, 0, 0], [1, 0, 0]])
        np.testing.assert_array_equal(ds["lon"].values, [0.0, 120.0, 240.0])
        assert ds["lat"].attrs["units"] == "degrees_north" and ds["lon"].attrs["units"] == "degrees_east"


def test_write_source_ocean_nemo_domain(tmp_path: Path):
    path = tmp_path / "domain_cfg.nc"
    depth = np.array([[0.0, 5.0, 0.0, 0.0], [10.0, 0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 20.0]])
    lon, _ = write_nemo_grid(path, depth)
    write_source_ocean(Depth, str(path), str(tmp_path / "ocean.nc"))
    with xr.open_dataset(tmp_path / "ocean.nc") as ds:
        np.testing.assert_array_equal(ds[OCEAN_FIELD].values, depth > 0)
        np.testing.assert_array_equal(ds["lon"].values, lon)
        assert "lon_bnds" in ds and "lat_bnds" in ds
