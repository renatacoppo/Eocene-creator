"""
Function to compute Eocene-specific field:
- lsmgrd reconstruction

Authors
Renata Coppo (CNR-ISAC, Mar 2026)
"""

import numpy as np
import logging
import xarray as xr

loggy = logging.getLogger(__name__)


def lsmgrd(field: xr.Dataset, var=None, landsea=None, **kwargs):
    """
    Reconstruct lsmgrd using Eocene land-sea mask.

    Rules:
    - ocean points -> 0
    - land points  -> 3

    Parameters
    ----------
    field : xr.Dataset
        Dataset containing lsmgrd variable
    landsea : xr.DataArray or xr.Dataset
        Eocene land-sea mask (land > 0.5, ocean <= 0.5)

    Returns
    -------
    xr.Dataset
        Modified dataset with updated lsmgrd field
    """

    # -------------------
    # VALIDATION
    # -------------------
    if landsea is None:
        raise ValueError("You must provide `landsea` (Eocene land-sea mask).")

    if "lsmgrd" not in field:
        raise ValueError("Variable `lsmgrd` not found in input dataset.")

    loggy.info("Starting lsmgrd reconstruction using Eocene mask")

    # -------------------
    # PREPROCESS MASK
    # -------------------
    if not np.all(np.diff(landsea["lat"]) > 0):
        loggy.debug("Sorting landsea latitude to ascending order")
        landsea = landsea.sortby("lat")

    # Extract variable if landsea is a dataset
    if isinstance(landsea, xr.Dataset):
        mask_var = list(landsea.data_vars)[0]
        loggy.debug(f"Extracting mask variable '{mask_var}' from landsea dataset")
        landsea = landsea[mask_var]

    # Interpolate mask to target grid
    loggy.debug("Interpolating Eocene mask to field grid")
    landsea_interp = landsea.interp(
        lat=field["lat"],
        lon=field["lon"],
        method="nearest"
    )

    # Preserve original latitude ordering
    landsea_interp = landsea_interp.reindex(lat=field["lat"])

    da = field["lsmgrd"]

    # -------------------
    # HANDLE TIME DIMENSION
    # -------------------
    if "time" in da.dims:
        ntime = da.sizes["time"]

        if "time" not in landsea_interp.dims:
            loggy.debug("Broadcasting mask across time dimension")
            landsea_interp = (
                landsea_interp
                .expand_dims(time=da.time)
                .broadcast_like(da)
            )

    # -------------------
    # ALIGN DIMENSIONS
    # -------------------
    mask = (landsea_interp > 0.5)

    if set(mask.dims) != set(da.dims):
        mask = mask.broadcast_like(da)

    mask = mask.transpose(*da.dims)

    # -------------------
    # APPLY RULES
    # -------------------
    loggy.info("Applying lsmgrd values: land=3, ocean=0")

    field["lsmgrd"] = xr.where(mask, 3, 0)

    # Preserve attributes
    field["lsmgrd"].attrs = da.attrs

    loggy.info("lsmgrd reconstruction complete.")

    return field