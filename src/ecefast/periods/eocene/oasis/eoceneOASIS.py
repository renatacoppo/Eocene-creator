#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Functions to create boundary conditions for OASIS EOCENE

"""

import os
import logging
import xarray as xr

from ecefast.core.io import atomic_write
from ecefast.core.layout import oasis_restart_dir
from ecefast.core.steps import ComponentStep
from ecefast.core.workspace import Context

logger = logging.getLogger(__name__)


class EoceneOASIS(ComponentStep):
    """Write the OASIS restart rstos.nc: no sea ice, constant SST."""

    name = "oasis"
    component = "oasis"
    needs = ["stage"]
    # initial_state/oasis/<grid>/default/rstos.nc; the old path oasis/<grid>/rstos.nc is a link to it
    reads = [oasis_restart_dir("{input}", "{grids.nemo.name}") + "/rstos.nc"]
    writes = [oasis_restart_dir("{output}", "{grids.nemo.name}") + "/rstos.nc"]

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
            idir=ctx.section.input,
            odir=ctx.section.output,
            nemo_resolution=ctx.config.grids.nemo.name,
            constant_sst=ctx.section.oasis.constant_sst,
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

        rstos_file = os.path.join(oasis_restart_dir(self.idir, self.nemo_resolution), "rstos.nc")

        xfield = xr.open_dataset(rstos_file)
        for var in ["OIceFrc", "OIceTck", "OSnwTck", "O_AlbIce", "O_TepIce"]:
            xfield[var].data[:] = 0.0
        xfield["O_SSTSST"].data[:] = constant_sst
        output_dir = oasis_restart_dir(self.odir, self.nemo_resolution)
        os.makedirs(output_dir, exist_ok=True)
        with atomic_write(os.path.join(output_dir, "rstos.nc")) as tmp:
            xfield.to_netcdf(tmp)
