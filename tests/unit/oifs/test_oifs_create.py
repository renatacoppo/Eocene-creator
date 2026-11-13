"""Smoke tests for the ``create_*`` methods of ``EoceneOIFS`` on a tiny synthetic TL63 input tree.

The tree mirrors the layout of the EC-Earth4 files (ECE4-DATA-V3, TL63L31) with a few messages each, constant
fields on the reduced Gaussian N32 grid:

- ``ICMGGECE4INIT``: GRIB1 surface fields, the snow depth ``sd`` in GRIB2;
- ``ICMGGECE4INIUA``: GRIB2 humidity and cloud fields, plus ``o3`` (not modified);
- ``ICMSHECE4INIT``: GRIB2 spectral T63 fields;
- ``ICMCLECE4``: GRIB2 monthly albedo and LAI, two months;
- ``bare_soil_albedos.grb``: GRIB1 parameters 117-120 without a shortName.

Each test checks that the declared output is written, that the messages and their order are as expected, and the
values that follow directly from the synthetic input. The Herold fields and masks are prepared once per module.
"""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import xarray as xr
from oifs_helpers import (
    N32_POINTS,
    grib_data,
    grib_keys,
    make_grib,
    make_spectral_grib,
    needs_grib_tools,
    run,
    spectral_coefficients,
)

from ecefast.core.layout import oifs_initial_dir
from ecefast.periods.eocene.oifs.eoceneOIFS import EoceneOIFS

pytestmark = [pytest.mark.unit, needs_grib_tools]

RESOLUTION = "TL63L31"
STARTDATE = "19900101"  # grids.oifs.startdate default

ALBEDO = ["al", "aluvp", "aluvd", "alnip", "alnid"]
ALBEDO_DIRECT = ["aluvpi", "aluvpv", "aluvpg", "alnipi", "alnipv", "alnipg"]
ZEROED = ["sdfor", "anor", "chnk", "cl", "dl", "licd"]
# ICMGGECE4INIT: everything create_init touches, plus skt (untouched); GRIB1 except sd, as in ECE4-DATA-V3.
# The file starts with a GRIB2 message, as the real one: prepare_landsea_mask_present calls CDO without --eccodes,
# which reads a file starting with GRIB1 with its own GRIB1 decoder and then fails on the GRIB2 messages.
INIT_FIELDS = (
    [
        ("sd", 2.0, 2),
        ("lsm", 1.0, 1),
        ("lsmgrd", 9.0, 1),
        ("tvh", 1.0, 1),
        ("tvl", 1.0, 1),
        ("cvh", 0.5, 1),
        ("cvl", 0.5, 1),
    ]
    + [("sdor", 50.0, 1), ("slor", 0.01, 1), ("isor", 0.5, 1), ("slt", 3.0, 1), ("skt", 280.0, 1)]
    + [(v, 0.3, 1) for v in ALBEDO + ALBEDO_DIRECT]
    + [(v, 1.0, 1) for v in ZEROED]
)
INIUA_FIELDS = [(v, 1.0, 2) for v in ("q", "crwc", "cswc", "clwc", "ciwc", "cc", "o3")]
CLIMATE_VARS = ["al", "aluvp", "aluvd", "alnip", "alnid", "lai_lv", "lai_hv"]
BARE_SOIL = [(f"code{c}", 0.25, 1) for c in (117, 118, 119, 120)]

# Herold et al. (2014) fields on a 30-degree grid: land (topo 1000 m, biome 1) from 5W to 175E. The coasts are not
# on the meridians 0 and 180, the centres of F32 cells, where the remapped mask would be exactly 0.5 (a tie).
HEROLD_LAT = np.arange(-75.0, 90.0, 30.0)
HEROLD_LON = np.arange(10.0, 360.0, 30.0)
LAND_LON = HEROLD_LON < 180.0


def write_herold(herold: Path) -> None:
    coords = {
        "lat": ("lat", HEROLD_LAT, {"units": "degrees_north", "standard_name": "latitude"}),
        "lon": ("lon", HEROLD_LON, {"units": "degrees_east", "standard_name": "longitude"}),
    }
    shape = (HEROLD_LAT.size, HEROLD_LON.size)
    land = np.broadcast_to(LAND_LON, shape)
    topo = np.where(land, 1000.0, -3000.0)
    xr.Dataset({"topo": (("lat", "lon"), topo)}, coords=coords).to_netcdf(herold / "herold_etal_eocene_topo_1x1.nc")
    sd = np.where(land, 100.0, np.nan)  # NaN over the ocean, filled with 0 by prepare_herold
    xr.Dataset({"paleo_stddev_subgrid_topo": (("lat", "lon"), sd)}, coords=coords).to_netcdf(
        herold / "herold_etal_stddev_subgrid_etopo1_to_eocene_1x1.nc"
    )
    biome = np.where(land, 1.0, np.nan)  # tropical forest on land
    xr.Dataset({"eocene_biome_hp": (("lat", "lon"), biome)}, coords=coords).to_netcdf(
        herold / "herold_etal_eocene_biome_1x1.nc"
    )


def write_climate(path: Path) -> None:
    """Two months of the ICMCLECE4 fields, month by month, the second at step 744 h."""
    with open(path, "wb") as out:
        for step in (0, 744):
            month = make_grib(path.with_name("month"), [(v, 0.2, 2) for v in CLIMATE_VARS])
            run(["grib_set", "-s", f"step={step}", str(month), str(path.with_name("stepped"))])
            out.write(path.with_name("stepped").read_bytes())
    path.with_name("month").unlink()
    path.with_name("stepped").unlink()


@pytest.fixture(scope="module")
def oifs(tmp_path_factory: pytest.TempPathFactory) -> SimpleNamespace:
    """The step on the synthetic tree, with the Herold fields and both land-sea masks prepared once."""
    root = tmp_path_factory.mktemp("oifs")
    init = Path(oifs_initial_dir(str(root / "input"), RESOLUTION, STARTDATE))
    climate = root / "input" / "oifs" / RESOLUTION / "climate.v020"
    herold = root / "herold"
    for folder in (init, climate, herold):
        folder.mkdir(parents=True)
    make_grib(init / "ICMGGECE4INIT", INIT_FIELDS)
    make_grib(init / "ICMGGECE4INIUA", INIUA_FIELDS)
    make_spectral_grib(
        init / "ICMSHECE4INIT",
        [("vo", 0.0, 2), ("d", 0.0, 2), ("t", "topo", 2), ("lnsp", 11.5, 2), ("z", 0.0, 2)],
        gaussian=32,
    )
    write_climate(climate / "ICMCLECE4")
    make_grib(climate / "bare_soil_albedos.grb", BARE_SOIL)
    write_herold(herold)

    step = EoceneOIFS(
        idir=str(root / "input"),
        odir=str(root / "out"),
        herold=str(herold),
        startdate=STARTDATE,
        resolution=RESOLUTION,
        tmpdir=str(root / "tmp"),
    )
    herold_before = sorted(p.name for p in herold.iterdir())
    landsea = xr.open_dataset(step.prepare_herold(flag="landsea_mask"))
    orog = xr.open_dataset(step.prepare_herold(flag="orography"))
    sd_orog = xr.open_dataset(step.prepare_herold(flag="sd_orography"))
    lsm_present = step.prepare_landsea_mask_present()
    return SimpleNamespace(
        step=step,
        root=root,
        herold_before=herold_before,
        landsea=landsea,
        orog=orog,
        sd_orog=sd_orog,
        lsm_present=lsm_present,
    )


def output(oifs: SimpleNamespace, relative: str) -> Path:
    """An output file: ``<startdate>/<file>`` in the initial state, ``<climate_version>/<file>`` in oifs/<grid>."""
    if relative.startswith(STARTDATE + "/"):
        return Path(oifs_initial_dir(oifs.step.odir, RESOLUTION, relative))
    return Path(oifs.step.odir) / "oifs" / RESOLUTION / relative


def short_names(path: Path) -> list[str]:
    return [row[0] for row in grib_keys(path, "shortName")]


def test_prepare_landsea_mask_present(oifs: SimpleNamespace) -> None:
    """The present-day lsm of ICMGGECE4INIT on the regular Gaussian grid F32, without time."""
    lsm = oifs.lsm_present
    assert lsm.dims == ("lat", "lon")
    assert lsm.shape == (64, 128)
    np.testing.assert_array_equal(lsm.values, 1.0)


def test_create_iniua(oifs: SimpleNamespace) -> None:
    oifs.step.create_iniua()

    path = output(oifs, f"{STARTDATE}/ICMGGECE4INIUA")
    # o3 is not modified and stays first; the zeroed fields follow in their original order
    assert short_names(path) == ["o3", "q", "crwc", "cswc", "clwc", "ciwc", "cc"]
    assert {row[1:] for row in grib_keys(path, "shortName,edition,gridType,numberOfValues")} == {
        ("2", "reduced_gg", str(N32_POINTS))
    }
    for name in ("q", "crwc", "cswc", "clwc", "ciwc", "cc"):
        np.testing.assert_array_equal(grib_data(path, name), 0.0)
    np.testing.assert_array_equal(grib_data(path, "o3"), 1.0)


def test_create_bare_soil(oifs: SimpleNamespace) -> None:
    oifs.step.create_bare_soil(lsm_present=oifs.lsm_present, landsea=oifs.landsea)

    path = output(oifs, "climate.v020/bare_soil_albedos.grb")
    assert grib_keys(path, "paramId,edition,gridType") == [(str(c), "1", "reduced_gg") for c in (117, 118, 119, 120)]
    # the present-day zonal mean of a constant is the constant; the Eocene ocean (western hemisphere) gets 0
    ocean = grib_data(path, "", where="paramId=117") == 0.0
    assert 0.3 < ocean.mean() < 0.7
    for code in (117, 118, 119, 120):
        values = grib_data(path, "", where=f"paramId={code}")
        np.testing.assert_allclose(values[~ocean], 0.25, rtol=1e-6)
        np.testing.assert_array_equal(values[ocean], 0.0)


def test_create_climate(oifs: SimpleNamespace) -> None:
    oifs.step.create_climate(lsm_present=oifs.lsm_present, landsea=oifs.landsea)

    path = output(oifs, "climate.v020/ICMCLECE4")
    # every message is modified: the file is rewritten in CDO order (month by month), flattened to analyses
    assert grib_keys(path, "shortName,dataDate,step,edition") == [
        (v, date, "0", "2") for date in ("19900101", "19900201") for v in CLIMATE_VARS
    ]
    al = grib_data(path, "al")
    assert set(np.round(np.unique(al), 6)) == {0.05, 0.2}  # 0.05 over the Eocene ocean
    lai = grib_data(path, "lai_lv")
    assert set(np.round(np.unique(lai), 6)) == {0.0, 0.2}
    np.testing.assert_array_equal(np.isclose(al, 0.05), lai == 0.0)


def test_create_sh(oifs: SimpleNamespace) -> None:
    oifs.step.create_sh(orog=oifs.orog["orography"])

    path = output(oifs, f"{STARTDATE}/ICMSHECE4INIT")
    # truncated fields first (in file order), then the rest, then z (replaced last)
    assert grib_keys(path, "shortName,edition,gridType,J") == [
        (v, "2", "sh", "63") for v in ("vo", "d", "t", "lnsp", "z")
    ]
    # z = 9.81 * orography, orography >= 0: positive global mean
    assert spectral_coefficients(path, "z")[0] > 0
    # t, d, vo, lnsp truncated to T1 and padded back to T63 (truncate_grib_file): only the coefficients
    # (m, n) = (0,0), (0,1), (1,1) stay, at (real, imaginary) positions 0-1, 2-3 and 128-129 (after the 64 of m = 0)
    kept = [0, 1, 2, 3, 128, 129]
    t_before = spectral_coefficients(Path(oifs.step.idir_init) / "ICMSHECE4INIT", "t")
    t = spectral_coefficients(path, "t")
    assert t.size == t_before.size and np.count_nonzero(t_before) > 1000
    assert set(np.flatnonzero(t)) <= set(kept)
    np.testing.assert_allclose(t[kept], t_before[kept], rtol=1e-3)
    assert spectral_coefficients(path, "lnsp")[0] == pytest.approx(11.5, rel=1e-6)


def test_create_init(oifs: SimpleNamespace) -> None:
    oifs.step.create_init(
        lsm_present=oifs.lsm_present, landsea=oifs.landsea["landsea_mask"], sd_orog=oifs.sd_orog["sd_orography"]
    )

    path = output(oifs, f"{STARTDATE}/ICMGGECE4INIT")
    names = short_names(path)
    assert sorted(names) == sorted(name for name, _, _ in INIT_FIELDS)
    # each modified group is appended at the end, in the order of the steps of create_init
    groups = [["lsm"], ["lsmgrd"], ["tvh", "tvl", "cvh", "cvl"], ["sdor"], ["slor"], ["isor"], ["slt"]]
    groups += [ALBEDO + ALBEDO_DIRECT, ZEROED, ["sd"]]
    assert names == ["skt"] + [name for group in groups for name in group]
    editions = dict(grib_keys(path, "shortName,edition"))
    assert editions["sd"] == "2" and {editions[n] for n in names if n != "sd"} == {"1"}

    # lsm is the Herold mask remapped conservatively (remapcon): fractions on the coast
    lsm = grib_data(path, "lsm")
    land = lsm > 0.5
    assert lsm.min() == 0.0 and lsm.max() == 1.0 and 0.3 < land.mean() < 0.7
    np.testing.assert_array_equal(grib_data(path, "lsmgrd"), np.where(land, 3.0, 0.0))
    np.testing.assert_array_equal(grib_data(path, "tvh") == 6.0, land)  # tropical forest -> evergreen broadleaf
    np.testing.assert_array_equal(grib_data(path, "tvl"), 0.0)
    np.testing.assert_array_equal(grib_data(path, "isor"), 1.0)
    np.testing.assert_array_equal(grib_data(path, "slt"), 2.0)
    np.testing.assert_allclose(grib_data(path, "al")[~land], 0.05)
    np.testing.assert_allclose(grib_data(path, "aluvpi")[~land], 0.0)
    for name in ZEROED + ["sd"]:
        np.testing.assert_array_equal(grib_data(path, name), 0.0)
    np.testing.assert_array_equal(grib_data(path, "skt"), 280.0)
    # slope = a * sdor + b (subgrid_orog.compute_slope defaults): b over the ocean, where sdor = 0
    np.testing.assert_allclose(grib_data(path, "slor")[grib_data(path, "sdor") == 0.0], 2.476405e-04, rtol=1e-3)


def test_herold_folder_untouched(oifs: SimpleNamespace) -> None:
    assert sorted(p.name for p in Path(oifs.step.herold).iterdir()) == oifs.herold_before


@pytest.mark.parametrize("method", ["create_sic", "create_sst"])
@pytest.mark.xfail(strict=True, raises=AttributeError, reason="idir_amip is commented out in __init__ (dead code)")
def test_amip_methods_are_broken(oifs: SimpleNamespace, method: str) -> None:
    getattr(oifs.step, method)()
