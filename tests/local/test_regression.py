"""Regression test: the Eocene workflow reproduces the frozen baseline.

Opt-in. Set ``ECEFAST_TEST_DATA`` to a directory holding::

    ECE4-DATA-V3/                         input tree
    herold-et-al-2014/Supp/               Herold et al. (2014) supplement
    data/domain/PALEORCA2/eocene/         Eocene domain_cfg.nc and maskutil.nc
    EOCENE-BASELINE/eocene/               frozen reference output

then run ``pytest -m local_data``. Takes about a minute.

The workflow runs with the ``cdo`` binary of the running environment (its ``bin`` first in ``PATH``), so a
different CDO installed elsewhere on ``PATH`` (e.g. Homebrew) cannot leak into the comparison.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).parents[2]
DATA = os.environ.get("ECEFAST_TEST_DATA")

pytestmark = [
    pytest.mark.local_data,
    pytest.mark.skipif(not DATA, reason="ECEFAST_TEST_DATA is not set"),
]


def test_eocene_workflow_matches_baseline(tmp_path: Path) -> None:
    data = Path(DATA)
    baseline = data / "EOCENE-BASELINE" / "eocene"
    output = tmp_path / "EOCENE-TEST"
    config = {
        "dirs": {
            "input": str(data / "ECE4-DATA-V3"),
            "output": str(output),
            "herold": str(data / "herold-et-al-2014" / "Supp"),
            "domain": str(data / "data" / "domain" / "PALEORCA2" / "eocene"),
            "tmpdir": str(tmp_path / "tmp"),
        }
    }
    for key, path in config["dirs"].items():
        if key not in ("output", "tmpdir"):
            assert Path(path).is_dir(), f"missing test data: {path}"
    assert baseline.is_dir(), f"missing test data: {baseline}"
    config_file = tmp_path / "config.yml"
    config_file.write_text(yaml.safe_dump(config))

    env = {**os.environ, "PATH": os.pathsep.join([str(Path(sys.executable).parent), os.environ.get("PATH", "")])}
    subprocess.run(
        [sys.executable, "-m", "eocene.cli_eocene", "-c", str(config_file), "--run", "all", "--copy"],
        check=True,
        cwd=tmp_path,
        env=env,
    )
    compare = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "compare_outputs.py"), str(baseline), str(output)], env=env
    )

    assert compare.returncode == 0, "output differs from EOCENE-BASELINE/eocene, see the report above"
