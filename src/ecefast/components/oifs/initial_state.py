"""The OIFS initial state of a resolution, made from a finer one: the processes of :class:`~.generator.OIFSData`.

In run order:

1. :func:`generate_spectral_conditions`: spectral truncation of ``ICMSHECE4INIT`` (``cdo sp2sp``);
2. :func:`generate_gridpoint_conditions`: nearest-neighbour remapping of ``ICMGGECE4INIT`` and ``ICMGGECE4INIUA``;
3. :func:`install_initial_state` when the source and target have the same number of levels, else
   :func:`vertical_interpolation` (``cdo remapeta``), which needs the grid with cell corners of
   :func:`ecefast.components.oifs.corners.create_corner_grid`.

Steps 1 and 2 write into the work directory; step 3 moves or interpolates the files into the output tree.
The generation logic is the one of the original script (Paolo Davini, CNR-ISAC, Apr 2024).
"""

import logging
import os
import shutil
import subprocess

from ecefast.components.oifs.grid_files import grid_description, hybrid_coefficients
from ecefast.core.cdo import get_cdo
from ecefast.core.grib import GRIB2, repack_grib_file, unpack_grib_file
from ecefast.core.io import atomic_write

logger = logging.getLogger(__name__)

IC_FILES = ["ICMSHECE4INIT", "ICMGGECE4INIT", "ICMGGECE4INIUA"]
# ecCodes tools called directly by the vertical interpolation
GRIB_TOOLS = ["grib_set", "grib_copy"]


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
        gridfile = str(grid_description(target_spectral))
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


def install_initial_state(TMPDIR: str, IC_TGT: str) -> None:
    """Move the initial-state files from the work directory to the output tree (no vertical interpolation)."""
    logger.info("Copying files to the target directory")
    for file in IC_FILES:
        with atomic_write(f"{IC_TGT}/{file}") as tmp:
            shutil.move(f"{TMPDIR}/{file}", tmp)


def vertical_interpolation(TMPDIR, GRIDS, target_spectral, vertical, IC_TGT, do_clean):
    """
    Perform vertical interpolation for spectral and gridpoint data.
    """

    # Procedure for vertical interpolation requires all the data to be in grid point space.
    # This is done by converting the spectral fields to gaussian grids and then moving back them to the spectral space
    # It has been decided to interpolate spectral data (T, D, V) and keep gaussian data (Q, etc.) on the gaussian reduced grid
    # Orography and surface pressure are not touched and attached to the files at the end of the operations
    # A-B coefficients for remapeta come from the ECMWF model level tables, converted to CDO-compliant txt files
    # by grid_files.write_hybrid_coefficients. To set gaussian reduced grids the grid files are produced by
    # grid_files.write_grid_descriptions. Both are stored in the grids folder.
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
    get_cdo().setgrid(str(grid_description(target_spectral)), input=remapped, output=f"{TMPDIR}/sp2gauss_reduced.grb")

    # Merge files for interpolation
    logger.info("Merging files")
    subprocess.run(
        ["grib_copy", f"{TMPDIR}/ICMGGECE4INIUA", f"{TMPDIR}/sp2gauss_reduced.grb", f"{TMPDIR}/single.grb"], check=True
    )
    # subprocess.call(f"cat {TMPDIR}/ICMGGECE4INIUA {TMPDIR}/sp2gauss_reduced.grb > {TMPDIR}/single.grb", shell=True)

    # Perform hybrid levels interpolation
    logger.info("Remapping vertical on hybrid levels")
    gridfile = str(hybrid_coefficients(vertical))
    get_cdo().remapeta(gridfile, input=f"{TMPDIR}/single.grb", output=f"{TMPDIR}/remapped.grb", options=GRIB2)

    # Create INITUA file
    logger.info("Selecting fields to create ICMSHECE4INIUA and setting Gaussian reduced grid")
    with atomic_write(f"{IC_TGT}/ICMGGECE4INIUA") as tmp:
        get_cdo().setgrid(
            str(grid_description(target_spectral)),
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
