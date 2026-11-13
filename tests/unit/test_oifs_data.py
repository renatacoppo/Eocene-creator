"""Unit tests for ``ecefast oifs data`` (the OIFS generator): config section, plan, input checks, CLI.

The generation itself needs the TL255L91 inputs of Atos: ``tests/local/test_oifs_data_local.py`` runs it on the
local TL63L31 files, ``tests/hpc/test_oifs_data_hpc.py`` compares an Atos run with ECE4-DATA.
"""

from pathlib import Path

import pytest
import yaml

from ecefast.cli import main as cli
from ecefast.components.oifs import generator
from ecefast.components.oifs.generator import GRIDS_DIR, STEP_DESCRIPTIONS, OIFSData
from ecefast.core.config import ConfigError, load_config
from ecefast.core.steps import PipelineError

pytestmark = pytest.mark.unit


def write_config(tmp_path: Path, data: dict | None = None, grid: str = "TL63L31") -> Path:
    for name in ("input", "herold"):
        (tmp_path / name).mkdir(exist_ok=True)
    raw = {
        "schema": 2,
        "inputs": {"ece4_data": str(tmp_path / "input"), "herold": str(tmp_path / "herold")},
        "oifs": {"grid": grid, "data": {"output_dir": str(tmp_path / "out")} | (data or {})},
    }
    path = tmp_path / "config.yml"
    path.write_text(yaml.safe_dump(raw))
    return path


def source_files(tmp_path: Path, grid: str = "TL255L91") -> Path:
    """Empty stand-ins for the source initial state in the input tree."""
    folder = tmp_path / "input" / "oifs" / grid / "19900101"
    folder.mkdir(parents=True)
    for name in generator.IC_FILES:
        (folder / name).write_text(name)
    return folder


# --- config ---------------------------------------------------------------------------------------------------------


def test_defaults(tmp_path: Path) -> None:
    data = load_config(write_config(tmp_path)).oifs.data
    assert (data.source_grid, data.startdate, data.climate_version) == ("TL255L91", "19900101", "climate.v020")
    assert (data.climate_dir, data.precomputed_climate_dir, data.vertical_grids_dir) == (None, None, None)
    assert (data.steps.spectral, data.steps.gridpoint, data.steps.boundary) == (True, True, False)


def test_overrides_and_placeholders(tmp_path: Path) -> None:
    raw = {"source_grid": "TL159L91", "steps": {"boundary": True}, "vertical_grids_dir": "{inputs.herold}/grids"}
    data = load_config(write_config(tmp_path, raw)).oifs.data
    assert data.source_grid == "TL159L91"
    assert (data.steps.spectral, data.steps.boundary) == (True, True)
    assert data.vertical_grids_dir == f"{tmp_path / 'herold'}/grids"


@pytest.mark.parametrize(
    "data, key",
    [
        ({"startdate": 19900101}, "oifs.data.startdate"),
        ({"steps": {"spectral": "yes"}}, "oifs.data.steps.spectral"),
        ({"steps": {"vertical": True}}, "oifs.data.steps"),
        ({"climate": "/x"}, "oifs.data"),
    ],
)
def test_bad_values(tmp_path: Path, data: dict, key: str) -> None:
    with pytest.raises(ConfigError, match=key):
        load_config(write_config(tmp_path, data))


def test_missing_output_dir(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    raw = yaml.safe_load(path.read_text())
    del raw["oifs"]["data"]["output_dir"]
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(ConfigError, match="oifs.data.output_dir"):
        load_config(path)


def test_needs_the_section(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path))
    config.oifs.data = None
    with pytest.raises(ConfigError, match="needs an 'oifs.data' section"):
        OIFSData(config)


def test_bad_grid_name(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="'oifs.grid' must be a grid name"):
        OIFSData(load_config(write_config(tmp_path, grid="T63")))


# --- plan and checks ------------------------------------------------------------------------------------------------


def test_plan_with_vertical_interpolation(tmp_path: Path) -> None:
    """TL63L31 from TL255L91: different levels, so the initial state is interpolated vertically."""
    gen = OIFSData(load_config(write_config(tmp_path, {"vertical_grids_dir": "/grids"})))
    assert (gen.spectral, gen.vertical, gen.target_spectral, gen.ecmwf_name) == (63, 31, "TL63", "63l_2")
    assert gen.do_vertical
    plan = {name: (reads, writes) for name, reads, writes in gen.plan()}
    assert list(plan) == ["spectral", "gridpoint", "vertical"]
    out, work = tmp_path / "out", tmp_path / "out" / "work"
    assert plan["vertical"][1] == [str(out / "oifs" / "TL63L31" / "19900101" / f) for f in generator.IC_FILES]
    assert "/grids/TL63_grid.nc" in plan["vertical"][0]
    assert str(GRIDS_DIR / "L31.txt") in plan["vertical"][0]
    assert all(path.startswith(str(work)) for path in plan["spectral"][1] + plan["gridpoint"][1])


def test_plan_same_levels_installs(tmp_path: Path) -> None:
    gen = OIFSData(load_config(write_config(tmp_path, {"source_grid": "TL159L31"})))
    assert not gen.do_vertical
    assert [name for name, _, _ in gen.plan()] == ["spectral", "gridpoint", "install"]


@pytest.mark.parametrize(
    "precomputed, expected", [(True, "ICMCLECE4"), (False, "ICMCLECE4-1990")], ids=["precomputed", "computed"]
)
def test_plan_boundary(tmp_path: Path, precomputed: bool, expected: str) -> None:
    ready = tmp_path / "ready"
    if precomputed:
        (ready / "TL63L31" / "climate.v020").mkdir(parents=True)
        (ready / "TL63L31" / "climate.v020" / "ICMCLECE4").write_text("x")
    data = {"steps": {"spectral": False, "gridpoint": False, "boundary": True}, "precomputed_climate_dir": str(ready)}
    data["climate_dir"] = "/clim"
    gen = OIFSData(load_config(write_config(tmp_path, data)))
    (name, reads, writes), *_ = gen.plan()
    assert name == "boundary"
    assert writes == [str(tmp_path / "out" / "oifs" / "TL63L31" / "climate.v020" / expected)]
    if not precomputed:
        assert reads == [f"/clim/63l_2/month_{var}" for var in generator.CLIMATE_VARIABLES]


def test_check_lists_every_missing_input(tmp_path: Path) -> None:
    gen = OIFSData(load_config(write_config(tmp_path)))
    with pytest.raises(PipelineError, match="4 input files are missing") as error:
        gen.check()
    message = str(error.value)
    source = tmp_path / "input" / "oifs" / "TL255L91" / "19900101"
    for name in generator.IC_FILES:
        assert str(source / name) in message
    assert "oifs.data.vertical_grids_dir is not set" in message


def test_check_passes_with_inputs(tmp_path: Path) -> None:
    source_files(tmp_path, "TL159L31")
    OIFSData(load_config(write_config(tmp_path, {"source_grid": "TL159L31"}))).check()


# --- CLI ------------------------------------------------------------------------------------------------------------


def test_cli_dry_run_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    source_files(tmp_path, "TL159L31")
    config = write_config(tmp_path, {"source_grid": "TL159L31"})
    cli.main(["oifs", "data", "-c", str(config), "--dry-run"])
    assert not (tmp_path / "out").exists()
    log = capsys.readouterr().err
    assert "Dry run" in log
    assert str(tmp_path / "out" / "oifs" / "TL63L31" / "19900101" / "ICMSHECE4INIT") in log


def test_cli_missing_input_exits(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["oifs", "data", "-c", str(write_config(tmp_path))])
    assert exit_info.value.code == 1
    assert not (tmp_path / "out").exists()


def test_cli_help_lists_steps(capsys: pytest.CaptureFixture) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["oifs", "data", "-h"])
    assert exit_info.value.code == 0
    lines = capsys.readouterr().out.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("steps, in run order"))
    assert [line.split()[0] for line in lines[start + 1 :]] == list(STEP_DESCRIPTIONS)


def test_cli_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(generator, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    cli.main(["oifs", "data", "-c", "x.yml", "--dry-run"])
    assert calls == [(("x.yml",), {"dry_run": True})]
