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
(``oifs/<grid>/<startdate>/``, ``oifs/<grid>/<climate_version>/``), the intermediate files in
``<machine.tmpdir>/present/oifs``. The generation logic is the one of the original script (Paolo Davini, CNR-ISAC, Apr 2024); only its
paths come from the configuration.

The reduced Gaussian grid descriptions (``grids/T<kind><N>.txt``) and the hybrid level coefficients
(``grids/L<levels>.txt``) ship with the package; ``descriptor_generator.py`` and ``convert_aka_bika.py`` are the
scripts that made them.
"""

import logging
import os
import shutil
import subprocess
from pathlib import Path

from ecefast.components.oifs.corners import create_corner_grid
from ecefast.core.cdo import get_cdo
from ecefast.core.config import ConfigError, OIFSDataSteps
from ecefast.core.grib import GRIB2, ecmwf_grid, extract_grid_info, repack_grib_file, unpack_grib_file
from ecefast.core.io import atomic_write
from ecefast.core.steps import PipelineError, missing_inputs_message
from ecefast.core.workspace import Context

logger = logging.getLogger(__name__)

# reduced Gaussian grid descriptions and hybrid level coefficients shipped with the package
GRIDS_DIR = Path(__file__).with_name("grids")
IC_FILES = ["ICMSHECE4INIT", "ICMGGECE4INIT", "ICMGGECE4INIUA"]
# monthly ECMWF climate fields merged into ICMCLECE4 (albedos and leaf area index)
CLIMATE_VARIABLES = ["alb", "aluvp", "aluvd", "alnip", "alnid", "lail", "laih"]
# ecCodes tools called directly by the vertical interpolation
GRIB_TOOLS = ["grib_set", "grib_copy"]

# One line per step of present.oifs.steps, in run order; shown by `ecefast oifs run -h`
STEP_DESCRIPTIONS = {
    "spectral": "truncate the spectral initial state ICMSHECE4INIT to the target resolution",
    "gridpoint": "remap ICMGGECE4INIT and ICMGGECE4INIUA to the target reduced Gaussian grid",
    "boundary": "climate file ICMCLECE4: copy a precomputed one, or merge the ECMWF monthly fields",
}


def generate_spectral_conditions(OIFS_IC, spectral, TMPDIR):
    """
    Generate spectral initial conditions.
    This is done with a clean spectral truncation with cdo.
    Orography is reliable and should not produce Gibbs oscillations.
    """
    # NEW PROCEDURE FOR CY48
    # in cycle all is grb2 so no problem with this
    logger.info("Truncating spectral file ICMSHECE4INIT to %s harmonics", spectral)
    get_cdo().sp2sp(spectral, input=f"{OIFS_IC}/ICMSHECE4INIT", output=f"{TMPDIR}/ICMSHECE4INIT", options=GRIB2)

    # OLD PROCEDURE FOR CY43
    # The file has to be split in two since orography is GRIB1 and the rest is GRIB2
    # grib2file = cdo.sp2sp(spectral, input=f"-selname,lnsp,vo,t,d {OIFS_IC}/ICMSHECE4INIT")
    # gribtemp = cdo.selname("z", input=f"{OIFS_IC}/ICMSHECE4INIT", options="--eccodes")
    # grib1file = cdo.sp2sp(spectral, input=gribtemp, options="--eccodes")
    # subprocess.call(f"cat {grib2file} {grib1file} > {TMPDIR}/ICMSHECE4INIT", shell=True)
    # if clean:
    #    os.remove(grib2file)
    #    os.remove(grib1file)


def generate_gridpoint_conditions(OIFS_IC, target_spectral, TMPDIR, clean=True):
    """
    Generate gridpoint initial conditions.
    Nearest neighbour interpolation is used to remap the data.
    """
    logger.info("Remapping ICMGG gaussian ICs to target grid")
    for file in ["ICMGGECE4INIT", "ICMGGECE4INIUA"]:
        # This is the alternative to be done with remapcon using the grid fils computed with oifs_create_corner.py
        # icmtmp = cdo.remapcon(f"{GRIDS}/{target_spectral}_grid.nc",
        #             input=f"-setgrid,{GRIDS}/{source_spectral}_grid.nc {OIFS_IC}/{file}")
        # cdo.setgrid(f"grids/{target_spectral}.txt", input=icmtmp, output=f"{TMPDIR}/{file}")
        # this is the old version with remapnn
        # cdo.remapnn(f"{GRIDS}/{target_spectral}_grid.nc", input=f"{OIFS_IC}/{file}", output=f"{TMPDIR}/{file}", options="--eccodes")
        gridfile = f"{GRIDS_DIR}/{target_spectral}.txt"
        inputfile = f"{OIFS_IC}/{file}"
        # Split GRIB messages in GRIB1 and GRIB2 to avoid CDO problems in cy48
        grib1, grib2 = unpack_grib_file(inputfile, f"{TMPDIR}/{file}")

        # interpolate
        for grbfile in [grib1, grib2]:
            if os.path.exists(grbfile):
                get_cdo().remapnn(gridfile, input=grbfile, output=f"{grbfile}.remap", options="--eccodes")
        # pack them together
        repack_grib_file(f"{grib1}.remap", f"{grib2}.remap", f"{TMPDIR}/{file}")
        if clean:
            for file in [grib1, grib2]:
                if os.path.exists(file):
                    os.remove(file)
                    os.remove(f"{file}.remap")


def climate_paths(OIFS_BC, target_grid, climate_version, ecmwf_name):
    """Precomputed climate file, and the monthly fields it is built from when it is missing."""
    climfile = f"{OIFS_BC['ready']}/{target_grid}/{climate_version}/ICMCLECE4" if OIFS_BC["ready"] else None
    compute = OIFS_BC["compute"] or "<present.oifs.climate_dir is not set>"
    paths = [f"{compute}/{ecmwf_name}/month_{var}" for var in CLIMATE_VARIABLES]
    return climfile, paths


def generate_boundary_conditions(OIFS_BC, target_grid, climate_version, TMPDIR, BC_TGT, ecmwf_name):
    """
    Generate boundary conditions.
    """
    climfile, paths = climate_paths(OIFS_BC, target_grid, climate_version, ecmwf_name)
    # case when BCs are already available, produced by Klaus Wyser
    if climfile and os.path.exists(climfile):
        logger.info("BCs already exist")
        with atomic_write(f"{BC_TGT}/ICMCLECE4") as tmp:
            shutil.copy(climfile, tmp)
    # This is done with a mergetime of the 7 variables in the ECMWF directory based on a magic command by Klaus Wyser
    else:
        logger.info("Building BCs from %s data", ecmwf_name)
        get_cdo().mergetime(options="-L", input=paths, output=f"{TMPDIR}/temp.grb")
        with atomic_write(f"{BC_TGT}/ICMCLECE4-1990") as tmp:
            get_cdo().settaxis("2021-01-15,00:00:00,1month", input=f"{TMPDIR}/temp.grb", output=tmp)
        os.remove(f"{TMPDIR}/temp.grb")


def vertical_interpolation(TMPDIR, GRIDS, target_spectral, vertical, IC_TGT, do_clean):
    """
    Perform vertical interpolation for spectral and gridpoint data.
    """

    # Procedure for vertical interpolation requires all the data to be in grid point space.
    # This is done by converting the spectral fields to gaussian grids and then moving back them to the spectral space
    # It has been decided to interpolate spectral data (T, D, V) and keep gaussian data (Q, etc.) on the gaussian reduced grid
    # Orography and surface pressure are not touched and attached to the files at the end of the operations
    # A-B coefficients for remapeta are downloaded from ECMWF website and then converted to txt file
    # in CDO-compliant style with convert_aka_bika.py script. These are stored in the grids folder.
    # To set gaussian reduced grids the grid files are produced with descriptor_generator.py and
    # also stored in txt file in the grids folder
    logger.info("Vertical interpolation is necessary")
    logger.info("Select z and lnsp from ICMSHECE4INIT...")
    VERTVALUES = (int(vertical) + 1) * 2
    get_cdo().selname("z", input=f"{TMPDIR}/ICMSHECE4INIT", output=f"{TMPDIR}/orog.grb", options=GRIB2)
    get_cdo().selname("lnsp", input=f"{TMPDIR}/ICMSHECE4INIT", output=f"{TMPDIR}/lnsp.grb", options=GRIB2)

    # Modify lnsp to avoid CDO issues
    subprocess.run(
        [
            "grib_set",
            "-s",
            f"numberOfVerticalCoordinateValues={VERTVALUES}",
            f"{TMPDIR}/lnsp.grb",
            f"{TMPDIR}/lnsp2.grb",
        ],
        check=True,
    )

    # Convert spectral fields to Gaussian grid
    logger.info("Converting ICMSHECE4INIT to Gaussian grid")
    get_cdo().sp2gpl(input=f"{TMPDIR}/ICMSHECE4INIT", output=f"{TMPDIR}/sp2gauss.grb", options=GRIB2)

    # Remap spectral fields to Gaussian reduced grid
    logger.info("Remapping spectral fields from Gaussian to Gaussian reduced")
    remapped = get_cdo().remapcon(f"{GRIDS}/{target_spectral}_grid.nc", input=f"{TMPDIR}/sp2gauss.grb", options=GRIB2)
    get_cdo().setgrid(f"{GRIDS_DIR}/{target_spectral}.txt", input=remapped, output=f"{TMPDIR}/sp2gauss_reduced.grb")

    # Merge files for interpolation
    logger.info("Merging files")
    subprocess.run(
        ["grib_copy", f"{TMPDIR}/ICMGGECE4INIUA", f"{TMPDIR}/sp2gauss_reduced.grb", f"{TMPDIR}/single.grb"], check=True
    )
    # subprocess.call(f"cat {TMPDIR}/ICMGGECE4INIUA {TMPDIR}/sp2gauss_reduced.grb > {TMPDIR}/single.grb", shell=True)

    # Perform hybrid levels interpolation
    logger.info("Remapping vertical on hybrid levels")
    gridfile = f"{GRIDS_DIR}/L{vertical}.txt"
    get_cdo().remapeta(gridfile, input=f"{TMPDIR}/single.grb", output=f"{TMPDIR}/remapped.grb", options=GRIB2)

    # Create INITUA file
    logger.info("Selecting fields to create ICMSHECE4INIUA and setting Gaussian reduced grid")
    with atomic_write(f"{IC_TGT}/ICMGGECE4INIUA") as tmp:
        get_cdo().setgrid(
            f"{GRIDS_DIR}/{target_spectral}.txt",
            input=f"-selname,q,o3,crwc,cswc,clwc,ciwc,cc {TMPDIR}/remapped.grb",
            output=tmp,
            options=GRIB2,
        )

    # Convert back to spectral space
    logger.info("Converting back to spectral (through Gaussian regular) the spectral fields")
    get_cdo().gp2spl(
        input=f"-setgridtype,regular -selname,t,vo,d {TMPDIR}/remapped.grb",
        output=f"{TMPDIR}/spback.grb",
        options="--eccodes",
    )

    # Merge with orography and lnsp to create the final SH file
    logger.info("Merging files and creating the final ICMSHECE4INIT")
    # subprocess.call(f"cat {TMPDIR}/spback.grb {TMPDIR}/lnsp2.grb {TMPDIR}/orog.grb > {IC_TGT}/ICMSHECE4INIT", shell=True)
    with atomic_write(f"{IC_TGT}/ICMSHECE4INIT") as tmp:
        subprocess.run(
            ["grib_copy", f"{TMPDIR}/spback.grb", f"{TMPDIR}/lnsp2.grb", f"{TMPDIR}/orog.grb", tmp], check=True
        )

    # Move the ICMGGECE4INIT file
    with atomic_write(f"{IC_TGT}/ICMGGECE4INIT") as tmp:
        shutil.move(f"{TMPDIR}/ICMGGECE4INIT", tmp)

    # Cleanup temporary files if required
    if do_clean:
        logger.info("Cleaning up")
        for file in [
            "sp2gauss.grb",
            "sp2gauss_reduced.grb",
            "single.grb",
            "remapped.grb",
            "ICMSHECE4INIT",
            "ICMGGECE4INIUA",
            "spback.grb",
            "lnsp.grb",
            "lnsp2.grb",
            "orog.grb",
        ]:
            os.remove(f"{TMPDIR}/{file}")


class OIFSData:
    """The OIFS base data of ``target_grid``, made from ``source_grid`` of the input tree.

    Parameters
    ----------
    input_dir : str
        Input tree holding ``oifs/<source_grid>/<startdate>/``.
    output_dir : str
        Output tree: ``oifs/<target_grid>/<startdate>/`` and ``oifs/<target_grid>/<climate_version>/``.
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

        target = os.path.join(output_dir, "oifs", target_grid)
        self.ic_source = os.path.join(input_dir, "oifs", source_grid, startdate)
        self.ic_target = os.path.join(target, startdate)
        self.bc_target = os.path.join(target, climate_version)
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
        grid_file = str(GRIDS_DIR / f"{self.target_spectral}.txt")
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
                reads.append(str(GRIDS_DIR / f"L{self.vertical}.txt"))
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
                logger.info("Copying files to the target directory")
                for file in IC_FILES:
                    with atomic_write(f"{self.ic_target}/{file}") as tmp:
                        shutil.move(f"{TMPDIR}/{file}", tmp)
            else:
                create_corner_grid(
                    f"{TMPDIR}/ICMGGECE4INIT", self.grid_type, self.spectral, self.corner_grid_file(), TMPDIR
                )
                vertical_interpolation(TMPDIR, TMPDIR, self.target_spectral, self.vertical, self.ic_target, do_clean)

        logger.info("Done")
