"""Generic GRIB and OIFS grid helpers shared by the OIFS generator and the Eocene workflow.

GRIB files are handled with the ecCodes command-line tools (``grib_copy``, ``grib_count``), which must be on
``PATH``. Grid strings follow the EC-Earth4 naming, e.g. ``TL63L31`` or ``TCO95L91``.
"""

import logging
import os
import re
import subprocess

logger = logging.getLogger(__name__)

# CDO output options: GRIB2, GRIB1 and NetCDF4, all through ecCodes
GRIB2 = "-f grb2 --eccodes"
GRIB1 = "-f grb1 --eccodes"
NC4 = "-f nc4 --eccodes"


def unpack_grib_file(inputfile, tmpfile):
    """
    Unpack a GRIB file using grib_copy.
    This is used to split the GRIB messages into GRIB1 and GRIB2.
    """
    logger.debug(f"Unpacking GRIB file {inputfile} into {tmpfile}_grib1 and {tmpfile}_grib2")
    subprocess.run(["grib_copy", "-w", "edition=1", inputfile, f"{tmpfile}_grib1"], check=True)
    subprocess.run(["grib_copy", "-w", "edition=2", inputfile, f"{tmpfile}_grib2"], check=True)
    return f"{tmpfile}_grib1", f"{tmpfile}_grib2"


def repack_grib_file(grib1, grib2, outputfile, clean=True):
    """
    Repack a GRIB file using grib_copy.
    This is used to merge the GRIB1 and GRIB2 files back together.
    """
    if os.path.exists(outputfile):
        os.remove(outputfile)
    if not os.path.exists(grib1):
        logger.debug(f"Repacking GRIB file {grib2} into {outputfile}")
        subprocess.run(["grib_copy", grib2, outputfile], check=True)
    elif not os.path.exists(grib2):
        logger.debug(f"Repacking GRIB file {grib1} into {outputfile}")
        subprocess.run(["grib_copy", grib1, outputfile], check=True)
    else:
        logger.debug(f"Repacking GRIB file {grib1} and {grib2} into {outputfile}")
        subprocess.run(["grib_copy", grib1, grib2, outputfile], check=True)

    # cleanup
    if clean:
        for file in [grib1, grib2]:
            if os.path.exists(file):
                logger.debug(f"Removing temporary file {file}")
                os.remove(file)


def detect_grib_version(filepath):
    """Detect the GRIB version of a file."""
    with open(filepath, "rb") as f:
        header = f.read(8)  # read enough bytes
        if header[:4] != b"GRIB":
            return None  # Not a GRIB file
        return header[7]  # Edition number (1 or 2)


def count_grib_messages(inputfile):
    """Return the number of messages in a GRIB file."""
    result = subprocess.run(["grib_count", inputfile], check=True, capture_output=True, text=True)
    n = int(result.stdout.strip())
    logger.debug(f"{inputfile} contains {n} messages")
    return n


def ecmwf_grid(kind):
    """Get the info on the grid to find the right ECMWF file"""

    ecmwf_name = {"L": "l_2", "CO": "_4", "Q": "_2"}

    return ecmwf_name[kind.upper()]


def extract_grid_info(string):
    """Extract grid info from a string"""
    string = string.upper()
    pattern = r"T(CO|L)(\d+)L(\d+)"
    match = re.match(pattern, string)
    if match:
        grid_type = match.group(1)
        spectral = int(match.group(2))
        num_levels = int(match.group(3))
        return grid_type, spectral, num_levels

    return None


def spectral2gaussian(spectral, kind):
    """Convert spectral resolution to gaussian"""
    if kind.upper() == "CO":
        return int(spectral) + 1
    if kind == "L":
        return int((int(spectral) + 1) / 2)

    raise ValueError("Unknown grid type")
