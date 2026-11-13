"""Contract between the real DOMAINcfg and the ``fake`` backend (run by hand on ECMWF Atos).

The ``fake`` backend stands in for DOMAINcfg in CI, so its output must have the structure of the real one: every
variable it writes must exist in the real ``domain_cfg_<name>.nc`` / ``mesh_mask_<name>.nc`` with the same
dimensions (names, order, sizes) and dtype, and the 1-D vertical grid must be the same. Values other than the
vertical grid are not compared: the fake does no partial steps, closed seas or north fold (see
``docs/external_tools.rst``).

Run after ``ecefast nemo run -c configs/atos.yml`` with ``machine.name: atos``. Set ``ECEFAST_HPC_DOMAINCFG_DIR``
to the folder holding the namelists and the raw outputs (``<machine.atos.ecearth4_sources>/nemo-4.2/tools/DOMAINcfg``),
then::

    pytest -m hpc tests/hpc

Each ``namelist_cfg_<name>`` with both raw outputs next to it is checked. The fake is built from the same
namelist, so the input files it names must exist.
"""

import os
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from ecefast.periods.eocene.nemo.domain import VERTICAL_GRID_ATOL
from ecefast.tools.ecearth import FakeBackend, output_files, read_namelist

DOMAINCFG_DIR = os.environ.get("ECEFAST_HPC_DOMAINCFG_DIR")

pytestmark = [
    pytest.mark.hpc,
    pytest.mark.skipif(not DOMAINCFG_DIR, reason="ECEFAST_HPC_DOMAINCFG_DIR is not set"),
]

VERTICAL_GRID = ("nav_lev", "e3t_1d")


def built_names(folder: Path) -> list[str]:
    """Bathymetry names with a namelist and both raw DOMAINcfg outputs in ``folder``."""
    names = sorted(p.name.removeprefix("namelist_cfg_") for p in folder.glob("namelist_cfg_*"))
    return [n for n, files in output_files(folder, names).items() if all(f.is_file() for f in files)]


def contract_problems(real: xr.Dataset, fake: xr.Dataset) -> list[str]:
    """Differences in structure between a real and a fake DOMAINcfg dataset; empty if the fake matches."""
    problems = []
    for name, var in fake.variables.items():
        if name not in real.variables:
            problems.append(f"{name}: missing in the real output")
            continue
        ref = real[name]
        if ref.dims != var.dims:
            problems.append(f"{name}: dims {ref.dims} (real) vs {var.dims} (fake)")
        elif ref.shape != var.shape:
            problems.append(f"{name}: shape {ref.shape} (real) vs {var.shape} (fake)")
        if ref.dtype != var.dtype:
            problems.append(f"{name}: dtype {ref.dtype} (real) vs {var.dtype} (fake)")
    return problems


def test_raw_outputs_found() -> None:
    assert built_names(Path(DOMAINCFG_DIR)), f"no namelist_cfg_<name> with both raw outputs in {DOMAINCFG_DIR}"


@pytest.mark.parametrize("name", built_names(Path(DOMAINCFG_DIR)) if DOMAINCFG_DIR else [])
def test_fake_matches_real_domaincfg(name: str) -> None:
    folder = Path(DOMAINCFG_DIR)
    fake_domain, fake_mesh = FakeBackend.build(read_namelist(folder / f"namelist_cfg_{name}"))
    domain_file, mesh_file = output_files(folder, [name])[name]
    with (
        xr.open_dataset(domain_file, decode_cf=False) as real_domain,
        xr.open_dataset(mesh_file, decode_cf=False) as real_mesh,
    ):
        problems = [f"domain_cfg: {p}" for p in contract_problems(real_domain, fake_domain)]
        problems += [f"mesh_mask: {p}" for p in contract_problems(real_mesh, fake_mesh)]
        for var in VERTICAL_GRID:
            if var in real_domain and var in fake_domain:
                diff = float(np.abs(real_domain[var].values - fake_domain[var].values).max())
                if diff > VERTICAL_GRID_ATOL:
                    problems.append(f"domain_cfg: {var} differs by up to {diff:.3g} m")
    assert not problems, f"{name}: the fake backend no longer matches DOMAINcfg:\n" + "\n".join(problems)
