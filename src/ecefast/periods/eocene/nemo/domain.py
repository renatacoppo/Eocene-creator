"""The ``domain`` step: install the Eocene NEMO domain and check the vertical grid rule.

``eocene.nemo.domain`` says where the domain comes from: a directory holding its ``domain_cfg.nc`` and
``maskutil.nc`` (e.g. the domain built on Atos, copied to a laptop), or ``build``: the step first builds it with
the NEMO domain pipeline and the Eocene bathymetry (steps ``eocene.nemo.steps``), intermediate and final files in
``<machine.tmpdir>/eocene/nemo``, which needs DOMAINcfg (``machine.name: atos``, or ``fake`` in tests).

``EoceneNEMO`` reads only present-day domains (the PALEORCA2 levels for the ocean initial state). This is
correct only if the Eocene domain has the same vertical grid as the present-day one, so the step stops when
``nav_lev`` or ``e3t_1d`` differ.
"""

import logging
import os
import shutil

import numpy as np
import xarray as xr

from ecefast.components.nemo.domain.pipeline import NEMOWorkflow
from ecefast.core.config import BUILD
from ecefast.core.io import atomic_write
from ecefast.core.steps import ComponentStep, PipelineError
from ecefast.core.workspace import Context
from ecefast.periods.eocene.bathymetry import EoceneBathymetry
from ecefast.tools.ecearth import get_backend

logger = logging.getLogger(__name__)

# files of a NEMO domain installed into the output tree
DOMAIN_FILES = ["domain_cfg.nc", "maskutil.nc"]

# variables that define the vertical grid; they must be equal in the present-day and Eocene domains
VERTICAL_GRID_VARIABLES = ["nav_lev", "e3t_1d"]
# Absolute tolerance (m) of the vertical grid check: floating-point rounding between DOMAINcfg builds and the fake
# backend (about 1e-12 m observed on PALEORCA2 L31), far below any real change of the vertical grid. Agreed by the
# authors in task 5.2 (#37).
VERTICAL_GRID_ATOL = 1e-6


def check_vertical_grid(present: xr.Dataset, eocene: xr.Dataset, present_name: str, eocene_name: str) -> None:
    """Check that two NEMO domains have the same vertical grid.

    The vertical grid is ``nav_lev`` and ``e3t_1d``. Both domains must have the same number of levels, and the
    values must agree within :data:`VERTICAL_GRID_ATOL` (m), a tolerance for floating-point rounding only.

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
        If the number of levels differs, or a vertical grid variable differs by more than the tolerance. The
        message names both files, their number of levels, the variables that differ and, for the same number of
        levels, the maximum absolute difference.
    """
    differ = []
    for name in VERTICAL_GRID_VARIABLES:
        a, b = present[name].values, eocene[name].values
        if a.shape != b.shape:
            differ.append(name)
        elif not np.allclose(a, b, rtol=0, atol=VERTICAL_GRID_ATOL):
            diff = np.max(np.abs(a.astype("float64") - b.astype("float64")))
            differ.append(f"{name} (max absolute difference {diff:.3g} m, tolerance {VERTICAL_GRID_ATOL:g} m)")
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
    """Install the Eocene NEMO domain (eocene.nemo.domain: a directory, or build) and check its vertical grid."""

    name = "domain"
    component = "nemo"
    needs = ["stage"]
    # It also reads domain_cfg.nc and maskutil.nc from the directory of eocene.nemo.domain; with build it runs the
    # NEMO domain pipeline first, which reads and writes in machine.tmpdir. Neither fits a class-level list that
    # cannot depend on eocene.nemo.domain, so both are checked in from_context, which the runner calls for every
    # selected step before the first one runs.
    reads = ["{input}/nemo/domain/{grids.nemo.name}/domain_cfg.nc"]
    writes = [f"{{output}}/nemo/domain/{{grids.nemo.name}}/{filename}" for filename in DOMAIN_FILES]

    def __init__(
        self,
        domain_dir: str,
        input_folder: str,
        output_folder: str,
        nemo_grid: str = "PALEORCA2",
        workflow: NEMOWorkflow | None = None,
    ):
        """
        Parameters
        ----------
        domain_dir : str
            Directory holding the Eocene ``domain_cfg.nc`` and ``maskutil.nc`` to install.
        input_folder, output_folder : str
            Input tree (present-day domain) and output tree.
        nemo_grid : str
            NEMO grid, directory under ``nemo/domain/``.
        workflow : NEMOWorkflow, optional
            Pipeline that builds the domain into ``domain_dir`` first; ``None`` for a precomputed domain.
        """
        self.domain_dir = domain_dir
        self.input_folder = input_folder
        self.output_folder = output_folder
        self.nemo_grid = nemo_grid
        self.workflow = workflow

    @classmethod
    def from_context(cls, ctx: Context) -> "EoceneDomain":
        section = ctx.section
        args = (section.input, section.output, ctx.config.grids.nemo.name)
        if section.nemo.domain != BUILD:
            domain_dir = section.nemo.domain
            missing = [f for f in DOMAIN_FILES if not os.path.isfile(os.path.join(domain_dir, f))]
            if missing:
                raise PipelineError(
                    f"Step 'domain': missing in eocene.nemo.domain ({domain_dir}): {', '.join(missing)}. "
                    "Build it on Atos (eocene.nemo.domain: build) and copy its <eocene.output>/nemo/domain/<grid> here."
                )
            return cls(domain_dir, *args)

        # build (the config refuses it with machine.name: local): the final files go to the tmpdir, then installed
        domain_dir = os.path.join(ctx.tmpdir("nemo"), "domain", ctx.config.grids.nemo.name)
        workflow = NEMOWorkflow.from_context(ctx, EoceneBathymetry, domain_dir, get_backend(ctx.config))
        try:
            workflow.check()
        except PipelineError as e:
            raise PipelineError(f"Step 'domain' builds the Eocene domain with the NEMO domain pipeline. {e}") from e
        return cls(domain_dir, *args, workflow=workflow)

    def run(self) -> None:
        """Build the domain if there is a workflow, install it, then check the vertical grid rule."""
        if self.workflow is not None:
            self.build_domain()
        self.install_domain()
        self.verify()

    def build_domain(self) -> None:
        """Run the NEMO domain pipeline for the Eocene bathymetry and check that it wrote the domain files.

        Raises
        ------
        FileNotFoundError
            If ``domain_cfg.nc`` or ``maskutil.nc`` is missing afterwards (e.g. the ``domain_cfg`` or
            ``generate_mask`` step of ``eocene.nemo.steps`` is off and they were not built before).
        """
        logger.info("Building the Eocene domain on machine '%s'", self.workflow.backend.name)
        self.workflow.run()
        missing = [f for f in DOMAIN_FILES if not os.path.isfile(os.path.join(self.domain_dir, f))]
        if missing:
            raise FileNotFoundError(
                f"Step 'domain': the NEMO domain pipeline did not write {', '.join(missing)} in {self.domain_dir}. "
                "Turn on the domain_cfg and generate_mask steps of eocene.nemo.steps."
            )

    def install_domain(self) -> None:
        """Copy ``domain_cfg.nc`` and ``maskutil.nc`` from the Eocene domain directory to the output tree."""
        for filename in DOMAIN_FILES:
            src = os.path.join(self.domain_dir, filename)
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
