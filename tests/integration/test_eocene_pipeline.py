"""``ecefast eocene run`` end to end on a synthetic input tree, with the ``fake`` backend.

The input tree holds only the files the steps declare in ``reads`` (``tests/synthetic.py``), so a step that reads
an undeclared file fails here. OIFS is not run (real GRIB inputs only: ``tests/local/``, unit tests in
``tests/unit/oifs/``).
"""

import os
from pathlib import Path

import pytest
import yaml

from ecefast.cli.main import main
from ecefast.core.config import load_config
from ecefast.core.workspace import Context
from ecefast.paleo.eocene import pipeline
from synthetic import nemo_domain_section, write_input_tree

pytestmark = pytest.mark.integration

STEPS = ["stage", "domain", "oasis", "nemo", "rnfm"]


@pytest.fixture(scope="module")
def tree(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """Configuration and synthetic input tree for STEPS, shared by the tests of this module (it takes a while)."""
    root = tmp_path_factory.mktemp("eocene")
    for name in ("input", "herold"):
        (root / name).mkdir()
    config_file = root / "config.yml"
    raw = {
        "schema": 1,
        "paths": {"input": str(root / "input"), "output": str(root / "out"), "herold": str(root / "herold")},
        "tools": {"backend": "fake"},
        "nemo_domain": nemo_domain_section(root / "domain", root),
    }
    config_file.write_text(yaml.safe_dump(raw))
    ctx = Context(load_config(config_file))
    steps = [s for s in pipeline.PIPELINE if s.name in STEPS]
    inputs = write_input_tree(steps, ctx)
    return {"config": str(config_file), "ctx": ctx, "steps": steps, "inputs": inputs, "root": root}


def files_under(*roots: Path) -> dict[str, float]:
    """Every file under ``roots`` with its modification time."""
    return {str(p): p.stat().st_mtime for root in roots for p in Path(root).rglob("*") if p.is_file()}


def test_input_tree_holds_only_declared_reads(tree: dict) -> None:
    ctx = tree["ctx"]
    declared = {ctx.expand(t) for step in tree["steps"] for t in step.reads}
    assert {str(p) for p in tree["inputs"]} == declared
    files = set(files_under(Path(ctx.paths.input), Path(ctx.paths.herold)))
    assert files <= declared, "files outside the declared reads"


def test_dry_run_writes_nothing(tree: dict) -> None:
    main(["eocene", "run", "-c", tree["config"], "--steps", ",".join(STEPS), "--dry-run"])
    assert not os.path.exists(tree["ctx"].paths.output)


def test_run_writes_every_declared_output(tree: dict) -> None:
    ctx = tree["ctx"]
    before = files_under(Path(ctx.paths.input), Path(ctx.paths.herold))
    main(["eocene", "run", "-c", tree["config"], "--steps", ",".join(STEPS)])

    missing = [p for step in tree["steps"] for p in (ctx.expand(t) for t in step.writes) if not os.path.exists(p)]
    assert missing == []
    record = yaml.safe_load((Path(ctx.paths.output) / "provenance.yml").read_text())
    assert record["steps"] == STEPS
    assert files_under(Path(ctx.paths.input), Path(ctx.paths.herold)) == before, "the read-only trees changed"
