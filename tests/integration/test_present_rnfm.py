"""``ecefast present run --steps stage,rnfm`` end to end on a synthetic input tree and synthetic OASIS weights.

The input tree holds only the files the steps declare in ``reads`` (``tests/synthetic.py``).
"""

import os
from pathlib import Path

import numpy as np
import pytest
import xarray as xr
import yaml

from ecefast.cli.main import main
from ecefast.core.config import load_config
from ecefast.core.steps import PipelineError
from ecefast.core.workspace import Context
from ecefast.periods.present import pipeline
from synthetic import RUNOFF_MAPS_DELIVERING, write_input_tree

pytestmark = pytest.mark.integration

STEPS = ["stage", "rnfm"]


@pytest.fixture
def tree(tmp_path: Path) -> dict:
    """Configuration and synthetic input tree of STEPS."""
    (tmp_path / "input").mkdir()
    raw = {
        "schema": 2,
        "machine": {"name": "fake", "tmpdir": str(tmp_path / "tmp")},
        "present": {
            "input": str(tmp_path / "input"),
            "output": str(tmp_path / "present"),
            "rnfm": {"weights_dir": str(tmp_path / "run")},
        },
    }
    config_file = tmp_path / "config.yml"
    config_file.write_text(yaml.safe_dump(raw))
    ctx = Context(load_config(config_file), "present")
    steps = [s for s in pipeline.PIPELINE if s.name in STEPS]
    inputs = write_input_tree(steps, ctx)
    return {"config": str(config_file), "ctx": ctx, "inputs": inputs, "raw": raw}


def test_paths_expand(tree: dict) -> None:
    ctx = tree["ctx"]
    root = Path(ctx.section.input).parent
    assert [ctx.expand(t) for t in pipeline.PresentRNFM.reads] == [
        str(root / "input/runoff-mapper/runoff_maps.nc"),
        str(root / "run/rmp_F128R-ocean_to_PALEORCA2-T_BILINEAR.nc"),
        str(root / "run/areas.nc"),
    ]
    assert [ctx.expand(t) for t in pipeline.PresentRNFM.writes] == [str(root / "present/runoff-mapper/runoff_maps.nc")]


def test_dry_run_writes_nothing(tree: dict) -> None:
    main(["present", "run", "-c", tree["config"], "--steps", ",".join(STEPS), "--dry-run"])
    assert not os.path.exists(tree["ctx"].section.output)


def test_run_moves_the_arrival_point(tree: dict) -> None:
    ctx = tree["ctx"]
    main(["present", "run", "-c", tree["config"], "--steps", ",".join(STEPS)])
    original = xr.load_dataset(ctx.expand(pipeline.PresentRNFM.reads[0]))
    maps = xr.load_dataset(ctx.expand(pipeline.PresentRNFM.writes[0]))
    np.testing.assert_array_equal(maps["drainage_basin_id"].values, original["drainage_basin_id"].values)
    for name in ("arrival_point_id", "calving_point_id"):
        assert np.argwhere(maps[name].values == 1).tolist() == [list(RUNOFF_MAPS_DELIVERING)]
    record = yaml.safe_load((Path(ctx.section.output) / "provenance.yml").read_text())
    assert record["steps"] == STEPS


def test_whole_period_skips_rnfm_without_its_section(tree: dict) -> None:
    raw = tree["raw"]
    del raw["present"]["rnfm"]
    Path(tree["config"]).write_text(yaml.safe_dump(raw))
    assert pipeline.run(tree["config"], dry_run=True) == ["stage"]


def test_missing_weights_name_where_to_get_them(tree: dict) -> None:
    rmp = Path(tree["ctx"].expand(pipeline.PresentRNFM.reads[1]))
    rmp.unlink()
    with pytest.raises(PipelineError, match="run directory of an EC-Earth run"):
        pipeline.run(tree["config"], select=STEPS, dry_run=True)
