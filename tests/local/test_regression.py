"""Regression test: the Eocene workflow reproduces the frozen baseline.

Opt-in. Set ``ECEFAST_TEST_DATA`` to a directory holding::

    ECE4-DATA-V3/                         input tree
    herold-et-al-2014/Supp/               Herold et al. (2014) supplement
    data/domain/PALEORCA2/eocene/         Eocene domain_cfg.nc and maskutil.nc
    BASELINE/eocene/                      frozen reference output, with BASELINE/BASELINE.txt

then run ``pytest -m local_data``. Takes about a minute and a half: ``ecefast eocene run --overwrite``, then
``--steps nemo`` on the same output, each compared with the baseline.

The workflow uses the ``cdo`` found first on ``PATH``. A different CDO version legitimately changes the
results (e.g. remapped bathymetries), so the test is skipped unless ``cdo --version`` matches the
``CDO:`` line of ``BASELINE/BASELINE.txt``.
"""

import os
import re
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


def cdo_version() -> str:
    """Version of the ``cdo`` binary first on ``PATH``."""
    out = subprocess.run(["cdo", "--version"], capture_output=True, text=True, check=True)
    return re.search(r"version (\S+)", out.stdout + out.stderr).group(1)


def baseline_cdo_version(baseline_txt: Path) -> str:
    """CDO version recorded in the ``CDO:`` line of ``BASELINE.txt``."""
    return re.search(r"^CDO:\s+(\S+)", baseline_txt.read_text(), re.MULTILINE).group(1)


def test_eocene_workflow_matches_baseline(tmp_path: Path) -> None:
    data = Path(DATA)
    baseline = data / "BASELINE" / "eocene"
    output = tmp_path / "OUTPUT" / "eocene"
    config = {
        "schema": 2,
        "inputs": {"ece4_data": str(data / "ECE4-DATA-V3"), "herold": str(data / "herold-et-al-2014" / "Supp")},
        "tmpdir": str(tmp_path / "tmp"),
        "eocene": {
            "output_dir": str(output),
            "domain": {"from": str(data / "data" / "domain" / "PALEORCA2" / "eocene")},
        },
    }
    for path in (*config["inputs"].values(), config["eocene"]["domain"]["from"]):
        assert Path(path).is_dir(), f"missing test data: {path}"
    assert baseline.is_dir(), f"missing test data: {baseline}"
    expected_cdo = baseline_cdo_version(data / "BASELINE" / "BASELINE.txt")
    found_cdo = cdo_version()
    if found_cdo != expected_cdo:
        pytest.skip(f"cdo on PATH is {found_cdo}, the baseline was made with CDO {expected_cdo}: results would differ")
    config_file = tmp_path / "config.yml"
    config_file.write_text(yaml.safe_dump(config))

    def ecefast_eocene_run(*args: str) -> None:
        subprocess.run(
            [sys.executable, "-m", "ecefast.cli.main", "eocene", "run", "-c", str(config_file), *args],
            check=True,
            cwd=tmp_path,
        )

    def differences() -> int:
        compare = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "compare_outputs.py"), str(baseline), str(output)]
        )
        return compare.returncode

    # full run
    ecefast_eocene_run("--overwrite")
    assert differences() == 0, "output differs from BASELINE/eocene, see the report above"
    assert yaml.safe_load((output / "provenance.yml").read_text())["steps"] == [
        "stage",
        "domain",
        "oasis",
        "oifs",
        "nemo",
        "rnfm",
    ]

    # rerun one step on the existing output, without stage
    ecefast_eocene_run("--steps", "nemo")
    assert differences() == 0, "output differs from BASELINE/eocene after '--steps nemo', see the report above"
    assert yaml.safe_load((output / "provenance.yml").read_text())["steps"] == ["nemo"]
