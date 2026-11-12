"""The NEMO domain pipeline end to end on the real laptop inputs, with the ``fake`` DOMAINcfg backend.

Opt-in, like ``test_regression.py``: set ``ECEFAST_TEST_DATA`` to a directory holding ``ECE4-DATA-V3/``,
``herold-et-al-2014/Supp/`` and ``data/PALEORCA2/coords_ori.nc``, then run
``pytest -m local_data``. Takes about 15 s.

All steps but ``generate_subbasins`` run for both bathymetries: coordinates, bathymetries (CDO), namelists, fake
DOMAINcfg, post-processing. The vertical grid of the result is compared with the present-day PALEORCA2 domain of
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
from ecefast.paleo.eocene.nemo.domain import check_vertical_grid

DATA = os.environ.get("ECEFAST_TEST_DATA")

pytestmark = [
    pytest.mark.local_data,
    pytest.mark.skipif(not DATA, reason="ECEFAST_TEST_DATA is not set"),
]


def test_fake_domain_pipeline_on_real_inputs(tmp_path: Path) -> None:
    data = Path(DATA)
    output = tmp_path / "domain"
    config = {
        "schema": 1,
        "paths": {
            "input": str(data / "ECE4-DATA-V3"),
            "output": str(tmp_path / "out"),
            "herold": str(data / "herold-et-al-2014" / "Supp"),
        },
        "tools": {"backend": "fake"},
        "nemo_domain": {
            "output_dir": str(output),
            "coords_ori": str(data / "data" / "PALEORCA2" / "coords_ori.nc"),
            "grids": {"target": "PALEORCA2", "source": "eORCA1", "staggering_source": "T", "staggering_target": "T"},
            "parameters": {"minimum_depth": 30},
            "steps": {
                "coordinates": True,
                "bathymetry": True,
                "configure_domain": True,
                "domain_cfg": True,
                "generate_mask": True,
                "generate_subbasins": False,
            },
            "bathymetries": [
                {
                    "name": "present_day",
                    "processor": "PresentDayBathymetry",
                    "source_file": "{input}/nemo/domain/eORCA1/domain_cfg.nc",
                },
                {
                    "name": "eocene",
                    "processor": "EoceneBathymetry",
                    "source_file": "{herold}/herold_etal_stddev_subgrid_etopo1_to_eocene_1x1.nc",
                },
            ],
        },
    }
    coords_ori = config["nemo_domain"]["coords_ori"]
    assert Path(coords_ori).is_file(), f"missing test data: {coords_ori}"
    config_file = tmp_path / "config.yml"
    config_file.write_text(yaml.safe_dump(config))

    main(["nemo", "domain", "-c", str(config_file), "-l", "WARNING"])

    present_file = data / "ECE4-DATA-V3" / "nemo" / "domain" / "PALEORCA2" / "domain_cfg.nc"
    with xr.open_dataset(present_file) as present:
        for name in ("present_day", "eocene"):
            domain_dir = output / "domain" / "PALEORCA2" / name
            assert sorted(p.name for p in domain_dir.iterdir()) == ["domain_cfg.nc", "maskutil.nc"]
            with xr.open_dataset(domain_dir / "domain_cfg.nc") as domain:
                assert domain.sizes == present.sizes
                np.testing.assert_array_equal(domain["nav_lev"].values, present["nav_lev"].values)
                check_vertical_grid(present, domain, str(present_file), name)
            with xr.open_dataset(domain_dir / "maskutil.nc") as masks:
                assert list(masks.data_vars) == ["tmaskutil", "umaskutil", "vmaskutil"]
