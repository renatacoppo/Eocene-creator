"""The ``domain`` step: install the Eocene NEMO domain and check the vertical grid rule.

``EoceneNEMO`` reads only present-day domains (the PALEORCA2 levels for the ocean initial state). This is
correct only if the Eocene domain has the same vertical grid as the present-day one, so the step stops when
``nav_lev`` or ``e3t_1d`` differ.
"""

import logging
import os
import shutil

import numpy as np
import xarray as xr

from ecefast.core.config import ConfigError
from ecefast.core.io import atomic_write
from ecefast.core.steps import ComponentStep
from ecefast.core.workspace import Context

logger = logging.getLogger(__name__)

# files of a NEMO domain installed into the output tree
DOMAIN_FILES = ["domain_cfg.nc", "maskutil.nc"]

# variables that define the vertical grid; they must be equal in the present-day and Eocene domains
VERTICAL_GRID_VARIABLES = ["nav_lev", "e3t_1d"]


def check_vertical_grid(present: xr.Dataset, eocene: xr.Dataset, present_name: str, eocene_name: str) -> None:
    """Check that two NEMO domains have the same vertical grid.

    The vertical grid is ``nav_lev`` and ``e3t_1d``; their values must be equal.

    Parameters
    ----------
    present : xarray.Dataset
        Present-day ``domain_cfg``.
    eocene : xarray.Dataset
        Eocene ``domain_cfg``.
    present_name, eocene_name : str
        File names shown in the error message.

    Raises
    ------
    ValueError
        If the number of levels or the values of a vertical grid variable differ. The message names both files
        and their number of levels.
    """
    differ = [name for name in VERTICAL_GRID_VARIABLES if not np.array_equal(present[name].values, eocene[name].values)]
    if not differ:
        return
    width = max(len(present_name), len(eocene_name))
    lines = [
        "domain: the Eocene domain does not have the same vertical grid as the present-day one.",
        f"  present-day  {present_name:<{width}}  {present['nav_lev'].size} levels",
        f"  Eocene       {eocene_name:<{width}}  {eocene['nav_lev'].size} levels",
        f"  Different: {', '.join(differ)}.",
        "  EoceneNEMO uses present-day levels; both domains must match.",
    ]
    raise ValueError("\n".join(lines))


class EoceneDomain(ComponentStep):
    """Install the precomputed Eocene NEMO domain and check its vertical grid."""

    name = "domain"
    needs = ["stage"]
    # also reads domain_cfg.nc and maskutil.nc from tools.precomputed.domain (checked in from_context)
    reads = ["{input}/nemo/domain/{nemo_grid}/domain_cfg.nc"]
    writes = [f"{{output}}/nemo/domain/{{nemo_grid}}/{filename}" for filename in DOMAIN_FILES]

    def __init__(self, precomputed_dir: str, input_folder: str, output_folder: str, nemo_grid: str = "PALEORCA2"):
        self.precomputed_dir = precomputed_dir
        self.input_folder = input_folder
        self.output_folder = output_folder
        self.nemo_grid = nemo_grid

    @classmethod
    def from_context(cls, ctx: Context) -> "EoceneDomain":
        precomputed_dir = ctx.config.tools.precomputed.domain
        if precomputed_dir is None:
            raise ConfigError(f"{ctx.config.file}: step 'domain' needs 'tools.precomputed.domain' (the Eocene domain)")
        missing = [f for f in DOMAIN_FILES if not os.path.isfile(os.path.join(precomputed_dir, f))]
        if missing:
            raise FileNotFoundError(
                f"Step 'domain': missing in tools.precomputed.domain ({precomputed_dir}): {', '.join(missing)}"
            )
        return cls(precomputed_dir, ctx.paths.input, ctx.paths.output, ctx.grids.nemo)

    def run(self) -> None:
        """Install the domain, then check the vertical grid rule."""
        self.install_domain()
        self.verify()

    def install_domain(self) -> None:
        """Copy ``domain_cfg.nc`` and ``maskutil.nc`` from the precomputed domain to the output tree."""
        for filename in DOMAIN_FILES:
            src = os.path.join(self.precomputed_dir, filename)
            dst = os.path.join(self.output_folder, "nemo", "domain", self.nemo_grid, filename)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            logger.info(f"Copying {src} to {dst}")
            with atomic_write(dst) as tmp:
                shutil.copy(src, tmp)

    def verify(self) -> None:
        """Check the vertical grid rule on the installed domain.

        Raises
        ------
        ValueError
            If the installed Eocene ``domain_cfg.nc`` and the present-day one in the input tree do not have the
            same vertical grid.
        """
        present_file = os.path.join(self.input_folder, "nemo", "domain", self.nemo_grid, "domain_cfg.nc")
        eocene_file = os.path.join(self.output_folder, "nemo", "domain", self.nemo_grid, "domain_cfg.nc")
        with xr.open_dataset(present_file) as present, xr.open_dataset(eocene_file) as eocene:
            check_vertical_grid(present, eocene, present_file, eocene_file)
        logger.info("Vertical grid of %s matches %s", eocene_file, present_file)
