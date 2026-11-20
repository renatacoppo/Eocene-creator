"""Data version v2: the NEMO domains of both periods on the real laptop inputs, with the ``fake`` DOMAINcfg backend.

Opt-in like ``test_nemo_domain_fake.py``: ``ECEFAST_TEST_DATA`` must hold ``ECE4-DATA-V3/`` (with the ORCA2 domain),
``herold-et-al-2014/Supp/`` and ``data/PALEORCA2/coords_ori.nc``; CDO 2.6 is needed. Run ``pytest -m local_data``.

The domain pipeline runs from the coordinates to the domain files (without subbasins and sections). The counts are
those of the v2 design (issue #58), made with CDO 2.6.4: a change means the v2 output changed.
"""

import os
from pathlib import Path

import numpy as np
import pytest
import xarray as xr
import yaml

from ecefast.components.nemo.bathymetry import geography
from ecefast.components.nemo.domain.pipeline import NEMOWorkflow
from ecefast.core.config import load_config
from ecefast.core.workspace import Context
from ecefast.periods.eocene.bathymetry import BATHYMETRIES as EOCENE
from ecefast.periods.present.bathymetry import BATHYMETRIES as PRESENT
from ecefast.tools.ecearth import FakeBackend
from synthetic import needs_cdo_2_6

DATA = os.environ.get("ECEFAST_TEST_DATA")

pytestmark = [
    pytest.mark.local_data,
    pytest.mark.data_v2,
    pytest.mark.skipif(not DATA, reason="ECEFAST_TEST_DATA is not set"),
    needs_cdo_2_6,
]

# ocean cells, one-cell-wide cells, of which the only link between two basins, cells at the minimum depth (30 m);
# a cell of the north-fold row is held twice in the arrays and counts twice (one Eocene one-cell-wide cell)
EXPECTED = {
    "present": (16733, 11, 8, 54),
    "eocene": (17017, 12, 1, 485),
}


def counts(domain_file: Path) -> tuple[int, int, int, int]:
    with xr.open_dataset(domain_file) as domain:
        ocean = domain["top_level"].squeeze().values > 0
        depth = domain["bathy_metry"].squeeze().values
    edges = geography.side_edges(ocean.shape, geography.T_PIVOT)
    narrow = geography.one_cell_wide(ocean, geography.T_PIVOT)
    segments = geography.label_bodies(narrow, edges)
    links = sum(
        int((segments == s).sum())
        for s in np.unique(segments[segments >= 0])
        if geography.is_only_link(ocean, segments == s, edges)
    )
    return int(ocean.sum()), int(narrow.sum()), links, int((ocean & (depth <= 30.01)).sum())


@pytest.mark.parametrize("period", ["present", "eocene"])
def test_v2_domain_on_real_inputs(tmp_path: Path, period: str) -> None:
    data = Path(DATA)
    coords_ori = data / "data" / "PALEORCA2" / "coords_ori.nc"
    assert coords_ori.is_file(), f"missing test data: {coords_ori}"
    steps = {"generate_subbasins": False, "sections": False}
    config = {
        "schema": 2,
        "data_version": "v2",
        "machine": {"name": "fake", "tmpdir": str(tmp_path / "tmp")},
        "grids": {"nemo": {"coords_ori": str(coords_ori)}},
        "present": {
            "input": str(data / "ECE4-DATA-V3"),
            "output": str(tmp_path / "present"),
            "nemo": {"minimum_depth": 30, "steps": steps},
        },
        "eocene": {
            "input": "{present.input}",
            "herold": str(data / "herold-et-al-2014" / "Supp"),
            "output": str(tmp_path / "eocene"),
            "nemo": {"minimum_depth": 30, "steps": steps},
        },
    }
    config_file = tmp_path / "config.yml"
    config_file.write_text(yaml.safe_dump(config))
    ctx = Context(load_config(config_file), period)
    processor = (PRESENT if period == "present" else EOCENE)["v2"]
    domain_dir = tmp_path / "domain"
    NEMOWorkflow.from_context(ctx, processor, str(domain_dir), FakeBackend()).run()  # includes the mask check

    assert counts(domain_dir / "domain_cfg.nc") == EXPECTED[period]
