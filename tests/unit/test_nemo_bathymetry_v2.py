"""Unit tests of the bathymetry processors of data version v2: conservative mask and ocean-mean depth with CDO.

The source is a 1x1 degree elevation field (as Herold et al. 2014), the target a 2x2 degree grid given by its cell
bounds (as the ``coords_bounds_T.nc`` of the coordinates step), so every target cell holds 2x2 source cells.
"""

import re
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from ecefast.components.nemo.bathymetry import base
from ecefast.components.nemo.bathymetry.base import BathymetryProcessor
from ecefast.core.cdo import get_cdo
from ecefast.periods.eocene.bathymetry import BATHYMETRIES as EOCENE, EoceneBathymetry, EoceneBathymetryV2
from ecefast.periods.present.bathymetry import BATHYMETRIES as PRESENT, PresentDayBathymetry, PresentDayBathymetryV2

pytestmark = [pytest.mark.unit, pytest.mark.data_v2]

GRID = "TARGET"


def write_target_bounds(path: Path) -> None:
    """A global 2x2 degree grid as a curvilinear grid with cell corners, counterclockwise."""
    lat_edges, lon_edges = np.arange(-90.0, 91.0, 2.0), np.arange(0.0, 361.0, 2.0)
    lat = 0.5 * (lat_edges[:-1] + lat_edges[1:])
    lon = 0.5 * (lon_edges[:-1] + lon_edges[1:])
    lon2, lat2 = np.meshgrid(lon, lat)
    s, n = lat_edges[:-1][:, None, None], lat_edges[1:][:, None, None]
    w, e = lon_edges[:-1][None, :, None], lon_edges[1:][None, :, None]
    ny, nx = lat2.shape
    lat_bnds = np.concatenate([np.broadcast_to(v, (ny, nx, 1)) for v in (s, s, n, n)], axis=2)
    lon_bnds = np.concatenate([np.broadcast_to(v, (ny, nx, 1)) for v in (w, e, e, w)], axis=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    xr.Dataset(
        {
            "lat": (("y", "x"), lat2, {"standard_name": "latitude", "units": "degrees_north", "bounds": "lat_bnds"}),
            "lon": (("y", "x"), lon2, {"standard_name": "longitude", "units": "degrees_east", "bounds": "lon_bnds"}),
            "lat_bnds": (("y", "x", "bnds"), lat_bnds),
            "lon_bnds": (("y", "x", "bnds"), lon_bnds),
            # CDO reads the grid of a data variable, as the cell_area of coords_bounds_T.nc
            "cell_area": (("y", "x"), np.ones((ny, nx)), {"coordinates": "lat lon"}),
        }
    ).to_netcdf(path)


def source_elevation() -> np.ndarray:
    """Ocean at -1000 m between 60S and 60N, land elsewhere, with the cells the tests look at (1x1 degree)."""
    lat, lon = np.arange(-89.5, 90.0), np.arange(0.5, 360.0)
    elev = np.where(np.abs(lat)[:, None] < 60, -1000.0, 500.0) * np.ones((1, lon.size))

    def cells(lat0, lat1, lon0, lon1):
        return (slice(int(lat0 + 90), int(lat1 + 90)), slice(int(lon0), int(lon1)))

    elev[cells(0, 20, 100, 140)] = 500.0  # a continent
    elev[cells(0, 2, 98, 100)] = 500.0  # target cell (45, 49): 3 of 4 source cells land, fraction 0.25
    elev[cells(0, 1, 99, 100)] = -1000.0
    elev[cells(0, 2, 41, 42)] = 100.0  # target cell (45, 20): half ocean, split along longitude
    elev[cells(0, 1, 40, 41)] = -100.0
    elev[cells(1, 2, 40, 41)] = -300.0
    elev[cells(10, 12, 60, 62)] = -10.0  # target cell (50, 30): shallower than the minimum depth
    return elev


@pytest.fixture
def processed(tmp_path: Path) -> xr.DataArray:
    """The bathymetry made by EoceneBathymetryV2 from the synthetic source."""
    source = tmp_path / "herold.nc"
    xr.Dataset(
        {"paleotopo": (("lat", "lon"), source_elevation())},
        coords={
            "lat": ("lat", np.arange(-89.5, 90.0), {"units": "degrees_north", "standard_name": "latitude"}),
            "lon": ("lon", np.arange(0.5, 360.0), {"units": "degrees_east", "standard_name": "longitude"}),
        },
    ).to_netcdf(source)
    write_target_bounds(tmp_path / "coordinates" / GRID / "coords_bounds_T.nc")
    processor = EoceneBathymetryV2(
        {"name": "eocene", "source_file": str(source)},
        {"bathydir": str(tmp_path / "bathymetry"), "coordsdir": str(tmp_path / "coordinates")},
        {"target": GRID, "source": None, "staggering_target": "T"},
        {"minimum_depth": 30.0},
        get_cdo(),
    )
    processor.process()
    assert processor.output_file == processor.expected_output()
    assert Path(processor.output_file).name == f"HEROLD_bathy_metry_remapcon_to_{GRID}_T.nc"
    with xr.open_dataset(processor.output_file) as ds:
        assert "v2" in ds.attrs["history"]
        return ds["bathy_metry"].squeeze().load()


def test_half_ocean_cell_is_ocean_with_the_mean_depth_of_its_ocean_part(processed: xr.DataArray) -> None:
    """Ocean fraction exactly 0.5 is ocean; the depth is the area-weighted mean of the ocean source cells."""
    weights = np.cos(np.deg2rad([0.5, 1.5]))
    assert processed.values[45, 20] == pytest.approx(np.average([100.0, 300.0], weights=weights), rel=1e-6)


def test_cell_mostly_land_is_land(processed: xr.DataArray) -> None:
    assert processed.values[45, 49] == 0.0


def test_shallow_cell_gets_the_minimum_depth(processed: xr.DataArray) -> None:
    assert processed.values[50, 30] == 30.0


def test_open_ocean_and_land(processed: xr.DataArray) -> None:
    assert processed.values[60, 10] == pytest.approx(1000.0)
    assert processed.values[50, 60] == 0.0  # the continent
    assert (processed.values[-1] == 0).all()  # land at the north fold row


def test_rule_based_geography_needs_remapcon(tmp_path: Path) -> None:
    class Bilinear(EoceneBathymetryV2):
        remap_method = "remapbil"

    processor = Bilinear({"name": "x", "source_file": "s"}, {}, {"target": GRID}, {"minimum_depth": 30.0}, None)
    with pytest.raises(ValueError, match="needs remap_method remapcon"):
        processor._remap_rule_based("in.nc", str(tmp_path / "out.nc"))


def test_processors_of_each_data_version() -> None:
    assert PRESENT == {"v1": PresentDayBathymetry, "v2": PresentDayBathymetryV2}
    assert EOCENE == {"v1": EoceneBathymetry, "v2": EoceneBathymetryV2}
    for v1, v2 in (PRESENT.values(), EOCENE.values()):
        assert not v1.rule_based_geography and v2.rule_based_geography
        assert v2.remap_method == "remapcon" and v1.name == v2.name
    # v2 has no manual corrections
    assert PresentDayBathymetryV2.postprocess is BathymetryProcessor.postprocess
    assert set(PresentDayBathymetryV2.sills) == {"Gibraltar", "Bab-el-Mandeb"}
    assert EoceneBathymetryV2.sills == {}


def test_source_grid_description_and_prefix() -> None:
    """A processor with a source grid reads the source cell bounds of the coordinates step (v1 and v2)."""
    grids = {"target": "PALEORCA2", "source": "ORCA2", "staggering_source": "T", "staggering_target": "T"}
    processor = PresentDayBathymetryV2({"name": "present_day"}, {"coordsdir": "c", "bathydir": "b"}, grids, {}, None)
    assert processor.setgrid == "c/ORCA2/coords_bounds_T.nc"
    assert processor.expected_output() == "b/PALEORCA2/ORCA2_T_bathy_metry_remapcon_to_PALEORCA2_T.nc"
    grids["source"] = "eORCA1"
    processor = PresentDayBathymetry({"name": "present_day"}, {"coordsdir": "c", "bathydir": "b"}, grids, {}, None)
    assert processor.setgrid == "c/eORCA1/coords_bounds_T.nc"
    assert processor.output_prefix == "eORCA1_T"


def test_north_fold_matches_the_domaincfg_namelist() -> None:
    """The geography rules use the north fold that DOMAINcfg is given (jperio of namelist_cfg.j2)."""
    template = Path(base.__file__).parents[1] / "domain" / "namelist_cfg.j2"
    jperio = re.search(r"^\s*jperio\s*=\s*(\d+)", template.read_text(), re.MULTILINE)
    assert int(jperio.group(1)) == base.NORTH_FOLD
