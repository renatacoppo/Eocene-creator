"""Unit tests for the strait corrections of the present-day bathymetry."""

import logging

import numpy as np
import pytest
import xarray as xr

from ecefast.components.nemo.config.loader import get_corrections_for_grid
from ecefast.periods.present.bathymetry import close_region, open_region

pytestmark = pytest.mark.unit


def field() -> xr.Dataset:
    """A 3x3 bathymetry: land in the centre and in one corner, ocean elsewhere."""
    depth = np.array([[[100.0, 200.0, 300.0], [400.0, 0.0, 500.0], [600.0, 700.0, 0.0]]])
    return xr.Dataset({"bathy_metry": (("t", "y", "x"), depth)})


def test_open_region_sets_land_cell_to_mean_of_ocean_neighbours() -> None:
    opened = open_region(field(), "strait", {"strait": [(1, 1)]})
    assert opened["bathy_metry"][0, 1, 1] == pytest.approx(np.mean([100, 200, 300, 400, 500, 600, 700]))


def test_open_region_leaves_ocean_cell_unchanged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="ecefast"):
        opened = open_region(field(), "strait", {"strait": [(0, 1)]})
    assert opened["bathy_metry"][0, 0, 1] == 200.0
    assert "Cell (0, 1) in region 'strait' is already open (depth=200.0 m). Skipping." in caplog.text


def test_close_region_sets_cells_to_land() -> None:
    closed = close_region(field(), "lake", {"lake": [(slice(0, 2), 0)]})
    assert list(closed["bathy_metry"][0, :, 0].values) == [0.0, 0.0, 600.0]


def test_eorca1_to_paleorca2_corrections_of_data_version_v1() -> None:
    """The corrections that reproduce the present-day domain of PALEORCA2-definitive (data_version v1)."""
    open_regions, close_regions = get_corrections_for_grid("eORCA1", "PALEORCA2", "remapnn")
    assert open_regions["Philippines"] == [(111, 13), (112, 13)]
    assert {(103, 11), (104, 11), (105, 11)} <= set(open_regions["Indonesia"])
    assert (94, 16) not in open_regions["Indonesia"]
    assert close_regions["Thailand"] == [
        (slice(104, 117), 2),
        (slice(104, 108), 3),
        (slice(98, 107), 4),
        (slice(88, 91), 5),
    ]
