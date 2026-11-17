"""``ecefast oifs run`` on ECMWF Atos: the generated TL63L31 initial state against ECE4-DATA (run by hand).

Run ``ecefast oifs run -c configs/atos.yml`` first (``grids.oifs.name: TL63L31``, ``present.oifs.source_grid:
TL255L91``), then::

    ECEFAST_HPC_CONFIG=configs/atos.yml pytest -m hpc tests/hpc/test_oifs_data_hpc.py

``scripts/compare_outputs.py`` compares the three initial-state files of
``<present.output>/initial_state/oifs/TL63L31/<startdate>`` with the same files of ``present.input`` (that folder also
holds wave-model files the generator does not make). A difference is a finding for task 7.1 (whether the generator still reproduces ECE4-DATA),
not necessarily a bug: report it in the pull request.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from ecefast.components.oifs.initial_state import IC_FILES
from ecefast.core.config import load_config
from ecefast.core.layout import oifs_initial_dir

CONFIG = os.environ.get("ECEFAST_HPC_CONFIG")
REPO = Path(__file__).parents[2]

pytestmark = [
    pytest.mark.hpc,
    pytest.mark.skipif(not CONFIG, reason="ECEFAST_HPC_CONFIG is not set"),
]


def test_generated_initial_state_matches_ece4_data(tmp_path: Path) -> None:
    config = load_config(CONFIG)
    present = config.period("present")
    assert present.oifs is not None, "the configuration has no present.oifs section"
    grid = config.grids.oifs
    new = Path(oifs_initial_dir(present.output, grid.name, grid.startdate))
    reference = Path(oifs_initial_dir(present.input, grid.name, grid.startdate))
    assert new.is_dir(), f"run `ecefast oifs run -c {CONFIG}` first: {new} does not exist"
    selected = tmp_path / "reference"
    selected.mkdir()
    for name in IC_FILES:
        (selected / name).symlink_to(reference / name)
    compare = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "compare_outputs.py"), str(selected), str(new)], check=False
    )
    assert compare.returncode == 0, f"{new} differs from {reference}, see the report above"
