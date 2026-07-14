"""
Function to compute Eocene-specific field:
- slope from SD

Authors
Renata Coppo (CNR-ISAC, Mar 2026)

"""

import re
import os
import tempfile
import shutil
import logging
import numpy as np
import xarray as xr
import subprocess
import xesmf as xe
import shutil
import tempfile
from cdo import Cdo
cdo = Cdo()
loggy = logging.getLogger(__name__)

def compute_slope (field, var=None, sd_eoc=None, a=4.376786e-05, b=2.476405e-04):
    """
    Replace a GRIB field (slor) using the linear transfer function:
        slope = a * sd + b
    Parameters
    ----------
    grib_field : xarray.DataArray
        The existing slope field from GRIB (ignored except for shape alignment).
    sd_eoc : xarray.DataArray
        Eocene sd_orography on the model grid.
    a, b : float
        Linear transfer coefficients.
    """
    
    loggy.info("Computing slope from sd using linear transfer function")


    # Compute slope
    new_slope = a * sd_eoc + b
    loggy.debug("Computed new slope (before expanding dims):", new_slope.shape)

    for v in var:        
        target = field[v]

        # Ensure time dimension exists and shape matches
        if 'time' in target.dims and len(target.dims) == 3:
            loggy.debug(f"Variable '{v}' has time dimension")

            # GRIB has time dimension (1, lat, lon)
            if new_slope.shape != target.shape:
                # expand time dim if missing
                new_slope_exp = new_slope
                if 'time' not in new_slope_exp.dims:
                    loggy.debug(f"Expanding time dimension for variable '{v}'")
                    new_slope_exp = new_slope_exp.expand_dims('time', axis=0)
                # broadcast to match exactly
                if new_slope_exp.shape != target.shape:
                    loggy.debug(f"Broadcasting slope to match shape {target.shape} for '{v}'")
                    new_slope_exp = np.broadcast_to(new_slope_exp, target.shape)
                new_slope_to_assign = new_slope_exp
            else:
                new_slope_to_assign = new_slope
        else:
            new_slope_to_assign = new_slope

        loggy.debug(f"Assigning slope to variable '{v}' with shape {target.shape}")
        field[v].data = new_slope_to_assign.data

    loggy.info("Slope computation complete")
    
    return field