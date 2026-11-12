"""Tests for ``ecefast.tools.ecearth``: backend selection, the atos command line, the local error and the fake output.

Nothing here runs DOMAINcfg or touches an HPC: the atos test mocks ``subprocess.run``. The fake backend is fed
a namelist rendered from the real ``namelist_cfg.j2`` template, on a small synthetic grid.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pytest
import xarray as xr
import yaml

from ecefast.components.nemo.common.util import extract_maskutil, process_domain_cfg
from ecefast.components.nemo.domain import namelist as namelist_script
from ecefast.core.config import ConfigError, load_config
from ecefast.tools import ecearth
from ecefast.tools.ecearth import AtosBackend, FakeBackend, LocalBackend, get_backend

pytestmark = pytest.mark.unit

L31 = Path(ecearth.__file__).parents[1] / "components" / "nemo" / "grids" / "L31.txt"
NY, NX = 6, 8


def config_file(tmp_path: Path, tools: dict | None = None) -> Path:
    (tmp_path / "input").mkdir(exist_ok=True)
    (tmp_path / "herold").mkdir(exist_ok=True)
    raw = {
        "schema": 1,
        "paths": {
            "input": str(tmp_path / "input"),
            "output": str(tmp_path / "out"),
            "herold": str(tmp_path / "herold"),
        },
    }
    if tools is not None:
        raw["tools"] = tools
    path = tmp_path / "config.yml"
    path.write_text(yaml.safe_dump(raw))
    return path


def l31_levels() -> np.ndarray:
    """Depths of ``components/nemo/grids/L31.txt`` (CDO zaxis description)."""
    text = L31.read_text()
    return np.array(text.split("levels =")[1].split(), dtype=float)


# --- configuration and backend selection ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("backend", "cls"), [(None, LocalBackend), ("local", LocalBackend), ("atos", AtosBackend), ("fake", FakeBackend)]
)
def test_get_backend(tmp_path: Path, backend: str | None, cls: type) -> None:
    tools = None if backend is None else {"backend": backend}
    assert type(get_backend(load_config(config_file(tmp_path, tools)))) is cls


def test_atos_defaults_and_overrides(tmp_path: Path) -> None:
    config = load_config(config_file(tmp_path))
    assert (config.tools.atos.profile, config.tools.atos.oasis_lib_dir) == ("atos", None)
    tools = {"backend": "atos", "atos": {"profile": "atos", "oasis_lib_dir": "/path/to/oasis/lib"}}
    backend = get_backend(load_config(config_file(tmp_path, tools)))
    assert (backend.profile, backend.oasis_lib_dir) == ("atos", "/path/to/oasis/lib")


@pytest.mark.parametrize(
    ("tools", "key"),
    [
        ({"backend": "hpc"}, "tools.backend"),
        ({"atos": {"profile": 1}}, "tools.atos.profile"),
        ({"atos": {"oasis_lib_dir": 1}}, "tools.atos.oasis_lib_dir"),
        ({"atos": {"modules": []}}, "tools.atos"),
    ],
)
def test_bad_tools_values(tmp_path: Path, tools: dict, key: str) -> None:
    with pytest.raises(ConfigError, match=key):
        load_config(config_file(tmp_path, tools))


def test_unknown_hpc_profile() -> None:
    with pytest.raises(ValueError, match="'leonardo' not found.*atos"):
        AtosBackend(profile="leonardo")


def test_profile_modules_cli(capsys: pytest.CaptureFixture) -> None:
    """``python -m ecefast.tools.ecearth atos``, as run_domain_cfg.sh calls it."""
    ecearth.main(["atos"])
    printed = capsys.readouterr().out.split()
    assert printed == ecearth.hpc_modules("atos")
    assert printed[0] == "prgenv/intel"
    with pytest.raises(SystemExit, match="not found"):
        ecearth.main(["nowhere"])


# --- atos -----------------------------------------------------------------------------------------------------


def test_atos_command_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Same arguments as the pipeline (NEMO tools dir, then names); this Python and the profile in the env."""
    namelist_dir = tmp_path / "tools" / "DOMAINcfg"
    namelist_dir.mkdir(parents=True)
    calls = []

    def fake_run(cmd, check, env):
        calls.append((cmd, check, env))
        for name in cmd[3:]:
            (namelist_dir / f"domain_cfg_{name}.nc").touch()
            (namelist_dir / f"mesh_mask_{name}.nc").touch()

    monkeypatch.setattr(ecearth.subprocess, "run", fake_run)
    backend = AtosBackend(profile="atos", oasis_lib_dir="/path/to/oasis/lib")
    outputs = backend.domaincfg(namelist_dir, ["present_day", "eocene"])

    ((cmd, check, env),) = calls
    assert cmd == ["bash", str(ecearth.RUN_DOMAIN_CFG), str(tmp_path / "tools"), "present_day", "eocene"]
    assert ecearth.RUN_DOMAIN_CFG.is_file()
    assert check is True
    assert env["ECEFAST_PYTHON"] == sys.executable
    assert env["ECEFAST_HPC_PROFILE"] == "atos"
    assert env["ECEFAST_OASIS_LIB_DIR"] == "/path/to/oasis/lib"
    assert outputs["eocene"] == (namelist_dir / "domain_cfg_eocene.nc", namelist_dir / "mesh_mask_eocene.nc")


def test_atos_without_oasis_and_missing_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    namelist_dir = tmp_path / "DOMAINcfg"
    namelist_dir.mkdir()
    monkeypatch.delenv("ECEFAST_OASIS_LIB_DIR", raising=False)
    _, env = AtosBackend().command(namelist_dir, ["eocene"])
    assert "ECEFAST_OASIS_LIB_DIR" not in env
    monkeypatch.setattr(ecearth.subprocess, "run", lambda cmd, check, env: None)
    with pytest.raises(FileNotFoundError, match="domain_cfg_eocene.nc"):
        AtosBackend().domaincfg(namelist_dir, ["eocene"])


def test_atos_needs_domaincfg_folder(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="DOMAINcfg/ folder"):
        AtosBackend().command(tmp_path / "domain", ["eocene"])


def test_availability(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MODULESHOME", raising=False)
    assert not AtosBackend().available()
    monkeypatch.setenv("MODULESHOME", "/usr/share/modules")
    assert AtosBackend().available()
    assert not LocalBackend().available()
    assert FakeBackend().available()


# --- local ----------------------------------------------------------------------------------------------------


def test_local_backend_error(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match=r"'local' backend.*tools\.precomputed\.domain.*tools\.backend: atos"):
        LocalBackend().domaincfg(tmp_path, ["eocene"])


# --- fake -----------------------------------------------------------------------------------------------------


@pytest.fixture
def namelist_dir(tmp_path: Path) -> Path:
    """A namelist_cfg_test rendered by the pipeline's namelist script, with synthetic bathymetry and coordinates."""
    lon = np.linspace(0, 315, NX)[None].repeat(NY, axis=0)
    lat = np.linspace(-60, 60, NY)[:, None].repeat(NX, axis=1)
    coords = {}
    for point, shift in zip("tuvf", (0.0, 0.5, 0.0, 0.5)):
        coords[f"glam{point}"] = (("y", "x"), lon + shift)
        coords[f"gphi{point}"] = (("y", "x"), lat + shift)
        coords[f"e1{point}"] = (("y", "x"), np.full((NY, NX), 2.0e5))
        coords[f"e2{point}"] = (("y", "x"), np.full((NY, NX), 2.0e5))
    xr.Dataset(coords).to_netcdf(tmp_path / "coords_halo.nc")

    depth = np.full((NY, NX), 4000.0)
    depth[:, :2] = 0.0  # a land strip
    depth[2, 4] = 50.0  # shallow point: five T levels
    depth[3, 5] = np.nan  # missing value = land
    xr.Dataset(
        {"bathy_metry": (("time_counter", "y", "x"), depth[None])},
        coords={"lon": (("y", "x"), lon), "lat": (("y", "x"), lat)},
    ).to_netcdf(tmp_path / "bathy.nc")

    out = tmp_path / "DOMAINcfg"
    out.mkdir()
    args = argparse.Namespace(
        bathymetry=str(tmp_path / "bathy.nc"),
        coordinates=str(tmp_path / "coords_halo.nc"),
        output=str(out / "namelist_cfg_test"),
        configuration="PALEORCA2",
        levels=31,
        log_level="WARNING",
    )
    namelist_script.main(args)
    return out


def test_fake_output_passes_postprocessing(namelist_dir: Path, tmp_path: Path) -> None:
    outputs = FakeBackend().domaincfg(namelist_dir, ["test"])
    assert outputs == {"test": (namelist_dir / "domain_cfg_test.nc", namelist_dir / "mesh_mask_test.nc")}
    assert sorted(p.name for p in namelist_dir.iterdir()) == [
        "domain_cfg_test.nc",
        "mesh_mask_test.nc",
        "namelist_cfg_test",
    ]

    target = tmp_path / "domain" / "PALEORCA2" / "test"
    process_domain_cfg(str(namelist_dir), str(target), "test")
    extract_maskutil(str(namelist_dir), str(target), "test")

    with xr.open_dataset(target / "domain_cfg.nc") as domain:
        assert domain.sizes == {"time_counter": 1, "y": NY, "x": NX, "z": 31}
        assert domain["e3t_1d"].dims == ("time_counter", "z")
        assert domain["bottom_level"].dtype == np.int32
        assert domain.attrs["cn_cfg"] == "PALEORCA"
        np.testing.assert_allclose(domain["nav_lev"].values, l31_levels(), rtol=1e-6)
        bottom = domain["bottom_level"].values[0]
        assert (bottom[:, :2] == 0).all() and bottom[3, 5] == 0
        assert bottom[2, 4] == 5  # W levels 0, 10, 20, 30, 40 m are above 50 m
        assert bottom.max() <= 30
        np.testing.assert_array_equal(domain["top_level"].values[0], bottom > 0)
    with xr.open_dataset(target / "maskutil.nc") as masks:
        assert list(masks.data_vars) == ["tmaskutil", "umaskutil", "vmaskutil"]
        assert masks["tmaskutil"].dims == ("t", "y", "x")
        assert masks["tmaskutil"].dtype == np.int8
        np.testing.assert_array_equal(masks["tmaskutil"].values[0], bottom > 0)
        # a U point is ocean only if both T neighbours are
        assert masks["umaskutil"].values[0, 0, 1] == 0


def test_fake_vertical_grid_is_l31(namelist_dir: Path) -> None:
    """The fake vertical grid is DOMAINcfg's: depths of L31.txt, e3t_1d = differences of the W depths."""
    FakeBackend().domaincfg(namelist_dir, ["test"])
    with xr.open_dataset(namelist_dir / "mesh_mask_test.nc") as mesh:
        np.testing.assert_allclose(mesh["gdept_1d"].values[0], l31_levels(), rtol=1e-6)
        gdepw = mesh["gdepw_1d"].values[0]
        np.testing.assert_allclose(mesh["e3t_1d"].values[0][:-1], np.diff(gdepw))
        assert mesh["tmask"].dims == ("time_counter", "nav_lev", "y", "x")
        assert mesh["tmask"].dtype == np.int8


def test_fake_rejects_other_vertical_grids(namelist_dir: Path) -> None:
    path = namelist_dir / "namelist_cfg_test"
    path.write_text(path.read_text().replace("ldbletanh   =  .FALSE.", "ldbletanh   =  .TRUE."))
    with pytest.raises(NotImplementedError, match="analytic ORCA vertical grid"):
        FakeBackend().domaincfg(namelist_dir, ["test"])
