#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Functions to create boundary conditions for OASIS EOCENE

"""

import os
import logging
import xarray as xr

from ecefast.core.io import atomic_write
from ecefast.core.steps import ComponentStep
from ecefast.core.workspace import Context

logger = logging.getLogger(__name__)


class EoceneOASIS(ComponentStep):
    """Write the OASIS restart rstos.nc: no sea ice, constant SST."""

    name = "oasis"
    needs = ["stage"]
    reads = ["{inputs.ece4_data}/oasis/{nemo.grid}/rstos.nc"]
    writes = ["{eocene.output_dir}/oasis/{nemo.grid}/rstos.nc"]

    def __init__(self, idir, odir, nemo_resolution="PALEORCA2", constant_sst=290.0):

        self.idir = idir
        self.odir = odir

        if not os.path.exists(self.idir):
            raise FileNotFoundError(f"Input data not found at {self.idir}")

        self.nemo_resolution = nemo_resolution
        self.constant_sst = constant_sst

    @classmethod
    def from_context(cls, ctx: Context) -> "EoceneOASIS":
        return cls(
            idir=ctx.config.inputs.ece4_data,
            odir=ctx.config.eocene.output_dir,
            nemo_resolution=ctx.config.nemo.grid,
            constant_sst=ctx.config.eocene.oasis.constant_sst,
        )

    def run(self) -> None:
        """Create the OASIS modifications (was ``cli/eocene.py:run_oasis``)."""
        logger.info("Starting OASIS modifications")
        self.create_rstos(constant_sst=self.constant_sst)

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
        with atomic_write(os.path.join(self.odir, "oasis", self.nemo_resolution, "rstos.nc")) as tmp:
            xfield.to_netcdf(tmp)
