"""Unit tests for the land-sea mask plot of the present-day bathymetry."""

import logging
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from ecefast.periods.present.bathymetry import PLOT_FILE, PresentDayBathymetry

pytestmark = pytest.mark.unit


def write_domain(path: Path, variable: str) -> None:
    path.parent.mkdir(parents=True)
    depth = np.array([[[0.0, 50.0], [100.0, 0.0]]])
    xr.Dataset({variable: (("t", "y", "x"), depth)}).to_netcdf(path)


def test_plot_leaves_out_a_domain_without_bathy_metry(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """ORCA1 in ECE4-DATA 4.1.11 names its bathymetry bathy_meter: left out of the plot, with a warning."""
    domains = tmp_path / "input" / "nemo" / "domain"
    write_domain(domains / "ORCA1" / "domain_cfg.nc", "bathy_meter")
    write_domain(domains / "ORCA2" / "domain_cfg.nc", "bathy_metry")
    grids = {"source": "eORCA1", "target": "PALEORCA2"}
    paths = {"input": str(tmp_path / "input"), "coordsdir": str(tmp_path / "coordinates")}
    processor = PresentDayBathymetry({"name": "present_day"}, paths, grids, {}, None)
    field = xr.Dataset({"bathy_metry": (("t", "y", "x"), np.array([[[0.0, 30.0], [40.0, 0.0]]]))})
    with caplog.at_level(logging.WARNING, logger="ecefast"):
        processor._plot(field, str(tmp_path))
    assert (tmp_path / PLOT_FILE).exists()
    assert "ORCA1/domain_cfg.nc has no bathy_metry, left out of the plot" in caplog.text
    assert "ORCA2" not in caplog.text
