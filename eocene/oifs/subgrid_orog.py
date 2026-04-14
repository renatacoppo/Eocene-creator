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
import numpy as np
import xarray as xr
import subprocess
import xesmf as xe
import shutil
import tempfile
from cdo import Cdo
cdo = Cdo()

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
    
    # Compute slope
    new_slope = a * sd_eoc + b
    print("Computed new slope (before expanding dims):", new_slope.shape)

    for v in var:
        target = field[v]

        # Ensure time dimension exists and shape matches
        if 'time' in target.dims and len(target.dims) == 3:
            # GRIB has time dimension (1, lat, lon)
            if new_slope.shape != target.shape:
                # expand time dim if missing
                new_slope_exp = new_slope
                if 'time' not in new_slope_exp.dims:
                    new_slope_exp = new_slope_exp.expand_dims('time', axis=0)
                # broadcast to match exactly
                if new_slope_exp.shape != target.shape:
                    new_slope_exp = np.broadcast_to(new_slope_exp, target.shape)
                new_slope_to_assign = new_slope_exp
            else:
                new_slope_to_assign = new_slope
        else:
            new_slope_to_assign = new_slope

        print(f"Assigning slope to variable '{v}' with shape {target.shape}")
        field[v].data = new_slope_to_assign.data

    return field