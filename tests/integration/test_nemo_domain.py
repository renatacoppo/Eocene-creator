"""Tests of the NEMO domain pipeline with the ``fake`` backend, ``ecefast nemo domain`` and the Eocene ``domain``
step building its domain.

The ``coordinates`` and ``bathymetry`` steps need real grids (``tests/local/test_nemo_domain_fake.py``); here they
are off, and their outputs (``coords_halo.nc``, the remapped bathymetry) are small synthetic files put where the
pipeline expects them. ``configure_domain``, ``domain_cfg`` (fake DOMAINcfg) and ``generate_mask`` run for real.
"""

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
from ecefast.core.config import NEMO_DOMAIN_STEPS, ConfigError, load_config
from ecefast.core.steps import PipelineError, run_pipeline
from ecefast.core.workspace import Context, Stage
from ecefast.paleo.eocene.bathymetry import EOCENE_PROCESSORS, EoceneBathymetry
from ecefast.paleo.eocene.nemo.domain import EoceneDomain
from ecefast.paleo.eocene.pipeline import PIPELINE
from ecefast.tools.ecearth import FakeBackend, LocalBackend
from synthetic import STEPS_WITHOUT_GRIDS, nemo_domain_section

pytestmark = pytest.mark.integration

ALL_PROCESSORS = {**PROCESSORS, **EOCENE_PROCESSORS}


def write_config(tmp_path: Path, backend: str = "fake", steps: dict | None = None, bathymetries=None) -> Path:
    """A configuration on a synthetic tree, with the synthetic pipeline inputs already in ``nemo.domain.output_dir``.

    The Eocene ``domain`` step builds its domain (``eocene.domain.build``) unless the machine is ``local``.
    """
    for name in ("input", "herold"):
        (tmp_path / name).mkdir(exist_ok=True)
    raw = {
        "schema": 2,
        "inputs": {"ece4_data": str(tmp_path / "input"), "herold": str(tmp_path / "herold")},
        "machine": {"name": backend},
        "nemo": {"domain": nemo_domain_section(tmp_path / "domain", tmp_path, steps, bathymetries)},
        "eocene": {
            "output_dir": str(tmp_path / "out"),
            "domain": {"from": "{nemo.domain.output_dir}/nemo/domain/{nemo.grid}/eocene", "build": backend != "local"},
        },
    }
    path = tmp_path / "config.yml"
    path.write_text(yaml.safe_dump(raw))
    return path


def workflow(config_file: Path, processors=None, backend=None, only=None) -> NEMOWorkflow:
    config = load_config(config_file)
    processors = ALL_PROCESSORS if processors is None else processors
    return NEMOWorkflow(config, processors, backend or FakeBackend(), only=only)


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


def test_source_grid_from_input_tree(tmp_path: Path) -> None:
    """The source grid of the present-day bathymetry is its domain_cfg.nc in the input tree."""
    config_file = write_config(tmp_path)
    wf = workflow(config_file)
    assert wf.paths["source_grid"] == str(tmp_path / "input" / "nemo" / "domain" / "eORCA1" / "domain_cfg.nc")


def test_mesh_mask_key_is_rejected(tmp_path: Path) -> None:
    """``nemo_domain.mesh_mask`` was removed; a config with it fails with a clear message."""
    config_file = write_config(tmp_path)
    raw = yaml.safe_load(config_file.read_text())
    raw["nemo"]["domain"]["mesh_mask"] = "/path/to/mesh_mask.nc"
    config_file.write_text(yaml.safe_dump(raw))
    with pytest.raises(ConfigError, match="unknown key.*mesh_mask"):
        load_config(config_file)


def test_local_backend_cannot_run_domaincfg(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="domain_cfg is on.*'machine.name: local'"):
        workflow(write_config(tmp_path, backend="local"), backend=LocalBackend())


# --- the pipeline with the fake backend ------------------------------------------------------------------------------


def test_fake_pipeline_end_to_end(tmp_path: Path) -> None:
    """``ecefast nemo domain`` writes the namelist and the fake DOMAINcfg output under ``work/``, and the
    post-processed domain under ``nemo/domain/<grid>/<name>/``, as in an EC-Earth input tree."""
    cli.main(["nemo", "domain", "-c", str(write_config(tmp_path)), "-l", "WARNING"])
    out = tmp_path / "domain"
    assert sorted(p.name for p in out.iterdir()) == ["nemo", "work"]
    assert sorted(p.name for p in (out / "work" / "domaincfg").iterdir()) == [
        "domain_cfg_eocene.nc",
        "mesh_mask_eocene.nc",
        "namelist_cfg_eocene",
    ]
    domain_dir = out / "nemo" / "domain" / "PALEORCA2" / "eocene"
    assert sorted(p.name for p in domain_dir.iterdir()) == ["domain_cfg.nc", "maskutil.nc"]
    with xr.open_dataset(domain_dir / "domain_cfg.nc") as domain:
        assert domain.sizes["z"] == 31
        assert domain["bottom_level"].values[0, 2, 4] == 5  # the 50 m point


def test_subbasins_for_every_bathymetry(tmp_path: Path) -> None:
    """``generate_subbasins`` writes ``subbasins.nc`` for every bathymetry (task 5.3): all masks for present day,
    the global mask only for the Eocene (``EoceneBathymetry.regional_subbasins`` is False)."""
    # both use the synthetic remapped bathymetry: only the processor class matters here
    bathy = str(
        tmp_path / "domain" / "work" / "bathymetry" / "PALEORCA2" / "HEROLD_bathy_metry_remapbil_to_PALEORCA2_T.nc"
    )
    bathymetries = [
        {"name": "present_day", "processor": "PresentDayBathymetry", "source_file": "x", "output_file": bathy},
        {"name": "eocene", "processor": "EoceneBathymetry", "source_file": "{inputs.herold}/topo.nc"},
    ]
    steps = {**STEPS_WITHOUT_GRIDS, "generate_subbasins": True}
    config = write_config(tmp_path, steps=steps, bathymetries=bathymetries)
    cli.main(["nemo", "domain", "-c", str(config), "-l", "WARNING"])
    expected = {"present_day": ["atlmsk", "pacmsk", "indmsk", "indpacmsk", "glomsk"], "eocene": ["glomsk"]}
    for name, variables in expected.items():
        domain_dir = tmp_path / "domain" / "nemo" / "domain" / "PALEORCA2" / name
        assert sorted(p.name for p in domain_dir.iterdir()) == ["domain_cfg.nc", "maskutil.nc", "subbasins.nc"]
        with xr.open_dataset(domain_dir / "subbasins.nc") as masks, xr.open_dataset(domain_dir / "maskutil.nc") as m:
            assert list(masks.data_vars) == variables, name
            np.testing.assert_array_equal(masks["glomsk"].values, m["tmaskutil"].values[0])


# --- input checks and dry run ---------------------------------------------------------------------------------------


def tree(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.name != "config.yml")


def test_dry_run_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    config = write_config(tmp_path)
    before = tree(tmp_path)
    cli.main(["nemo", "domain", "-c", str(config), "--dry-run"])
    assert tree(tmp_path) == before
    log = capsys.readouterr().err
    assert "Dry run" in log
    assert str(tmp_path / "domain" / "nemo" / "domain" / "PALEORCA2" / "eocene" / "maskutil.nc") in log


def test_plan_follows_enabled_steps(tmp_path: Path) -> None:
    """Only enabled steps, in run order; a step reads what an earlier one writes."""
    plan = workflow(write_config(tmp_path)).plan()
    assert [name for name, _, _ in plan] == ["configure_domain", "domain_cfg", "generate_mask"]
    (_, _, namelists), (_, domaincfg_reads, raw), (_, mask_reads, _) = plan
    assert namelists == [str(tmp_path / "domain" / "work" / "domaincfg" / "namelist_cfg_eocene")]
    assert domaincfg_reads == namelists
    assert mask_reads == raw


def test_missing_inputs_listed_at_once(tmp_path: Path) -> None:
    """With every step on, the inputs from outside the pipeline are checked first and all reported together;
    files written by earlier steps (coordinates, bathymetries, namelists, DOMAINcfg output) are not missing."""
    steps = {name: True for name in STEPS_WITHOUT_GRIDS}
    wf = workflow(write_config(tmp_path, steps=steps))
    with pytest.raises(PipelineError, match="3 input files are missing") as error:
        wf.check()
    message = str(error.value)
    assert "coordinates  needs  " + str(tmp_path / "coords_ori.nc") in message
    assert str(tmp_path / "input" / "nemo" / "domain" / "eORCA1" / "domain_cfg.nc") in message
    assert "bathymetry   needs  " + str(tmp_path / "herold" / "topo.nc") in message


def test_cli_missing_input_exits(tmp_path: Path) -> None:
    config = write_config(tmp_path, steps={**STEPS_WITHOUT_GRIDS, "coordinates": True})
    before = tree(tmp_path)
    for extra in ([], ["--dry-run"]):
        with pytest.raises(SystemExit) as exit_info:
            cli.main(["nemo", "domain", "-c", str(config), *extra])
        assert exit_info.value.code == 1
    assert tree(tmp_path) == before


def test_bathymetry_reads(tmp_path: Path) -> None:
    """Each processor declares its inputs; the present-day one adds its source grid and the optional plot files."""
    bathymetries = [
        {
            "name": "present_day",
            "processor": "PresentDayBathymetry",
            "source_file": "{inputs.ece4_data}/src.nc",
            "orca2_file": "{inputs.ece4_data}/orca2.nc",
        },
        {"name": "eocene", "processor": "EoceneBathymetry", "source_file": "{inputs.herold}/topo.nc"},
    ]
    wf = workflow(write_config(tmp_path, bathymetries=bathymetries))
    present_day, eocene = (wf._make_processor(cfg).reads() for cfg in wf.bathymetries)
    bounds = tmp_path / "domain" / "work" / "coordinates"
    assert eocene == [str(tmp_path / "herold" / "topo.nc"), str(bounds / "PALEORCA2" / "coords_bounds_T.nc")]
    assert present_day == [
        str(tmp_path / "input" / "src.nc"),
        str(bounds / "PALEORCA2" / "coords_bounds_T.nc"),
        str(bounds / "eORCA1" / "coords_bounds_T.nc"),
        str(tmp_path / "input" / "orca2.nc"),
    ]


def test_cli_without_nemo_domain_section(tmp_path: Path) -> None:
    config_file = write_config(tmp_path)
    raw = yaml.safe_load(config_file.read_text())
    del raw["nemo"]["domain"]
    config_file.write_text(yaml.safe_dump(raw))
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["nemo", "domain", "-c", str(config_file)])
    assert exit_info.value.code == 1


# --- CLI parsing -----------------------------------------------------------------------------------------------------


def test_cli_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(pipeline, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    cli.main(["nemo", "domain", "-c", "x.yml", "--bathymetry", "present_day", "eocene", "-l", "DEBUG"])
    expected = {"only": ["present_day", "eocene"], "log_level": "DEBUG", "dry_run": False}
    assert calls == [(("x.yml", ALL_PROCESSORS), expected)]
    calls.clear()
    cli.main(["nemo", "domain", "-c", "x.yml", "--dry-run"])
    assert calls == [(("x.yml", ALL_PROCESSORS), {"only": None, "log_level": "INFO", "dry_run": True})]


def test_help_lists_steps(capsys: pytest.CaptureFixture) -> None:
    """``-h`` lists the steps: the domain pipeline's (``nemo.domain.steps``) and the Eocene ones (``--steps``)."""
    assert tuple(pipeline.STEP_DESCRIPTIONS) == NEMO_DOMAIN_STEPS
    for argv, names in (
        (["nemo", "domain", "-h"], NEMO_DOMAIN_STEPS),
        (["eocene", "run", "-h"], [step.name for step in PIPELINE]),
    ):
        with pytest.raises(SystemExit) as exit_info:
            cli.main(argv)
        assert exit_info.value.code == 0
        lines = capsys.readouterr().out.splitlines()
        start = next(i for i, line in enumerate(lines) if line.startswith("steps, in run order"))
        assert [line.split()[0] for line in lines[start + 1 :]] == list(names)


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
    source = build / "domain" / "nemo" / "domain" / "PALEORCA2" / "eocene" / "domain_cfg.nc"
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
    built = tmp_path / "domain" / "nemo" / "domain" / "PALEORCA2" / "eocene"
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
    config.nemo.domain = None
    with pytest.raises(ConfigError, match="eocene.domain.build: true builds the Eocene domain.*'nemo.domain'"):
        EoceneDomain.from_context(Context(config))


def test_eocene_domain_build_needs_from_at_the_pipeline_output(tmp_path: Path) -> None:
    """With ``build: true``, ``eocene.domain.from`` must be where the pipeline writes the Eocene domain."""
    config = load_config(write_config(tmp_path))
    config.eocene.domain.from_ = str(tmp_path / "elsewhere")
    with pytest.raises(ConfigError, match="eocene.domain.from must be where the NEMO domain pipeline writes"):
        EoceneDomain.from_context(Context(config))


def test_eocene_domain_from_earlier_nemo_domain_run(tmp_path: Path) -> None:
    """``build: false``: the step installs the output of an earlier ``ecefast nemo domain``, found with the
    placeholder ``{nemo.domain.output_dir}``; it does not run the pipeline."""
    present_day_domain(tmp_path)
    config = write_config(tmp_path)
    cli.main(["nemo", "domain", "-c", str(config), "-l", "WARNING"])
    raw = yaml.safe_load(config.read_text())
    raw["eocene"]["domain"]["build"] = False
    config.write_text(yaml.safe_dump(raw))
    ctx = Context(load_config(config))
    step = EoceneDomain.from_context(ctx)
    assert step.workflow is None
    step.run()
    assert Path(ctx.expand(EoceneDomain.writes[0])).is_file()


def test_eocene_domain_step_needs_eocene_bathymetry(tmp_path: Path) -> None:
    bathymetries = [{"name": "present_day", "processor": "PresentDayBathymetry", "source_file": "x.nc"}]
    with pytest.raises(ConfigError, match="eocene"):
        EoceneDomain.from_context(Context(load_config(write_config(tmp_path, bathymetries=bathymetries))))


def test_eocene_dry_run_checks_domain_pipeline_inputs(tmp_path: Path) -> None:
    """With the fake backend the ``domain`` step runs the NEMO domain pipeline: a dry run of the Eocene pipeline
    checks its inputs too (here ``nemo.domain.coords_ori``) and writes nothing."""
    present_day_domain(tmp_path)
    config = write_config(tmp_path, steps={**STEPS_WITHOUT_GRIDS, "coordinates": True})
    for read in Stage.reads:  # the input folders that stage copies
        Path(Context(load_config(config)).expand(read)).mkdir(parents=True, exist_ok=True)
    before = tree(tmp_path)
    with pytest.raises(PipelineError, match="(?s)Step 'domain'.*coordinates  needs  .*coords_ori.nc"):
        run_pipeline([Stage, EoceneDomain], Context(load_config(config)), dry_run=True)
    assert tree(tmp_path) == before
