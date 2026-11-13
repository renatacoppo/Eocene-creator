"""``ecefast oifs data`` on the real TL63L31 files of the local input tree.

Opt-in, like ``test_regression.py``: set ``ECEFAST_TEST_DATA`` to a directory holding ``ECE4-DATA-V3/`` and
``herold-et-al-2014/Supp/``. The local tree has no TL255L91, so this makes TL63L31 from TL63L31: the spectral
truncation and the nearest-neighbour remapping run on real GRIB files, the vertical interpolation does not (same
number of levels; it is checked on Atos, ``tests/hpc/test_oifs_data_hpc.py``). A few seconds.
"""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

from ecefast.cli.main import main
from ecefast.components.oifs.generator import IC_FILES

DATA = os.environ.get("ECEFAST_TEST_DATA")

pytestmark = [
    pytest.mark.local_data,
    pytest.mark.skipif(not DATA, reason="ECEFAST_TEST_DATA is not set"),
]


def grib_count(path: Path) -> int:
    return int(subprocess.run(["grib_count", str(path)], check=True, capture_output=True, text=True).stdout)


def test_tl63l31_from_itself(tmp_path: Path) -> None:
    data = Path(DATA)
    output = tmp_path / "OUTPUT" / "oifs-data"
    config = {
        "schema": 2,
        "inputs": {"ece4_data": str(data / "ECE4-DATA-V3"), "herold": str(data / "herold-et-al-2014" / "Supp")},
        "oifs": {"grid": "TL63L31", "data": {"output_dir": str(output), "source_grid": "TL63L31"}},
    }
    config_file = tmp_path / "config.yml"
    config_file.write_text(yaml.safe_dump(config))

    main(["oifs", "data", "-c", str(config_file), "-l", "WARNING"])

    source = data / "ECE4-DATA-V3" / "oifs" / "TL63L31" / "19900101"
    target = output / "oifs" / "TL63L31" / "19900101"
    assert sorted(p.name for p in target.iterdir()) == sorted(IC_FILES)
    for name in IC_FILES:
        assert grib_count(target / name) == grib_count(source / name), name
    assert not list(target.glob("*.tmp-*")), "temporary files left in the output"
