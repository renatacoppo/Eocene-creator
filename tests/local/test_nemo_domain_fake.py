"""The NEMO domain pipeline end to end on the real laptop inputs, with the ``fake`` DOMAINcfg backend.

Opt-in, like ``test_regression.py``: set ``ECEFAST_TEST_DATA`` to a directory holding ``ECE4-DATA-V3/``,
``herold-et-al-2014/Supp/`` and ``data/PALEORCA2/coords_ori.nc``, then run
``pytest -m local_data``. Takes about 15 s.

All steps run for both periods: ``ecefast nemo run`` for the present-day domain and ``ecefast nemo run --period
eocene`` (``eocene.nemo.domain: build``, after ``stage``) for the Eocene one: coordinates, bathymetry (CDO),
namelist, fake DOMAINcfg, post-processing, subbasins. The vertical grid of the result is compared with the present-day PALEORCA2 domain of
the input tree with ``check_vertical_grid``: ``nav_lev`` is equal, ``e3t_1d`` equal to rounding (the fake evaluates
the DOMAINcfg formula with NumPy, which differs from the Fortran build by about 1e-12 m).
"""

import os
from pathlib import Path

import numpy as np
import pytest
import xarray as xr
import yaml

from ecefast.cli.main import main
from ecefast.periods.eocene.nemo.domain import check_vertical_grid

DATA = os.environ.get("ECEFAST_TEST_DATA")

pytestmark = [
    pytest.mark.local_data,
    pytest.mark.skipif(not DATA, reason="ECEFAST_TEST_DATA is not set"),
]


def test_fake_domain_pipeline_on_real_inputs(tmp_path: Path) -> None:
    data = Path(DATA)
    coords_ori = data / "data" / "PALEORCA2" / "coords_ori.nc"
    assert coords_ori.is_file(), f"missing test data: {coords_ori}"
    config = {
        "schema": 2,
        "machine": {"name": "fake", "tmpdir": str(tmp_path / "tmp")},
        "grids": {"nemo": {"coords_ori": str(coords_ori)}},
        "present": {
            "input": str(data / "ECE4-DATA-V3"),
            "output": str(tmp_path / "present"),
            "nemo": {"source_grid": "eORCA1", "minimum_depth": 30},
        },
        "eocene": {
            "input": "{present.input}",
            "herold": str(data / "herold-et-al-2014" / "Supp"),
            "output": str(tmp_path / "eocene"),
            "nemo": {"domain": "build", "minimum_depth": 30},
        },
    }
    config_file = tmp_path / "config.yml"
    config_file.write_text(yaml.safe_dump(config))

    main(["nemo", "run", "-c", str(config_file), "-l", "WARNING"])
    main(["eocene", "run", "-c", str(config_file), "--steps", "stage,domain", "-l", "WARNING"])

    present_file = data / "ECE4-DATA-V3" / "nemo" / "domain" / "PALEORCA2" / "domain_cfg.nc"
    built_dirs = {
        "present_day": tmp_path / "present" / "nemo" / "domain" / "PALEORCA2",
        "eocene": tmp_path / "tmp" / "eocene" / "nemo" / "domain" / "PALEORCA2",
    }
    with xr.open_dataset(present_file) as present:
        for name, domain_dir in built_dirs.items():
            assert sorted(p.name for p in domain_dir.iterdir()) == ["domain_cfg.nc", "maskutil.nc", "subbasins.nc"]
            with xr.open_dataset(domain_dir / "domain_cfg.nc") as built:
                assert built.sizes == present.sizes
                np.testing.assert_array_equal(built["nav_lev"].values, present["nav_lev"].values)
                check_vertical_grid(present, built, str(present_file), name)
            with xr.open_dataset(domain_dir / "maskutil.nc") as masks:
                assert list(masks.data_vars) == ["tmaskutil", "umaskutil", "vmaskutil"]
    installed = tmp_path / "eocene" / "nemo" / "domain" / "PALEORCA2"
    assert sorted(p.name for p in installed.iterdir()) == ["domain_cfg.nc", "maskutil.nc"]
    plot = tmp_path / "tmp" / "present" / "nemo" / "bathymetry" / "PALEORCA2" / "landsea_mask_comparison.png"
    assert plot.is_file()
