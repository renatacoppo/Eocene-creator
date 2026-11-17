"""Unit tests of the OIFS file comparison (``ecefast.components.oifs.plots``).

``load_grib`` (CDO, tested in ``test_core_plotting.py``) is replaced by synthetic datasets: CDO cannot give
synthetic GRIB fields the ECMWF short names (``lsm``, ``z``) of the real files.
"""

import shutil
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from ecefast.components.oifs import plots
from ecefast.components.oifs.corners import reduced_grid_corners, write_corner_grid
from ecefast.components.oifs.plots import (
    STANDARD_GRAVITY,
    compare_file,
    compare_oifs,
    land_fraction_on,
    oifs_files,
)

pytestmark = pytest.mark.unit

LAT, LON = np.linspace(-60, 60, 4), np.linspace(0, 300, 6)


def surface(values, months: int = 0, **attrs) -> xr.DataArray:
    """A field on a 4 x 6 regular grid, with one time step or ``months`` of them."""
    values = np.broadcast_to(np.asarray(values, dtype=float), (LAT.size, LON.size))
    steps = months or 1
    data = np.stack([values + m for m in range(steps)])
    return xr.DataArray(data, dims=("time", "lat", "lon"), coords={"lat": LAT, "lon": LON}, attrs=attrs)


def fake_load_grib(files: dict[str, xr.Dataset]):
    def load(path: str, names: list[str] | None = None) -> xr.Dataset:
        ds = files[path]
        return ds[names] if names else ds

    return load


def test_oifs_files():
    files = oifs_files("/tree", "TL63L31", "19900101", "climate.v020")
    assert files == {
        "ICMGGECE4INIT": "/tree/initial_state/oifs/TL63L31/19900101/ICMGGECE4INIT",
        "ICMSHECE4INIT": "/tree/initial_state/oifs/TL63L31/19900101/ICMSHECE4INIT",
        "ICMCLECE4": "/tree/oifs/TL63L31/climate.v020/ICMCLECE4",
        "bare_soil_albedos": "/tree/oifs/TL63L31/climate.v020/bare_soil_albedos.grb",
    }


def test_compare_file_draws_only_what_differs(tmp_path: Path, monkeypatch):
    land = np.zeros((4, 6))
    land[1:3, 2:4] = 1.0
    reference = xr.Dataset(
        {
            "lsm": surface(land),
            "al": surface(0.1, units="(0 - 1)", long_name="Albedo"),
            "tvh": surface(3.0),
            "sd": xr.DataArray(np.zeros((1, 2, 4, 6)), dims=("time", "snow", "lat", "lon")),
            "old": surface(0.0),
        }
    )
    test = reference.drop_vars("old").assign(
        al=surface(0.3, units="(0 - 1)", long_name="Albedo"),
        tvh=surface(6.0),
        sd=xr.DataArray(np.ones((1, 2, 4, 6)), dims=("time", "snow", "lat", "lon")),
        new=surface(1.0),
    )
    monkeypatch.setattr(plots, "load_grib", fake_load_grib({"ref": reference, "test": test}))
    summary = compare_file("ICMGGECE4INIT", "ref", "test", str(tmp_path), ("reference", "eocene"))
    assert summary["changed"] == {"al": 0.2, "tvh": 3.0, "sd": 1.0}
    assert summary["unchanged"] == ["lsm"]
    assert summary["only_in_reference"] == ["old"] and summary["only_in_test"] == ["new"]
    drawn = sorted(p.name for p in (tmp_path / "ICMGGECE4INIT").iterdir())
    assert drawn == ["al.png", "sd.png", "tvh.png"]


def test_compare_file_monthly_fields(tmp_path: Path, monkeypatch):
    reference = xr.Dataset({"lai_lv": surface(1.0, months=12)})
    test = xr.Dataset({"lai_lv": surface(2.0, months=12)})
    monkeypatch.setattr(plots, "load_grib", fake_load_grib({"ref": reference, "test": test}))
    compare_file("ICMCLECE4", "ref", "test", str(tmp_path), ("reference", "eocene"))
    assert sorted(p.name for p in (tmp_path / "ICMCLECE4").iterdir()) == ["lai_lv_mean.png", "lai_lv_range.png"]


def test_compare_file_orography_from_geopotential(tmp_path: Path, monkeypatch):
    reference = xr.Dataset({"z": surface(0.0)})
    test = xr.Dataset({"z": surface(1000.0 * STANDARD_GRAVITY)})
    monkeypatch.setattr(plots, "load_grib", fake_load_grib({"ref": reference, "test": test}))
    summary = compare_file("ICMSHECE4INIT", "ref", "test", str(tmp_path), ("reference", "eocene"))
    assert summary["changed"] == {"orography": 1000.0}
    assert (tmp_path / "ICMSHECE4INIT" / "orography.png").is_file()


def test_compare_oifs_uses_the_land_sea_masks(tmp_path: Path, monkeypatch):
    land = np.zeros((4, 6))
    land[1:3, 2:4] = 1.0
    datasets = {}
    for tree, value in (("ref", 0.1), ("test", 0.2)):
        files = oifs_files(tree, "TL63L31", "19900101", "climate.v020")
        lsm = land if tree == "ref" else np.roll(land, 1, axis=1)
        datasets[files["ICMGGECE4INIT"]] = xr.Dataset({"lsm": surface(lsm), "al": surface(value)})
        datasets[files["ICMSHECE4INIT"]] = xr.Dataset({"z": surface(0.0)})
        datasets[files["ICMCLECE4"]] = xr.Dataset({"al": surface(value, months=12)})
        datasets[files["bare_soil_albedos"]] = xr.Dataset({"var117": surface(0.5)})
    monkeypatch.setattr(plots, "load_grib", fake_load_grib(datasets))
    reference = oifs_files("ref", "TL63L31", "19900101", "climate.v020")
    test = oifs_files("test", "TL63L31", "19900101", "climate.v020")
    summary = compare_oifs(reference, test, str(tmp_path), ("reference", "eocene"))
    assert list(summary) == ["ICMGGECE4INIT", "ICMSHECE4INIT", "ICMCLECE4", "bare_soil_albedos"]
    assert summary["ICMGGECE4INIT"]["changed"] == {"lsm": 1.0, "al": 0.1}
    assert summary["bare_soil_albedos"]["unchanged"] == ["var117"]


@pytest.mark.skipif(shutil.which("cdo") is None, reason="needs cdo")
def test_land_fraction_on_is_conservative(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Four latitude bands of 45 degrees, land (lsm > 0.5) in the two northern ones, onto the same bands."""
    lat, reduced_points = np.array([67.5, 22.5, -22.5, -67.5]), np.array([4, 8, 8, 4])
    lsm = np.repeat([1.0, 0.6, 0.4, 0.0], reduced_points)

    def corner_grid(icmgg, kind, spectral, outfile, workdir, masked_outfile):
        assert (icmgg, kind, spectral) == ("ICMGGECE4INIT", "L", 63)
        write_corner_grid(masked_outfile, *reduced_grid_corners(lat, reduced_points), mask=lsm)

    monkeypatch.setattr(plots, "create_corner_grid", corner_grid)
    fraction = land_fraction_on("ICMGGECE4INIT", "TL63L31", "r8x4", str(tmp_path))
    assert fraction.shape == (4, 8)
    np.testing.assert_allclose(fraction[:, 0], [0.0, 0.0, 1.0, 1.0], atol=1e-6)  # south to north


def test_land_fraction_on_rejects_an_unknown_grid(tmp_path: Path):
    with pytest.raises(ValueError, match="not an OIFS grid name"):
        land_fraction_on("ICMGGECE4INIT", "ORCA2", "r1x2", str(tmp_path))
