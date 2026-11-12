"""Tests of the NEMO domain pipeline with the ``fake`` backend, ``ecefast nemo domain`` and the Eocene ``domain``
step building its domain.

The ``coordinates`` and ``bathymetry`` steps need real grids (``tests/local/test_nemo_domain_fake.py``); here they
are off, and their outputs (``coords_halo.nc``, the remapped bathymetry) are small synthetic files put where the
pipeline expects them. ``configure_domain``, ``domain_cfg`` (fake DOMAINcfg) and ``generate_mask`` run for real.
"""

import logging
import shutil
from pathlib import Path

import numpy as np
import pytest
import xarray as xr
import yaml

from ecefast.cli import main as cli
from ecefast.components.nemo.bathymetry import PROCESSORS, PresentDayBathymetry
from ecefast.components.nemo.domain import pipeline
from ecefast.components.nemo.domain.pipeline import NEMOWorkflow
from ecefast.core.config import ConfigError, load_config
from ecefast.core.workspace import Context
from ecefast.paleo.eocene.bathymetry import EOCENE_PROCESSORS, EoceneBathymetry
from ecefast.paleo.eocene.nemo.domain import EoceneDomain
from ecefast.tools.ecearth import FakeBackend, LocalBackend
from synthetic import write_domain_inputs

pytestmark = pytest.mark.integration

ALL_PROCESSORS = {**PROCESSORS, **EOCENE_PROCESSORS}
STEPS_WITHOUT_GRIDS = {
    "coordinates": False,
    "bathymetry": False,
    "configure_domain": True,
    "domain_cfg": True,
    "generate_mask": True,
    "generate_subbasins": False,
}


@pytest.fixture(autouse=True)
def restore_logger():
    """``ecefast nemo domain`` sets up the ``ecefast`` logger; restore its handlers for the other tests."""
    logger = logging.getLogger("ecefast")
    handlers, level, propagate = logger.handlers[:], logger.level, logger.propagate
    yield
    logger.handlers[:], logger.level, logger.propagate = handlers, level, propagate


def write_config(tmp_path: Path, backend: str = "fake", steps: dict | None = None, bathymetries=None) -> Path:
    """A configuration on a synthetic tree, with the synthetic pipeline inputs already in ``nemo_domain.output_dir``."""
    for name in ("input", "herold"):
        (tmp_path / name).mkdir(exist_ok=True)
    domain_out = tmp_path / "domain"
    write_domain_inputs(
        domain_out / "coordinates" / "PALEORCA2" / "coords_halo.nc",
        domain_out / "bathymetry" / "PALEORCA2" / "HEROLD_bathy_metry_remapbil_to_PALEORCA2_T.nc",
    )
    if bathymetries is None:
        bathymetries = [{"name": "eocene", "processor": "EoceneBathymetry", "source_file": "{herold}/topo.nc"}]
    raw = {
        "schema": 1,
        "paths": {
            "input": str(tmp_path / "input"),
            "output": str(tmp_path / "out"),
            "herold": str(tmp_path / "herold"),
        },
        "tools": {"backend": backend},
        "nemo_domain": {
            "output_dir": str(domain_out),
            "coords_ori": str(tmp_path / "coords_ori.nc"),
            "mesh_mask": str(tmp_path / "mesh_mask.nc"),
            "grids": {"target": "PALEORCA2", "source": "eORCA1", "staggering_source": "T", "staggering_target": "T"},
            "parameters": {"minimum_depth": 30},
            "steps": STEPS_WITHOUT_GRIDS if steps is None else steps,
            "bathymetries": bathymetries,
        },
    }
    path = tmp_path / "config.yml"
    path.write_text(yaml.safe_dump(raw))
    return path


def workflow(config_file: Path, processors=None, backend=None, only=None) -> NEMOWorkflow:
    config = load_config(config_file)
    processors = ALL_PROCESSORS if processors is None else processors
    return NEMOWorkflow(config.nemo_domain, config.paths, processors, backend or FakeBackend(), only=only)


# --- bathymetry registry --------------------------------------------------------------------------------------------


def test_registry_merge() -> None:
    assert PROCESSORS == {"PresentDayBathymetry": PresentDayBathymetry}
    assert EOCENE_PROCESSORS == {"EoceneBathymetry": EoceneBathymetry}
    assert ALL_PROCESSORS == {"PresentDayBathymetry": PresentDayBathymetry, "EoceneBathymetry": EoceneBathymetry}


def test_unknown_processor_lists_known_names(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="Unknown processor 'EoceneBathymetry'.*known: PresentDayBathymetry"):
        workflow(write_config(tmp_path), processors=PROCESSORS)


def test_unknown_bathymetry_name(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="Unknown or disabled bathymetry name.*cretaceous.*enabled: eocene"):
        workflow(write_config(tmp_path), only=["cretaceous"])


def test_local_backend_cannot_run_domaincfg(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="domain_cfg is on.*'local' backend"):
        workflow(write_config(tmp_path, backend="local"), backend=LocalBackend())


# --- the pipeline with the fake backend ------------------------------------------------------------------------------


def test_fake_pipeline_end_to_end(tmp_path: Path) -> None:
    """``ecefast nemo domain`` writes the namelist, the fake DOMAINcfg output and the post-processed domain."""
    cli.main(["nemo", "domain", "-c", str(write_config(tmp_path)), "-l", "WARNING"])
    out = tmp_path / "domain" / "domain"
    assert sorted(p.name for p in out.iterdir()) == [
        "PALEORCA2",
        "domain_cfg_eocene.nc",
        "mesh_mask_eocene.nc",
        "namelist_cfg_eocene",
    ]
    domain_dir = out / "PALEORCA2" / "eocene"
    assert sorted(p.name for p in domain_dir.iterdir()) == ["domain_cfg.nc", "maskutil.nc"]
    with xr.open_dataset(domain_dir / "domain_cfg.nc") as domain:
        assert domain.sizes["z"] == 31
        assert domain["bottom_level"].values[0, 2, 4] == 5  # the 50 m point


def test_subbasins_for_every_bathymetry(tmp_path: Path) -> None:
    """``generate_subbasins`` writes ``subbasins.nc`` for a non-present-day bathymetry too (task 5.3)."""
    steps = {**STEPS_WITHOUT_GRIDS, "generate_subbasins": True}
    cli.main(["nemo", "domain", "-c", str(write_config(tmp_path, steps=steps)), "-l", "WARNING"])
    domain_dir = tmp_path / "domain" / "domain" / "PALEORCA2" / "eocene"
    assert sorted(p.name for p in domain_dir.iterdir()) == ["domain_cfg.nc", "maskutil.nc", "subbasins.nc"]
    with xr.open_dataset(domain_dir / "subbasins.nc") as masks, xr.open_dataset(domain_dir / "maskutil.nc") as util:
        assert list(masks.data_vars) == ["atlmsk", "pacmsk", "indmsk", "indpacmsk", "glomsk"]
        np.testing.assert_array_equal(masks["glomsk"].values, util["tmaskutil"].values[0])


def test_cli_without_nemo_domain_section(tmp_path: Path) -> None:
    config_file = write_config(tmp_path)
    raw = yaml.safe_load(config_file.read_text())
    del raw["nemo_domain"]
    config_file.write_text(yaml.safe_dump(raw))
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["nemo", "domain", "-c", str(config_file)])
    assert exit_info.value.code == 1


# --- CLI parsing -----------------------------------------------------------------------------------------------------


def test_cli_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(pipeline, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    cli.main(["nemo", "domain", "-c", "x.yml", "--bathymetry", "present_day", "eocene", "-l", "DEBUG"])
    assert calls == [(("x.yml", ALL_PROCESSORS), {"only": ["present_day", "eocene"], "log_level": "DEBUG"})]
    calls.clear()
    cli.main(["nemo", "domain", "-c", "x.yml"])
    assert calls == [(("x.yml", ALL_PROCESSORS), {"only": None, "log_level": "INFO"})]


@pytest.mark.parametrize(
    "argv", [["nemo"], ["nemo", "domain"], ["nemo-domain", "-c", "x.yml"], ["nemo", "domain", "--only", "eocene"]]
)
def test_cli_rejects(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(argv)
    assert exit_info.value.code == 2


# --- the Eocene domain step with the fake backend --------------------------------------------------------------------


def present_day_domain(tmp_path: Path, nav_lev: np.ndarray | None = None) -> Path:
    """Present-day domain in the input tree: the fake domain itself, or one with other levels."""
    build = tmp_path / "build"
    build.mkdir()
    cli.main(["nemo", "domain", "-c", str(write_config(build)), "-l", "WARNING"])
    source = build / "domain" / "domain" / "PALEORCA2" / "eocene" / "domain_cfg.nc"
    target = tmp_path / "input" / "nemo" / "domain" / "PALEORCA2" / "domain_cfg.nc"
    target.parent.mkdir(parents=True)
    if nav_lev is None:
        shutil.copy(source, target)
    else:
        with xr.open_dataset(source) as domain:
            domain.load().assign(nav_lev=("z", nav_lev)).to_netcdf(target)
    return target


def test_eocene_domain_step_builds_with_fake(tmp_path: Path) -> None:
    present_day_domain(tmp_path)
    ctx = Context(load_config(write_config(tmp_path)))
    step = EoceneDomain.from_context(ctx)
    assert step.workflow is not None and step.workflow.backend.name == "fake"
    step.run()
    built = tmp_path / "domain" / "domain" / "PALEORCA2" / "eocene"
    for template in EoceneDomain.writes:
        installed = Path(ctx.expand(template))
        assert installed.read_bytes() == (built / installed.name).read_bytes()


def test_eocene_domain_step_checks_vertical_grid(tmp_path: Path) -> None:
    present_day_domain(tmp_path, nav_lev=np.arange(31, dtype="float32"))
    step = EoceneDomain.from_context(Context(load_config(write_config(tmp_path))))
    with pytest.raises(ValueError, match="Different: nav_lev"):
        step.run()


def test_eocene_domain_step_needs_mask_step(tmp_path: Path) -> None:
    present_day_domain(tmp_path)
    steps = {**STEPS_WITHOUT_GRIDS, "generate_mask": False}
    step = EoceneDomain.from_context(Context(load_config(write_config(tmp_path, steps=steps))))
    with pytest.raises(FileNotFoundError, match="did not write domain_cfg.nc, maskutil.nc.*generate_mask"):
        step.run()


def test_eocene_domain_step_needs_nemo_domain(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path))
    config.nemo_domain = None
    with pytest.raises(ConfigError, match="tools.backend: fake builds the Eocene domain.*nemo_domain"):
        EoceneDomain.from_context(Context(config))


def test_eocene_domain_step_needs_eocene_bathymetry(tmp_path: Path) -> None:
    bathymetries = [{"name": "present_day", "processor": "PresentDayBathymetry", "source_file": "x.nc"}]
    with pytest.raises(ConfigError, match="eocene"):
        EoceneDomain.from_context(Context(load_config(write_config(tmp_path, bathymetries=bathymetries))))
