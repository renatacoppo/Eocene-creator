"""
Function to compute Eocene-specific field:
- albedo transformations

Authors
Renata Coppo (CNR-ISAC, Mar 2026)

"""

import re
import os
import tempfile
import shutil
import numpy as np
import logging
import xarray as xr
import subprocess
import xesmf as xe
import shutil
import tempfile
from cdo import Cdo
cdo = Cdo()
loggy = logging.getLogger(__name__)

def albedo(field: xr.Dataset, var=None, lsm_present=None, landsea=None, **kwargs):
    """
    Apply both:
    Land-sea mask-based albedo reconstruction using `lsm_present`
    Eocene land-sea mask adjustment (albedo=0.05, LAI=NaN over ocean)
    """

    # VALIDATION
    if lsm_present is None:
        raise ValueError("You must provide `lsm_present` (present-day land-sea mask).")
    if landsea is None:
        raise ValueError("You must provide `landsea` (Eocene land-sea mask).")

    loggy.info("Starting Albedo reconstruction + Eocene mask application")

    # PREPROCESS MASKS
    # Ensure ascending latitude
    if not np.all(np.diff(lsm_present['lat']) > 0):
        loggy.debug("Sorting lsm_present latitude to ascending order")
        lsm_present = lsm_present.sortby('lat')
    if not np.all(np.diff(landsea['lat']) > 0):
        loggy.debug("Sorting landsea latitude to ascending order")
        landsea = landsea.sortby('lat')

    # Extract variable if landsea is a dataset
    if isinstance(landsea, xr.Dataset):
        mask_var = list(landsea.data_vars)[0]
        loggy.debug(f"Extracting mask variable '{mask_var}' from landsea dataset")
        landsea = landsea[mask_var]

    # Interpolate Eocene mask to field grid
    loggy.debug("Interpolating Eocene mask to field grid")
    landsea_interp = landsea.interp(lat=field["lat"], lon=field["lon"], method="nearest")

    # Match time dimension if needed
    if "time" in field.dims:
        ntime = field.dims["time"]
        loggy.debug(f"Field has time dimension: {ntime} steps")
        if "time" not in landsea_interp.dims or landsea_interp.sizes.get("time", 1) != ntime:
            loggy.debug("Broadcasting landsea mask across time dimension")
            landsea_interp = landsea_interp.expand_dims("time").broadcast_like(field.isel(time=slice(0, 1)))
            landsea_interp = xr.concat([landsea_interp] * ntime, dim="time")

    # Boolean masks
    loggy.debug("Creating boolean masks")
    present_mask = (lsm_present.broadcast_like(field)) > 0.5
    eocene_mask = (landsea_interp > 0.5).transpose(*field[list(field.data_vars)[0]].dims)

    # APPLY ALBEDO RECONSTRUCTION
    loggy.info("Applying zonal-mean-based albedo reconstruction")
    for v in field.data_vars:
        loggy.debug(f"Processing variable: {v}")
        da = field[v]

        # Apply the present-day mask (land only)
        masked = da.where(present_mask)

        # Sort latitude ascending
        flip = False
        if da["lat"].values[0] > da["lat"].values[-1]:
            loggy.debug(f"Latitude descending detected for {v}, flipping")
            da = da.sortby("lat")
            masked = masked.sortby("lat")
            flip = True

        # Zonal mean over land
        zonal_mean = masked.mean(dim="lon", skipna=True)
        zonal_mean_filled = zonal_mean.interpolate_na(dim="lat", method="nearest")
        da_recon = zonal_mean_filled.broadcast_like(da)

        # Polar band filling
        lat = da["lat"]
        if (lat < -52).any():
            loggy.debug(f"Applying southern polar filling for {v}")
            mean_s = da_recon.sel(lat=lat.where((lat >= -52) & (lat <= -46), drop=True)).mean(dim=("lat", "lon"), skipna=True)
            da_recon = da_recon.where(~(lat < -52), other=mean_s)
        if (lat > 75).any():
            loggy.debug(f"Applying northern polar filling for {v}")
            mean_n = da_recon.sel(lat=lat.where((lat >= 70) & (lat <= 75), drop=True)).mean(dim=("lat", "lon"), skipna=True)
            da_recon = da_recon.where(~(lat > 75), other=mean_n)

        if flip:
            da_recon = da_recon.sortby("lat", ascending=False)

        # Replace variable data
        field[v].data = da_recon.data

    loggy.info("Albedo reconstruction complete.")

    # APPLY EOCENE MASK RULES
    loggy.info("Applying Eocene land-sea mask rules")

    albedo_diffuse_vars = ["al", "aluvp", "aluvd", "alnip", "alnid"]
    albedo_direct_vars = ["aluvpi", "aluvpv", "aluvpg", "alnipi", "alnipv", "alnipg"]
    lai_vars = ["lai_lv", "lai_hv"]
    bare_soil_vars = ["code117", "code118", "code119", "code120"]

    for v in albedo_diffuse_vars:
        if v in field:
            loggy.debug(f"Setting diffuse albedo over ocean for {v}")
            field[v].data = np.where(eocene_mask, field[v].data, 0.05)
    
    for v in albedo_direct_vars:
        if v in field:
            loggy.debug(f"Zeroing direct albedo over ocean for {v}")
            field[v].data = np.where(eocene_mask, field[v].data, 0)

    for v in lai_vars:
        if v in field:
            loggy.debug(f"Zeroing LAI over ocean for {v}")
            field[v].data = np.where(eocene_mask, field[v].data, 0)

    for v in bare_soil_vars:
        if v in field:
            loggy.debug(f"Zeroing bare soil vars over ocean for {v}")
            field[v].data = np.where(eocene_mask, field[v].data, 0)

    loggy.info("Eocene land-sea mask applied successfully.")
    loggy.info("Combined modification complete, GRIB structure preserved.")
    return field