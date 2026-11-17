"""OIFS base data of a resolution, made from a finer one (the ``oifs`` step of ``ecefast present run``).

Builds the present-day OIFS initial state of ``grids.oifs`` (e.g. TL63L31) from the one of
``present.oifs.source_grid`` (e.g. TL255L91) in the input tree, and optionally the climate (boundary) file:

- ``spectral``: spectral truncation of ``ICMSHECE4INIT`` (``cdo sp2sp``);
- ``gridpoint``: nearest-neighbour remapping of ``ICMGGECE4INIT`` and ``ICMGGECE4INIUA`` to the target reduced
  Gaussian grid, GRIB1 and GRIB2 messages remapped separately;
- ``boundary``: ``ICMCLECE4``, copied from ``present.oifs.precomputed_climate_dir`` if it is there, else built from
  the monthly ECMWF climate fields of ``present.oifs.climate_dir`` (``ICMCLECE4-1990``);
- vertical interpolation (``cdo remapeta``) when the source and target have a different number of levels, with the
  grid with cell corners of the target (``corners``) built first in ``<machine.tmpdir>/present/oifs``.

Inputs exist on ECMWF Atos only. The final files are written under ``present.output`` as in an EC-Earth tree
(``initial_state/oifs/<grid>/<startdate>/``, ``oifs/<grid>/<climate_version>/``), the intermediate files in
``<machine.tmpdir>/present/oifs``. The generation logic is the one of the original script (Paolo Davini, CNR-ISAC, Apr 2024); only its
paths come from the configuration.

This module only orchestrates: it plans, checks and runs the processes, which live in their own modules:

- :mod:`.initial_state`: ``spectral``, ``gridpoint``, then the install or the vertical interpolation;
- :mod:`.climate`: ``boundary``;
- :mod:`.corners`: the grid with cell corners (``corners``);
- :mod:`.grid_files`: the grid descriptions and hybrid coefficients shipped in ``grids/``.
"""

import logging
import os
import shutil

from ecefast.components.oifs.climate import climate_paths, generate_boundary_conditions
from ecefast.components.oifs.corners import create_corner_grid
from ecefast.components.oifs.grid_files import grid_description, hybrid_coefficients
from ecefast.components.oifs.initial_state import (
    GRIB_TOOLS,
    IC_FILES,
    generate_gridpoint_conditions,
    generate_spectral_conditions,
    install_initial_state,
    vertical_interpolation,
)
from ecefast.core.config import ConfigError, OIFSDataSteps
from ecefast.core.grib import ecmwf_grid, extract_grid_info
from ecefast.core.layout import oifs_initial_dir
from ecefast.core.steps import PipelineError, missing_inputs_message
from ecefast.core.workspace import Context

logger = logging.getLogger(__name__)

# One line per step of present.oifs.steps, in run order; shown by `ecefast oifs run -h`
STEP_DESCRIPTIONS = {
    "spectral": "truncate the spectral initial state ICMSHECE4INIT to the target resolution",
    "gridpoint": "remap ICMGGECE4INIT and ICMGGECE4INIUA to the target reduced Gaussian grid",
    "boundary": "climate file ICMCLECE4: copy a precomputed one, or merge the ECMWF monthly fields",
}


class OIFSData:
    """The OIFS base data of ``target_grid``, made from ``source_grid`` of the input tree.

    Parameters
    ----------
    input_dir : str
        Input tree holding ``initial_state/oifs/<source_grid>/<startdate>/``.
    output_dir : str
        Output tree: ``initial_state/oifs/<target_grid>/<startdate>/`` and ``oifs/<target_grid>/<climate_version>/``.
    workdir : str
        Directory of the intermediate files, kept between runs.
    target_grid, source_grid : str
        Grid names like ``TL63L31``.
    startdate, climate_version : str
        Folders of the initial state and of the climate files.
    climate_dir, precomputed_climate_dir : str or None
        Monthly ECMWF climate fields, ready ``ICMCLECE4`` files.
    steps : OIFSDataSteps
        Which steps run.

    Raises
    ------
    ConfigError
        If ``target_grid`` or ``source_grid`` is not a grid name like ``TL63L31``.
    """

    def __init__(
        self,
        input_dir: str,
        output_dir: str,
        workdir: str,
        target_grid: str,
        source_grid: str,
        startdate: str,
        climate_version: str,
        climate_dir: str | None,
        precomputed_climate_dir: str | None,
        steps: OIFSDataSteps,
    ):
        self.target_grid = target_grid
        self.source_grid = source_grid
        self.climate_version = climate_version
        grids = {}
        for key, name in (("grids.oifs.name", target_grid), ("present.oifs.source_grid", source_grid)):
            info = extract_grid_info(name)
            if info is None:
                raise ConfigError(f"'{key}' must be a grid name like TL63L31, got {name!r}")
            grids[key] = info

        # target grid info
        self.grid_type, self.spectral, self.vertical = grids["grids.oifs.name"]
        self.ecmwf_name = str(self.spectral) + ecmwf_grid(self.grid_type)
        self.target_spectral = "T" + self.grid_type + str(self.spectral)
        # source grid info: vertical interpolation when the number of levels differs
        _, _, ic_vertical = grids["present.oifs.source_grid"]
        self.do_vertical = ic_vertical != self.vertical

        self.ic_source = oifs_initial_dir(input_dir, source_grid, startdate)
        self.ic_target = oifs_initial_dir(output_dir, target_grid, startdate)
        self.bc_target = os.path.join(output_dir, "oifs", target_grid, climate_version)
        self.workdir = workdir
        self.oifs_bc = {"ready": precomputed_climate_dir, "compute": climate_dir}
        self.steps = steps

    @classmethod
    def from_context(cls, ctx: Context) -> "OIFSData":
        """Build it for the running period: section ``<period>.oifs``, ``grids.oifs``, ``machine.tmpdir``.

        Raises
        ------
        ConfigError
            If the period has no ``oifs`` section, or see :class:`OIFSData`.
        """
        oifs = ctx.section.oifs
        if oifs is None:
            raise ConfigError(f"{ctx.config.file}: the OIFS generator needs a '{ctx.period}.oifs' section")
        grid = ctx.config.grids.oifs
        workdir = ctx.tmpdir("oifs")
        ctx.check_writable(workdir, "oifs")
        ctx.check_writable(ctx.section.output, "oifs")
        return cls(
            ctx.section.input,
            ctx.section.output,
            workdir,
            grid.name,
            oifs.source_grid,
            grid.startdate,
            grid.climate_version,
            oifs.climate_dir,
            oifs.precomputed_climate_dir,
            oifs.steps,
        )

    def corner_grid_file(self) -> str:
        """The grid with cell corners of the target, built in ``workdir`` for the vertical interpolation."""
        return os.path.join(self.workdir, f"{self.target_spectral}_grid.nc")

    def final_files(self) -> list[str]:
        """The files the enabled steps write into the output tree."""
        return [path for _, _, writes in self.plan() for path in writes if not path.startswith(self.workdir + os.sep)]

    def plan(self) -> list[tuple[str, list[str], list[str]]]:
        """The enabled steps in run order, each with the files it reads and writes.

        Intermediate files in ``workdir`` written by an earlier step count as reads of the later one, so a step can
        run alone on the ``workdir`` of an earlier run.

        Returns
        -------
        list of (str, list of str, list of str)
            Step name, paths it reads, paths it writes.
        """
        work, ic_target, steps = self.workdir, self.ic_target, self.steps
        grid_file = str(grid_description(self.target_spectral))
        plan = []
        if steps.spectral:
            plan.append(
                ("spectral", [f"{self.ic_source}/ICMSHECE4INIT"], [f"{work}/ICMSHECE4INIT"]),
            )
        if steps.gridpoint:
            sources = [f"{self.ic_source}/{f}" for f in ("ICMGGECE4INIT", "ICMGGECE4INIUA")]
            plan.append(
                ("gridpoint", [*sources, grid_file], [f"{work}/{f}" for f in ("ICMGGECE4INIT", "ICMGGECE4INIUA")])
            )
        if steps.boundary:
            climfile, paths = climate_paths(self.oifs_bc, self.target_grid, self.climate_version, self.ecmwf_name)
            if climfile and os.path.exists(climfile):
                plan.append(("boundary", [climfile], [f"{self.bc_target}/ICMCLECE4"]))
            else:
                plan.append(("boundary", paths, [f"{self.bc_target}/ICMCLECE4-1990"]))
        # the initial-state files go to the output when spectral or boundary is on, as in the original script
        if steps.spectral or steps.boundary:
            name = "vertical" if self.do_vertical else "install"
            reads = [f"{work}/{f}" for f in IC_FILES]
            if self.do_vertical:
                # remapcon needs the cell corners, which the grid description of grids/ does not have
                plan.append(("corners", [f"{work}/ICMGGECE4INIT"], [self.corner_grid_file()]))
                reads += [self.corner_grid_file(), grid_file]
                reads.append(str(hybrid_coefficients(self.vertical)))
            plan.append((name, reads, [f"{ic_target}/{f}" for f in IC_FILES]))
        return plan

    def check(self) -> None:
        """Check that every file an enabled step reads exists or is written by an earlier step.

        Raises
        ------
        PipelineError
            Listing every missing input at once, or naming the ecCodes tools missing for the vertical
            interpolation.
        """
        missing, written = [], set()
        for name, reads, writes in self.plan():
            missing += [(name, path) for path in reads if path not in written and not os.path.exists(path)]
            written.update(writes)
        if missing:
            raise PipelineError(missing_inputs_message(missing))
        tools = [tool for tool in GRIB_TOOLS if shutil.which(tool) is None]
        if self.do_vertical and (self.steps.spectral or self.steps.boundary) and tools:
            raise PipelineError(f"The vertical interpolation needs the ecCodes tools, not found: {', '.join(tools)}")

    def run(self, dry_run: bool = False) -> None:
        """Check the inputs of the enabled steps, then run them (the steps of the original script, in its order).

        Parameters
        ----------
        dry_run : bool
            Only check the inputs and log the plan; write nothing.
        """
        self.check()
        if dry_run:
            logger.info("Dry run: nothing is written. %s from %s. Plan:", self.target_grid, self.source_grid)
            for name, _, writes in self.plan():
                logger.info("  %s", name)
                for path in writes:
                    logger.debug("      -> %s", path)
            return

        for d in [self.ic_target, self.bc_target, self.workdir]:
            os.makedirs(d, exist_ok=True)
        TMPDIR, steps = self.workdir, self.steps
        # intermediate files stay in workdir (the original script kept them unless --clean)
        do_clean = False

        if steps.spectral:
            generate_spectral_conditions(self.ic_source, self.spectral, TMPDIR)

        # Gridpoint generation
        if steps.gridpoint:
            generate_gridpoint_conditions(self.ic_source, self.target_spectral, TMPDIR, clean=do_clean)

        # Boundary condition generation
        if steps.boundary:
            generate_boundary_conditions(
                self.oifs_bc, self.target_grid, self.climate_version, TMPDIR, self.bc_target, self.ecmwf_name
            )

        # move the files to the target directory
        if steps.spectral or steps.boundary:
            if not self.do_vertical:
                install_initial_state(TMPDIR, self.ic_target)
            else:
                create_corner_grid(
                    f"{TMPDIR}/ICMGGECE4INIT", self.grid_type, self.spectral, self.corner_grid_file(), TMPDIR
                )
                vertical_interpolation(TMPDIR, TMPDIR, self.target_spectral, self.vertical, self.ic_target, do_clean)

        logger.info("Done")
