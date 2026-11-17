"""Unit tests of the NEMO domain checks and maps (``ecefast.components.nemo.plots``)."""

from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from ecefast.components.nemo.bathymetry import BathymetryProcessor
from ecefast.core.steps import PipelineError
from ecefast.components.nemo.plots import (
    BOTH_LAND,
    BOTH_OCEAN,
    ISOLATED,
    LAND,
    ONLY_OTHER,
    ONLY_TEST,
    PASSAGE,
    Domain,
    agreement_counts,
    compare_forcing,
    domain_classes,
    domain_summary,
    forcing_files,
    mask_agreement,
    ocean_at,
    ocean_basins,
    one_cell_passages,
    plot_agreement,
    plot_domain,
    plot_same_grid,
    read_domain,
    source_ocean,
)

pytestmark = pytest.mark.unit


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
    return Domain(label, "domain_cfg.nc", lon, lat, ocean, values)


def test_ocean_basins_numbered_by_size():
    ocean = mask(["oo.o.", "oo...", "....o"])
    lon, lat = grid(*ocean.shape)
    basins = ocean_basins(ocean, lon, lat)
    # largest first; basins of the same size in grid order
    np.testing.assert_array_equal(basins, [[0, 0, -1, 1, -1], [0, 0, -1, -1, -1], [-1, -1, -1, -1, 2]])


def test_ocean_basins_across_the_east_west_period():
    ocean = mask(["o..o", "...."])
    lon, lat = grid(*ocean.shape)
    assert set(ocean_basins(ocean, lon, lat)[ocean]) == {0}


def test_ocean_basins_join_cells_with_the_same_coordinates():
    """A T-point north fold duplicates rows: equal coordinates are the same cell."""
    ocean = mask(["o...", "....", "...o"])
    lon, lat = grid(*ocean.shape)
    lon[2, 3], lat[2, 3] = lon[0, 0], lat[0, 0]
    assert set(ocean_basins(ocean, lon, lat)[ocean]) == {0}


def test_ocean_basins_diagonal_cells_are_not_connected():
    ocean = mask(["o...", ".o.."])
    lon, lat = grid(*ocean.shape)
    assert sorted(ocean_basins(ocean, lon, lat)[ocean]) == [0, 1]


def test_one_cell_passages():
    """The rows beyond the first and the last are land, as the closed boundaries of a NEMO domain."""
    ocean = mask(["ooooo", "ooooo", "..o..", "ooooo", "ooooo"])
    passages = one_cell_passages(ocean)
    assert passages.sum() == 1 and passages[2, 2]
    # a north-south strait one cell high: land above and below
    ocean = mask(["....", "oooo", "...."])
    assert one_cell_passages(ocean).sum() == 4


def test_domain_classes_and_summary():
    ocean = mask(["oooooo", "oooooo", "..o...", "oooooo", "oooooo", "......", "....o."])
    test = domain(ocean)
    classes, basins = domain_classes(test)
    assert classes[2, 2] == PASSAGE
    assert classes[6, 4] == ISOLATED
    assert classes[5, 0] == LAND
    summary = domain_summary(test, basins, classes)
    assert summary["ocean_cells"] == 26 and summary["basins"] == 2
    assert summary["one_cell_passages"] == 1
    assert summary["other_basins"] == [{"cells": 1, "j": 6, "i": 4, "lon": 45.0, "lat": -25.0}]
    plot_domain(test, classes)


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


def test_ocean_at_and_plot_agreement():
    test = domain(mask(["oo..", "oooo"]))
    # another grid, shifted by one degree: ocean in the southern row only
    lon, lat = grid(2, 4)
    other = ocean_at(test, lon + 1.0, lat + 1.0, np.array([[True] * 4, [False] * 4]))
    np.testing.assert_array_equal(other, [[True] * 4, [False] * 4])
    _, counts = plot_agreement(test, other, "other", "title")
    assert counts == {"land_in_both": 0, "ocean_in_both": 2, "ocean_only_in_test": 4, "ocean_only_in_other": 2}


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
        }
    ).to_netcdf(path)
    test = read_domain(str(path), "test")
    np.testing.assert_array_equal(test.ocean, bottom > 0)
    assert np.isnan(test.depth.values[0, 0]) and test.depth.values[0, 1] == 100.0
    assert test.depth.attrs["units"] == "m"


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


def test_source_ocean_regular_grid(tmp_path: Path):
    path = tmp_path / "topo.nc"
    xr.Dataset(
        {"topo": (("lat", "lon"), np.array([[-100.0, 50.0, 0.0], [-1.0, np.nan, 10.0]]))},
        coords={"lat": [-10.0, 10.0], "lon": [0.0, 120.0, 240.0]},
    ).to_netcdf(path)
    lon, lat, ocean = source_ocean(Elevation, str(path))
    np.testing.assert_array_equal(ocean, [[True, False, False], [True, False, False]])
    np.testing.assert_array_equal(lon[0], [0.0, 120.0, 240.0])
    np.testing.assert_array_equal(lat[:, 0], [-10.0, 10.0])


def test_source_ocean_nemo_domain(tmp_path: Path):
    lon2d, lat2d = grid(2, 2)
    path = tmp_path / "domain_cfg.nc"
    xr.Dataset(
        {
            "glamt": (("t", "y", "x"), lon2d[None]),
            "gphit": (("t", "y", "x"), lat2d[None]),
            "bathy_metry": (("t", "y", "x"), np.array([[[0.0, 5.0], [10.0, 0.0]]])),
        }
    ).to_netcdf(path)
    lon, lat, ocean = source_ocean(Depth, str(path))
    np.testing.assert_array_equal(ocean, [[False, True], [True, False]])
    np.testing.assert_array_equal(lon, lon2d)
