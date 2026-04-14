
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Functions to create boundary conditions for OASIS EOCENE

"""

import os
import logging
import numpy as np
import xarray as xr

loggy = logging.getLogger(__name__)

class EoceneOASIS():
    """Class to create OASIS boundary conditions for EOCENE"""

    def __init__(self, idir, odir, nemo_resolution="PALEORCA2"):

        self.idir = idir
        self.odir = odir

        if not os.path.exists(self.idir):
            raise FileNotFoundError(f"Input data not found at {self.idir}")

        self.nemo_resolution = nemo_resolution

    def create_rstos(self):
        """
        Create the rstos file for OASIS boundary conditions
        Simply copy the present-day file, set nan for the zero and fill missing values with 273.15 K for the SST field
        """

        rstos_file = os.path.join(self.idir, "oasis", self.nemo_resolution, "rstos.nc")

        xfield = xr.open_dataset(rstos_file)
        #xfield['O_SSTSST'] = xr.where(xfield['O_SSTSST'] == 0, np.nan, xfield['O_SSTSST'])
        #xfield['O_SSTSST'] = xr.where(np.isnan(xfield['O_SSTSST']), 273.15, xfield['O_SSTSST'])
        da = xfield["O_SSTSST"].where(xfield["O_SSTSST"] != 0)
        xfield["O_SSTSST"] = da.fillna(273.15)
        os.makedirs(os.path.join(self.odir, "oasis", self.nemo_resolution), exist_ok=True)
        xfield.to_netcdf(os.path.join(self.odir, "oasis", self.nemo_resolution, "rstos.nc.new"))
