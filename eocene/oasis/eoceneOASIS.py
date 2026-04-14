
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Functions to create boundary conditions for OASIS EOCENE

"""

import os
import logging
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

    def create_rstos(self, constant_sst=290.0):
        """
        Create the rstos file for OASIS boundary conditions
        Simply copy the present-day file, remove sea ice and set a constant SST (to be improved in the future)
        """

        rstos_file = os.path.join(self.idir, "oasis", self.nemo_resolution, "rstos.nc")

        xfield = xr.open_dataset(rstos_file)
        for var in ["OIceFrc", "OIceTck", "OSnwTck", "O_AlbIce", "O_TepIce"]:
            xfield[var].data[:] = 0.0
        xfield["O_SSTSST"].data[:] = constant_sst
        os.makedirs(os.path.join(self.odir, "oasis", self.nemo_resolution), exist_ok=True)
        xfield.to_netcdf(os.path.join(self.odir, "oasis", self.nemo_resolution, "rstos.nc"))
