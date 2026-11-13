"""The OIFS climate (boundary) file ``ICMCLECE4``: the ``boundary`` process of :class:`~.generator.OIFSData`.

A precomputed ``ICMCLECE4`` is copied when there is one; otherwise ``ICMCLECE4-1990`` is built by merging the
monthly ECMWF climate fields (albedos and leaf area index). Logic of the original script (Paolo Davini, CNR-ISAC,
Apr 2024).
"""

import logging
import os
import shutil

from ecefast.core.cdo import get_cdo
from ecefast.core.io import atomic_write

logger = logging.getLogger(__name__)

# monthly ECMWF climate fields merged into ICMCLECE4 (albedos and leaf area index)
CLIMATE_VARIABLES = ["alb", "aluvp", "aluvd", "alnip", "alnid", "lail", "laih"]


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
