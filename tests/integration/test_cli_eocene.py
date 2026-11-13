"""Tests of ``ecefast eocene run|steps`` and ``provenance.yml``, through ``main(argv)``.

The real Eocene steps need the real data (see ``tests/local/test_regression.py``), so the pipeline is replaced by
the real ``stage`` step and one dummy step, on a tiny synthetic input tree.
"""

import hashlib
import logging
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from ecefast import __version__
from ecefast.cli.main import main
from ecefast.core import provenance
from ecefast.core.steps import ComponentStep
from ecefast.core.workspace import Stage
from ecefast.paleo.eocene import pipeline

pytestmark = pytest.mark.integration


class Dummy(ComponentStep):
    """Write a dummy file."""

    name = "dummy"
    needs = ["stage"]
    reads = ["{eocene.output_dir}/nemo/initial/woa.nc"]  # copied by stage
    writes = ["{eocene.output_dir}/dummy.txt"]

    def __init__(self, output: str):
        self.output = output

    @classmethod
    def from_context(cls, ctx):
        return cls(ctx.config.eocene.output_dir)

    def run(self):
        Path(self.output, "dummy.txt").write_text("dummy")


class NeedsMissing(Dummy):
    """Read a file that does not exist."""

    name = "missing"
    reads = ["{inputs.ece4_data}/nemo/initial/woa13-levitus-L31.nc", "{inputs.herold}/topo.nc"]
    writes = ["{eocene.output_dir}/missing.txt"]


@pytest.fixture
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """A tiny input tree, a config file, and the pipeline [Stage, Dummy]."""
    data = tmp_path / "input"
    for sub, name in [("oifs/TL63L31", "ICMGG"), ("nemo/initial", "woa.nc"), ("oasis/PALEORCA2", "rstos.nc")]:
        (data / sub).mkdir(parents=True)
        (data / sub / name).write_text(name)
    (tmp_path / "herold").mkdir()
    output = tmp_path / "out"
    config = tmp_path / "config.yml"
    config.write_text(
        yaml.safe_dump(
            {
                "schema": 2,
                "inputs": {"ece4_data": str(data), "herold": str(tmp_path / "herold")},
                "eocene": {"output_dir": str(output), "domain": {"from": str(tmp_path / "domain")}},
            }
        )
    )
    monkeypatch.setattr(pipeline, "PIPELINE", [Stage, Dummy])
    monkeypatch.setattr(pipeline, "cdo_version", lambda: "9.9.9")
    return {"config": str(config), "output": output}


@pytest.fixture(autouse=True)
def log(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    """Capture the ``ecefast`` logger (it does not propagate to the root logger) and restore it afterwards."""
    logger = logging.getLogger("ecefast")
    saved = logger.handlers[:], logger.level, logger.propagate
    logger.handlers[:] = [caplog.handler]
    yield caplog
    logger.handlers[:], logger.level, logger.propagate = saved


def run(*args: str) -> None:
    main(["eocene", "run", *args])


# --- steps ---------------------------------------------------------------------------------------------------------


def test_steps_lists_every_step_on_one_line(capsys: pytest.CaptureFixture) -> None:
    main(["eocene", "steps"])
    lines = capsys.readouterr().out.strip().splitlines()
    assert [line.split()[0] for line in lines] == ["stage", "domain", "oasis", "oifs", "nemo", "rnfm"]
    nemo = lines[4]
    assert "needs: stage" in nemo
    assert "{inputs.ece4_data}/nemo/initial/woa13-levitus-L31.nc" in nemo
    assert "{eocene.output_dir}/nemo/initial/woa13-levitus-L31_woa-pi.nc" in nemo


def test_pipeline_order() -> None:
    assert [s.name for s in pipeline.PIPELINE] == ["stage", "domain", "oasis", "oifs", "nemo", "rnfm"]


# --- run -----------------------------------------------------------------------------------------------------------


def test_run_writes_outputs_and_provenance(tree: dict, log) -> None:
    with log.at_level("INFO", logger="ecefast"):
        run("-c", tree["config"])
    out = tree["output"]
    assert (out / "dummy.txt").read_text() == "dummy"
    assert (out / "nemo" / "initial" / "woa.nc").exists()
    assert "CDO version: 9.9.9" in log.text

    record = yaml.safe_load((out / "provenance.yml").read_text())
    assert list(record) == ["steps", "config", "ecefast", "versions", "start", "end"]
    assert record["steps"] == ["stage", "dummy"]
    assert record["config"]["file"] == tree["config"]
    assert record["config"]["sha256"] == hashlib.sha256(Path(tree["config"]).read_bytes()).hexdigest()
    assert record["ecefast"]["version"] == __version__
    assert record["ecefast"]["git_commit"]
    assert set(record["versions"]) == {"python", "cdo", "eccodes"}
    assert record["versions"]["cdo"] == "9.9.9"
    assert datetime.fromisoformat(record["start"]) <= datetime.fromisoformat(record["end"])


def test_dry_run_writes_nothing(tree: dict, log) -> None:
    with log.at_level("INFO", logger="ecefast"):
        run("-c", tree["config"], "--dry-run")
    assert not tree["output"].exists()
    assert "Dry run: nothing is written" in log.text
    assert "dummy" in log.text


def test_missing_input_exits_and_writes_nothing(tree: dict, monkeypatch: pytest.MonkeyPatch, log) -> None:
    monkeypatch.setattr(pipeline, "PIPELINE", [Stage, NeedsMissing])
    with pytest.raises(SystemExit) as exit_info:
        run("-c", tree["config"])
    assert exit_info.value.code != 0
    assert not tree["output"].exists()
    assert "Cannot start: 2 input files are missing. Nothing was written." in log.text
    assert "woa13-levitus-L31.nc" in log.text and "topo.nc" in log.text


def test_stage_refuses_non_empty_output_without_overwrite(tree: dict, log) -> None:
    out = tree["output"]
    out.mkdir()
    (out / "old.txt").write_text("old")
    with pytest.raises(SystemExit) as exit_info:
        run("-c", tree["config"])
    assert exit_info.value.code != 0
    assert "is not empty" in log.text
    assert sorted(p.name for p in out.iterdir()) == ["old.txt"]

    run("-c", tree["config"], "--overwrite")
    assert not (out / "old.txt").exists()
    assert (out / "dummy.txt").exists()


def test_stage_accepts_empty_output(tree: dict) -> None:
    tree["output"].mkdir()
    run("-c", tree["config"])
    assert (tree["output"] / "dummy.txt").exists()


def test_steps_without_stage_reruns_on_existing_output(tree: dict) -> None:
    run("-c", tree["config"])
    out = tree["output"]
    (out / "dummy.txt").unlink()
    (out / "marker").write_text("kept")
    run("-c", tree["config"], "--steps", "dummy")
    assert (out / "dummy.txt").exists()
    assert (out / "marker").exists()  # stage did not run
    assert yaml.safe_load((out / "provenance.yml").read_text())["steps"] == ["dummy"]


def test_steps_without_stage_needs_staged_output(tree: dict, log) -> None:
    with pytest.raises(SystemExit):
        run("-c", tree["config"], "--steps", "dummy")
    assert "needs 'stage', which is not selected and has not run before" in log.text
    assert not tree["output"].exists()


def test_unknown_step_exits(tree: dict, log) -> None:
    with pytest.raises(SystemExit) as exit_info:
        run("-c", tree["config"], "--steps", "dummy,nope")
    assert exit_info.value.code != 0
    assert "Unknown step(s): nope" in log.text


def test_bad_config_exits(tmp_path: Path, log) -> None:
    with pytest.raises(SystemExit) as exit_info:
        run("-c", str(tmp_path / "nope.yml"))
    assert exit_info.value.code != 0
    assert "nope.yml" in log.text


# --- provenance helpers --------------------------------------------------------------------------------------------


def test_command_output_unknown_when_command_fails(tmp_path: Path) -> None:
    assert provenance._command_output(["ecefast-no-such-command"]) == "unknown"
    assert provenance._command_output(["git", "rev-parse", "HEAD"], cwd=str(tmp_path)) == "unknown"
