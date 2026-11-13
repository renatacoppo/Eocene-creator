"""The Eocene starts from the present-day tree (``eocene.input: "{present.output}"`` on Atos): every file it reads
from its input must be written by the present-day pipeline."""

import os
from pathlib import Path

import pytest

from ecefast.core.layout import initial_state_copies
from ecefast.core.workspace import Context
from ecefast.periods.eocene import pipeline as eocene_pipeline
from ecefast.periods.present import pipeline as present_pipeline
from synthetic import make_config

pytestmark = pytest.mark.unit

# written by the present-day nemo step (its writes depend on present.nemo.steps, so they are not declared)
PRESENT_NEMO_WRITES = ["{output}/nemo/domain/{grids.nemo.name}/domain_cfg.nc"]


def test_present_tree_holds_every_eocene_input(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    present = Context(config, "present")
    written = [present.expand(t) for step in present_pipeline.PIPELINE for t in step.writes]
    written += [present.expand(t) for t in PRESENT_NEMO_WRITES]
    config.eocene.input = config.present.output
    eocene = Context(config, "eocene")
    missing = [
        template
        for step in eocene_pipeline.PIPELINE
        for template in step.reads
        if template.startswith("{input}")
        and not any(eocene.expand(template) == w or eocene.expand(template).startswith(w + os.sep) for w in written)
    ]
    assert missing == []


def test_present_stage_copies_only_the_orca2_domain(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    root = Path(config.present.input)
    for sub in [
        "oifs/TL63L31",
        "nemo/initial",
        "nemo/domain/ORCA2",
        "nemo/domain/eORCA1",
        "oasis/PALEORCA2",
        *initial_state_copies("TL63L31", "PALEORCA2"),
    ]:
        (root / sub).mkdir(parents=True)
        (root / sub / "f.txt").write_text(sub)
    (root / "runoff-mapper").mkdir()
    present_pipeline.PresentStage.from_context(Context(config, "present")).run()
    domains = Path(config.present.output) / "nemo" / "domain"
    assert sorted(p.name for p in domains.iterdir()) == ["ORCA2"]
    assert (domains / "ORCA2" / "f.txt").read_text() == "nemo/domain/ORCA2"
