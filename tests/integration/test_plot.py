"""Tests of ``ecefast <period> plot`` through ``main(argv)``, on synthetic trees.

The NEMO domains are the fake DOMAINcfg domains of ``tests/synthetic.py``. The OIFS GRIB files are empty
placeholders and ``load_grib`` is replaced by synthetic datasets: CDO cannot give synthetic GRIB fields the ECMWF
short names (``lsm``, ``z``) of the real files.
"""

import logging
from pathlib import Path

import numpy as np
import pytest
import xarray as xr
import yaml
from synthetic import READ_WRITERS, _lat_lon_1x1

from ecefast.cli.main import main
from ecefast.components.oifs import plots as oifs_plots
from ecefast.components.oifs.plots import oifs_files
from ecefast.periods.plots import SUMMARY_FILE

pytestmark = pytest.mark.integration

DOMAIN = READ_WRITERS["{input}/nemo/domain/{grids.nemo.name}/domain_cfg.nc"]


def write_config(root: Path) -> Path:
    """A configuration with both periods: input ``root/input``, outputs ``root/present`` and ``root/out``."""
    config = {
        "schema": 2,
        "machine": {"name": "fake", "tmpdir": str(root / "tmp")},
        "present": {"input": str(root / "input"), "output": str(root / "present")},
        "eocene": {
            "input": str(root / "input"),
            "herold": str(root / "herold"),
            "output": str(root / "out"),
            "nemo": {"domain": str(root / "precomputed"), "minimum_depth": 30},
        },
    }
    path = root / "config.yml"
    path.write_text(yaml.safe_dump(config))
    return path


def write_domain(tree: Path, grid: str = "PALEORCA2") -> None:
    path = tree / "nemo" / "domain" / grid / "domain_cfg.nc"
    path.parent.mkdir(parents=True, exist_ok=True)
    DOMAIN(path)


def write_herold(root: Path) -> None:
    """The source of the Eocene bathymetry: ocean everywhere except a land band at the equator."""
    topo = np.full((180, 360), -4000.0)
    topo[85:95] = 500.0
    path = root / "herold" / "herold_etal_stddev_subgrid_etopo1_to_eocene_1x1.nc"
    path.parent.mkdir(parents=True, exist_ok=True)
    _lat_lon_1x1("paleotopo", topo).to_netcdf(path)


def write_oifs(tree: Path, value: float) -> dict[str, xr.Dataset]:
    """Empty OIFS files in ``tree`` and the datasets the replaced ``load_grib`` returns for them."""
    lat, lon = np.linspace(-90, 90, 19), np.arange(0, 360, 10.0)
    land = np.zeros((lat.size, lon.size))
    land[8:11] = 1.0  # land at the equator

    def field(values, months=1):
        data = np.broadcast_to(np.asarray(values, dtype=float), (months, lat.size, lon.size))
        return xr.DataArray(data, dims=("time", "lat", "lon"), coords={"lat": lat, "lon": lon})

    files = oifs_files(str(tree), "TL63L31", "19900101", "climate.v020")
    contents = {
        "ICMGGECE4INIT": xr.Dataset({"lsm": field(land), "al": field(value)}),
        "ICMSHECE4INIT": xr.Dataset({"z": field(0.0)}),
        "ICMCLECE4": xr.Dataset({"al": field(value, months=12)}),
        "bare_soil_albedos": xr.Dataset({"var117": field(0.5)}),
    }
    for path in files.values():
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).touch()
    return {files[name]: ds for name, ds in contents.items()}


@pytest.fixture
def log(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    """Capture the ``ecefast`` logger (it does not propagate to the root logger) and restore it afterwards."""
    logger = logging.getLogger("ecefast")
    saved = logger.handlers[:], logger.level, logger.propagate
    logger.handlers[:] = [caplog.handler]
    yield caplog
    logger.handlers[:], logger.level, logger.propagate = saved


@pytest.fixture
def trees(tmp_path: Path, monkeypatch) -> Path:
    """Input and Eocene output trees with a domain and OIFS files, and the Herold bathymetry."""
    write_domain(tmp_path / "input")
    write_domain(tmp_path / "out")
    write_herold(tmp_path)
    datasets = write_oifs(tmp_path / "input", 0.1) | write_oifs(tmp_path / "out", 0.3)
    monkeypatch.setattr(
        oifs_plots, "load_grib", lambda path, names=None: datasets[path][names] if names else datasets[path]
    )
    write_config(tmp_path)
    return tmp_path


def test_eocene_plot_all_groups(trees: Path):
    out = trees / "plots"
    main(["eocene", "plot", "-c", str(trees / "config.yml"), "-o", str(out)])
    summary = yaml.safe_load((out / SUMMARY_FILE).read_text())
    assert summary["period"] == "eocene"
    assert summary["test"] == str(trees / "out") and summary["reference"] == str(trees / "input")
    nemo = summary["nemo"]
    assert nemo["basins"] == 1 and nemo["ocean_cells"] > 0
    assert list(nemo["comparisons"]) == ["reference PALEORCA2", "bathymetry source"]
    assert nemo["comparisons"]["reference PALEORCA2"]["ocean_only_in_test"] == 0
    assert set(summary["coupling"]) == {"land_in_both", "ocean_in_both", "ocean_only_in_test", "ocean_only_in_other"}
    assert summary["oifs"]["ICMGGECE4INIT"]["changed"] == {"al": 0.2}
    assert summary["oifs"]["ICMSHECE4INIT"]["unchanged"] == ["orography"]
    figures = sorted(str(p.relative_to(out)) for p in out.rglob("*.png"))
    assert figures == [
        "coupling/oifs_lsm_vs_nemo.png",
        "nemo/domain.png",
        "nemo/vs_reference_PALEORCA2.png",
        "nemo/vs_source.png",
        "oifs/ICMCLECE4/al_mean.png",
        "oifs/ICMCLECE4/al_range.png",
        "oifs/ICMGGECE4INIT/al.png",
    ]


def test_eocene_plot_with_another_reference(trees: Path):
    other = trees / "other"
    write_domain(other)
    main(["eocene", "plot", "-c", str(trees / "config.yml"), "-o", str(trees / "plots"), "--reference", str(other),
          "--only", "nemo"])  # fmt: skip
    summary = yaml.safe_load((trees / "plots" / SUMMARY_FILE).read_text())
    assert summary["reference"] == str(other)
    assert summary["nemo"]["comparisons"]["reference PALEORCA2"]["domain"].startswith(str(other))
    assert "oifs" not in summary and "coupling" not in summary


def test_present_plot_compares_every_domain_of_the_reference(trees: Path):
    write_domain(trees / "present")
    write_domain(trees / "input", "ORCA2")
    main(["present", "plot", "-c", str(trees / "config.yml"), "-o", str(trees / "plots"), "--only", "nemo"])
    summary = yaml.safe_load((trees / "plots" / SUMMARY_FILE).read_text())
    assert list(summary["nemo"]["comparisons"]) == ["reference ORCA2", "reference PALEORCA2"]
    assert (trees / "plots" / "nemo" / "vs_reference_ORCA2.png").is_file()


def test_plot_refuses_a_directory_in_an_output_tree(trees: Path, log):
    with pytest.raises(SystemExit):
        main(["eocene", "plot", "-c", str(trees / "config.yml"), "-o", str(trees / "out" / "plots")])
    assert "keep plots out of the EC-Earth trees" in log.text
    assert not (trees / "out" / "plots").exists()


def test_plot_lists_missing_inputs_before_drawing(trees: Path, log):
    (trees / "herold" / "herold_etal_stddev_subgrid_etopo1_to_eocene_1x1.nc").unlink()
    with pytest.raises(SystemExit):
        main(["eocene", "plot", "-c", str(trees / "config.yml"), "-o", str(trees / "plots")])
    assert "herold_etal_stddev_subgrid_etopo1_to_eocene_1x1.nc" in log.text
    assert not (trees / "plots").exists()


def test_plot_rejects_an_unknown_group(trees: Path, log):
    with pytest.raises(SystemExit):
        main(["eocene", "plot", "-c", str(trees / "config.yml"), "-o", str(trees / "plots"), "--only", "atmosphere"])
    assert "Unknown plot group(s): atmosphere" in log.text
