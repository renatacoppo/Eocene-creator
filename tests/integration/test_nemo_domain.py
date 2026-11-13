"""Tests of the NEMO domain pipeline with the ``fake`` backend: ``ecefast nemo run`` (present-day domain) and the
Eocene ``domain`` step building its domain (``eocene.nemo.domain: build``).

The ``coordinates`` and ``bathymetry`` steps need real grids (``tests/local/test_nemo_domain_fake.py``); here they
are off, and their outputs (``coords_halo.nc``, the remapped bathymetry) are small synthetic files put where the
pipeline expects them, in ``<machine.tmpdir>/<period>/nemo``. ``configure_domain``, ``domain_cfg`` (fake DOMAINcfg)
and ``generate_mask`` run for real.
"""

from pathlib import Path

import numpy as np
import pytest
import xarray as xr
import yaml

from ecefast.cli import main as cli
from ecefast.components.nemo.config import get_corrections_for_grid
from ecefast.components.nemo.domain import pipeline as domain_pipeline
from ecefast.components.nemo.domain.pipeline import NEMOWorkflow
from ecefast.core import workspace
from ecefast.core.config import NEMO_DOMAIN_STEPS, ConfigError, load_config, override_steps
from ecefast.core.runner import component_steps
from ecefast.core.steps import PipelineError, run_pipeline
from ecefast.core.workspace import Context, Stage
from ecefast.periods.eocene import pipeline as eocene_pipeline
from ecefast.periods.eocene.bathymetry import EoceneBathymetry
from ecefast.periods.eocene.nemo.domain import EoceneDomain
from ecefast.periods.present import pipeline as present_pipeline
from ecefast.periods.present.bathymetry import PresentDayBathymetry
from ecefast.tools.ecearth import FakeBackend, LocalBackend
from synthetic import STEPS_WITHOUT_GRIDS, _domain, write_domain_work

pytestmark = pytest.mark.integration


def write_config(tmp_path: Path, machine: str = "fake", steps: dict | None = None) -> Path:
    """A configuration on a synthetic tree, with the synthetic pipeline inputs already in the tmpdir of both
    periods; ``steps`` are the domain steps of both periods. The Eocene domain is built unless the machine is
    ``local``."""
    for name in ("input", "herold"):
        (tmp_path / name).mkdir(exist_ok=True)
    for period in ("present", "eocene"):
        write_domain_work(tmp_path / "tmp" / period / "nemo", period)
    steps = STEPS_WITHOUT_GRIDS if steps is None else steps
    raw = {
        "schema": 2,
        "machine": {"name": machine, "tmpdir": str(tmp_path / "tmp")},
        "grids": {"nemo": {"coords_ori": str(tmp_path / "coords_ori.nc")}},
        "present": {
            "input": str(tmp_path / "input"),
            "output": str(tmp_path / "present"),
            "nemo": {"minimum_depth": 30, "steps": steps},
        },
        "eocene": {
            "input": "{present.input}",
            "herold": str(tmp_path / "herold"),
            "output": str(tmp_path / "out"),
            "nemo": {
                "domain": "build" if machine != "local" else str(tmp_path / "d"),
                "minimum_depth": 30,
                "steps": steps,
            },
        },
    }
    path = tmp_path / "config.yml"
    path.write_text(yaml.safe_dump(raw))
    return path


def workflow(config_file: Path, period: str = "present", backend=None) -> NEMOWorkflow:
    ctx = Context(load_config(config_file), period)
    processor = PresentDayBathymetry if period == "present" else EoceneBathymetry
    domain_dir = str(Path(ctx.section.output) / "nemo" / "domain" / "PALEORCA2")
    return NEMOWorkflow.from_context(ctx, processor, domain_dir, backend or FakeBackend())


# --- one bathymetry per period ---------------------------------------------------------------------------------------


def test_present_source_grid_from_input_tree(tmp_path: Path) -> None:
    """The present-day bathymetry and its source grid are the domain_cfg.nc of present.nemo.source_grid."""
    wf = workflow(write_config(tmp_path))
    source = str(tmp_path / "input" / "nemo" / "domain" / "eORCA1" / "domain_cfg.nc")
    assert wf.paths["source_grid"] == source
    assert wf.bathymetry == {"name": "present_day", "source_file": source}
    assert wf.paths["workdir"] == str(tmp_path / "tmp" / "present" / "nemo")


def test_eocene_bathymetry_has_no_source_grid(tmp_path: Path) -> None:
    wf = workflow(write_config(tmp_path), period="eocene")
    assert wf.grids["source"] is None and wf.paths["source_grid"] == ""
    assert wf.bathymetry["source_file"] == str(
        tmp_path / "herold" / "herold_etal_stddev_subgrid_etopo1_to_eocene_1x1.nc"
    )


def test_strait_corrections_by_source_grid() -> None:
    open_regions, close_regions = get_corrections_for_grid("eORCA1", "PALEORCA2", "remapnn")
    assert open_regions and close_regions
    with pytest.raises(ConfigError, match="No strait corrections defined for 'eORCA025_to_PALEORCA2_remapnn'"):
        get_corrections_for_grid("eORCA025", "PALEORCA2", "remapnn")


def test_local_backend_cannot_run_domaincfg(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="domain_cfg step is on.*'machine.name: local'"):
        workflow(write_config(tmp_path, machine="local"), backend=LocalBackend())


def test_coords_ori_needed(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path))
    config.grids.nemo.coords_ori = None
    with pytest.raises(ConfigError, match="needs 'grids.nemo.coords_ori'"):
        NEMOWorkflow.from_context(Context(config, "present"), PresentDayBathymetry, str(tmp_path), FakeBackend())


# --- ecefast nemo run (present) with the fake backend ------------------------------------------------------------------


def test_present_nemo_end_to_end(tmp_path: Path) -> None:
    """The namelist and the fake DOMAINcfg output go to the tmpdir, the post-processed domain to
    ``present.output/nemo/domain/<grid>/``, as in an EC-Earth input tree."""
    cli.main(["nemo", "run", "-c", str(write_config(tmp_path)), "-l", "WARNING"])
    work = tmp_path / "tmp" / "present" / "nemo" / "domaincfg"
    assert sorted(p.name for p in work.iterdir()) == [
        "domain_cfg_present_day.nc",
        "mesh_mask_present_day.nc",
        "namelist_cfg_present_day",
    ]
    domain_dir = tmp_path / "present" / "nemo" / "domain" / "PALEORCA2"
    assert sorted(p.name for p in domain_dir.iterdir()) == ["domain_cfg.nc", "maskutil.nc"]
    assert sorted(p.name for p in (tmp_path / "present").iterdir()) == ["nemo", "provenance.yml"]
    with xr.open_dataset(domain_dir / "domain_cfg.nc") as domain:
        assert domain.sizes["z"] == 31
        assert domain["bottom_level"].values[0, 2, 4] == 5  # the 50 m point


def test_present_nemo_overwrite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """A second run refuses the existing domain without --overwrite; with it, warns, pauses, replaces."""
    monkeypatch.setattr(workspace, "OVERWRITE_PAUSE", 0)
    config = str(write_config(tmp_path))
    cli.main(["nemo", "run", "-c", config, "-l", "WARNING"])
    capsys.readouterr()
    with pytest.raises(SystemExit):
        cli.main(["nemo", "run", "-c", config])
    log = capsys.readouterr().err
    assert "exist already" in log and "--overwrite" in log
    cli.main(["nemo", "run", "-c", config, "--overwrite"])
    assert "Step 'nemo' (--overwrite) replaces" in capsys.readouterr().err


def test_subbasins_per_period(tmp_path: Path) -> None:
    """``generate_subbasins``: all masks for the present day, the global mask only for the Eocene
    (``EoceneBathymetry.regional_subbasins`` is False)."""
    steps = {**STEPS_WITHOUT_GRIDS, "generate_subbasins": True}
    config = write_config(tmp_path, steps=steps)
    workflows = {"present": workflow(config), "eocene": workflow(config, period="eocene")}
    expected = {"present": ["atlmsk", "pacmsk", "indmsk", "indpacmsk", "glomsk"], "eocene": ["glomsk"]}
    for period, wf in workflows.items():
        wf.run()
        with (
            xr.open_dataset(Path(wf.domain_dir) / "subbasins.nc") as masks,
            xr.open_dataset(Path(wf.domain_dir) / "maskutil.nc") as mask,
        ):
            assert list(masks.data_vars) == expected[period], period
            np.testing.assert_array_equal(masks["glomsk"].values, mask["tmaskutil"].values[0])


# --- input checks and dry run ---------------------------------------------------------------------------------------


def tree(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.name != "config.yml")


def test_dry_run_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    config = write_config(tmp_path)
    before = tree(tmp_path)
    cli.main(["nemo", "run", "-c", str(config), "--dry-run"])
    assert tree(tmp_path) == before
    log = capsys.readouterr().err
    assert "Dry run" in log
    assert str(tmp_path / "present" / "nemo" / "domain" / "PALEORCA2" / "maskutil.nc") in log


def test_plan_follows_enabled_steps(tmp_path: Path) -> None:
    """Only enabled steps, in run order; a step reads what an earlier one writes."""
    plan = workflow(write_config(tmp_path)).plan()
    assert [name for name, _, _ in plan] == ["configure_domain", "domain_cfg", "generate_mask"]
    (_, _, namelists), (_, domaincfg_reads, raw), (_, mask_reads, _) = plan
    assert namelists == [str(tmp_path / "tmp" / "present" / "nemo" / "domaincfg" / "namelist_cfg_present_day")]
    assert domaincfg_reads == namelists
    assert mask_reads == raw


def test_missing_inputs_listed_at_once(tmp_path: Path) -> None:
    """With every step on, the inputs from outside the pipeline are checked first and all reported together;
    files written by earlier steps (coordinates, bathymetry, namelist, DOMAINcfg output) are not missing."""
    steps = {name: True for name in STEPS_WITHOUT_GRIDS}
    wf = workflow(write_config(tmp_path, steps=steps))
    with pytest.raises(PipelineError, match="3 input files are missing") as error:
        wf.check()
    message = str(error.value)
    source = str(tmp_path / "input" / "nemo" / "domain" / "eORCA1" / "domain_cfg.nc")
    assert "coordinates  needs  " + str(tmp_path / "coords_ori.nc") in message
    assert "coordinates  needs  " + source in message  # its grid
    assert "bathymetry   needs  " + source in message  # its bathymetry


def test_cli_missing_input_exits(tmp_path: Path) -> None:
    config = write_config(tmp_path, steps={**STEPS_WITHOUT_GRIDS, "coordinates": True})
    before = tree(tmp_path)
    for extra in ([], ["--dry-run"]):
        with pytest.raises(SystemExit) as exit_info:
            cli.main(["nemo", "run", "-c", str(config), *extra])
        assert exit_info.value.code == 1
    assert tree(tmp_path) == before


def test_bathymetry_reads(tmp_path: Path) -> None:
    """Each processor declares its inputs: the present-day one adds its source grid bounds and every domain of the
    input tree (the comparison plot)."""
    config = write_config(tmp_path)
    for grid in ("ORCA2", "eORCA1"):
        (tmp_path / "input" / "nemo" / "domain" / grid).mkdir(parents=True)
        (tmp_path / "input" / "nemo" / "domain" / grid / "domain_cfg.nc").write_text("x")
    bounds = tmp_path / "tmp" / "{}" / "nemo" / "coordinates"
    eocene = workflow(config, period="eocene")._make_processor().reads()
    assert eocene == [
        str(tmp_path / "herold" / "herold_etal_stddev_subgrid_etopo1_to_eocene_1x1.nc"),
        str(bounds).format("eocene") + "/PALEORCA2/coords_bounds_T.nc",
    ]
    domains = tmp_path / "input" / "nemo" / "domain"
    present = workflow(config)._make_processor().reads()
    assert present == [
        str(domains / "eORCA1" / "domain_cfg.nc"),
        str(bounds).format("present") + "/PALEORCA2/coords_bounds_T.nc",
        str(bounds).format("present") + "/eORCA1/coords_bounds_T.nc",
        str(domains / "ORCA2" / "domain_cfg.nc"),
    ]


def test_cli_without_present_nemo_section(tmp_path: Path) -> None:
    config_file = write_config(tmp_path)
    raw = yaml.safe_load(config_file.read_text())
    del raw["present"]["nemo"]
    config_file.write_text(yaml.safe_dump(raw))
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["nemo", "run", "-c", str(config_file)])
    assert exit_info.value.code == 1


# --- CLI parsing -----------------------------------------------------------------------------------------------------


def test_cli_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    for module in (present_pipeline, eocene_pipeline):
        monkeypatch.setattr(module, "run", lambda *args, m=module.PERIOD, **kwargs: calls.append((m, args, kwargs)))
    common = {"dry_run": False, "overwrite": False}
    cli.main(["nemo", "run", "-c", "x.yml", "--nemo", "coordinates,bathymetry", "-l", "DEBUG"])
    cli.main(["nemo", "run", "-c", "x.yml", "--period", "eocene", "--dry-run", "--overwrite"])
    cli.main(["rnfm", "run", "-c", "x.yml", "--period", "eocene"])
    cli.main(["eocene", "run", "-c", "x.yml", "--steps", "stage,domain", "--nemo", "coordinates"])
    cli.main(["present", "run", "-c", "x.yml"])
    assert calls == [
        ("present", ("x.yml",), common | {"component": "nemo", "substeps": {"nemo": ["coordinates", "bathymetry"]}}),
        ("eocene", ("x.yml",), {"dry_run": True, "overwrite": True, "component": "nemo", "substeps": {}}),
        ("eocene", ("x.yml",), common | {"component": "rnfm", "substeps": {}}),
        ("eocene", ("x.yml",), common | {"select": ["stage", "domain"], "substeps": {"nemo": ["coordinates"]}}),
        ("present", ("x.yml",), common | {"select": None, "substeps": {}}),
    ]


def test_help_lists_steps(capsys: pytest.CaptureFixture) -> None:
    """``-h`` lists the pipeline steps (``--steps``) and the domain steps (``--nemo``)."""
    assert tuple(domain_pipeline.STEP_DESCRIPTIONS) == NEMO_DOMAIN_STEPS
    for argv, title, names in (
        (["nemo", "run", "-h"], "--nemo steps", NEMO_DOMAIN_STEPS),
        (["eocene", "run", "-h"], "steps, in run order", [step.name for step in eocene_pipeline.PIPELINE]),
        (["present", "run", "-h"], "steps, in run order", ["oifs", "nemo"]),
    ):
        with pytest.raises(SystemExit) as exit_info:
            cli.main(argv)
        assert exit_info.value.code == 0
        lines = capsys.readouterr().out.splitlines()
        start = next(i for i, line in enumerate(lines) if line.startswith(title))
        assert [line.split()[0] for line in lines[start + 1 : start + 1 + len(names)]] == list(names)


@pytest.mark.parametrize(
    "argv",
    [
        ["nemo"],
        ["nemo", "domain", "-c", "x.yml"],
        ["nemo-domain", "-c", "x.yml"],
        ["oifs", "data", "-c", "x.yml"],
        ["nemo", "run", "-c", "x.yml", "--bathymetry", "eocene"],
        ["nemo", "run", "-c", "x.yml", "--period", "miocene"],
        ["oasis", "run", "-c", "x.yml", "--oasis", "a"],
    ],
)
def test_cli_rejects(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(argv)
    assert exit_info.value.code == 2


def test_component_steps() -> None:
    assert component_steps(eocene_pipeline.PIPELINE, "nemo") == ["domain", "nemo"]
    assert component_steps(eocene_pipeline.PIPELINE, "nemo", select=["nemo"]) == ["nemo"]
    assert component_steps(present_pipeline.PIPELINE, "oifs") == ["oifs"]
    with pytest.raises(PipelineError, match="no 'oasis' step"):
        component_steps(present_pipeline.PIPELINE, "oasis")


# --- the Eocene domain step with the fake backend --------------------------------------------------------------------


def present_day_domain(tmp_path: Path, nav_lev: np.ndarray | None = None) -> Path:
    """Present-day domain in the input tree: the fake domain of the synthetic grid, or one with other levels."""
    target = tmp_path / "input" / "nemo" / "domain" / "PALEORCA2" / "domain_cfg.nc"
    target.parent.mkdir(parents=True)
    _domain(target)
    if nav_lev is not None:
        with xr.open_dataset(target) as domain:
            changed = domain.load().assign(nav_lev=("z", nav_lev))
        changed.to_netcdf(target)
    return target


def test_eocene_domain_step_builds_with_fake(tmp_path: Path) -> None:
    present_day_domain(tmp_path)
    ctx = Context(load_config(write_config(tmp_path)), "eocene")
    step = EoceneDomain.from_context(ctx)
    assert step.workflow is not None and step.workflow.backend.name == "fake"
    step.run()
    built = tmp_path / "tmp" / "eocene" / "nemo" / "domain" / "PALEORCA2"
    assert step.domain_dir == str(built)
    for template in EoceneDomain.writes:
        installed = Path(ctx.expand(template))
        assert installed.read_bytes() == (built / installed.name).read_bytes()


def test_eocene_domain_step_checks_vertical_grid(tmp_path: Path) -> None:
    present_day_domain(tmp_path, nav_lev=np.arange(31, dtype="float32"))
    step = EoceneDomain.from_context(Context(load_config(write_config(tmp_path)), "eocene"))
    with pytest.raises(ValueError, match="Different: nav_lev"):
        step.run()


def test_eocene_domain_step_needs_mask_step(tmp_path: Path) -> None:
    present_day_domain(tmp_path)
    steps = {**STEPS_WITHOUT_GRIDS, "generate_mask": False}
    step = EoceneDomain.from_context(Context(load_config(write_config(tmp_path, steps=steps)), "eocene"))
    with pytest.raises(FileNotFoundError, match="did not write domain_cfg.nc, maskutil.nc.*generate_mask"):
        step.run()


def test_eocene_domain_from_a_directory(tmp_path: Path) -> None:
    """A directory in ``eocene.nemo.domain``: the step installs its files; it does not run the pipeline."""
    present_day_domain(tmp_path)
    config = load_config(write_config(tmp_path))
    built = workflow(write_config(tmp_path), period="eocene")
    built.run()
    config.eocene.nemo.domain = built.domain_dir
    ctx = Context(config, "eocene")
    step = EoceneDomain.from_context(ctx)
    assert step.workflow is None
    step.run()
    assert Path(ctx.expand(EoceneDomain.writes[0])).is_file()


def test_eocene_nemo_steps_override(tmp_path: Path) -> None:
    """``--nemo`` selects the domain steps of the Eocene build: here, only the namelist."""
    present_day_domain(tmp_path)
    ctx = Context(load_config(write_config(tmp_path)), "eocene")
    override_steps(ctx.config, "eocene", "nemo", ["configure_domain"])
    step = EoceneDomain.from_context(ctx)
    assert [name for name, _, _ in step.workflow.plan()] == ["configure_domain"]


def test_eocene_dry_run_checks_domain_pipeline_inputs(tmp_path: Path) -> None:
    """With ``build`` the ``domain`` step runs the NEMO domain pipeline: a dry run of the Eocene pipeline checks its
    inputs too (here ``grids.nemo.coords_ori``) and writes nothing."""
    present_day_domain(tmp_path)
    config = write_config(tmp_path, steps={**STEPS_WITHOUT_GRIDS, "coordinates": True})
    ctx = Context(load_config(config), "eocene")
    for read in Stage.reads:  # the input folders that stage copies
        Path(ctx.expand(read)).mkdir(parents=True, exist_ok=True)
    before = tree(tmp_path)
    with pytest.raises(PipelineError, match="(?s)Step 'domain'.*coordinates  needs  .*coords_ori.nc"):
        run_pipeline([Stage, EoceneDomain], ctx, dry_run=True)
    assert tree(tmp_path) == before


def test_present_run_skips_components_without_section(tmp_path: Path) -> None:
    """``ecefast present run`` on a config without ``present.oifs`` (as on a laptop) runs the ``nemo`` step only."""
    cli.main(["present", "run", "-c", str(write_config(tmp_path)), "-l", "WARNING"])
    assert yaml.safe_load((tmp_path / "present" / "provenance.yml").read_text())["steps"] == ["nemo"]
