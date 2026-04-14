import os
import xarray as xr
import numpy as np
from cdo import Cdo
import xesmf as xe
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import tempfile
import subprocess
from utils import spectral2gaussian
from eocene.oifs.eoceneOIFS import EoceneOIFS

cdo = Cdo()

# Sanity check helper
def plot_compare(original, modified, title):
    fig, axes = plt.subplots(1, 2, figsize=(12,4), subplot_kw=dict(projection=ccrs.Robinson()))
    for ax, da, label in zip(axes, [original, modified], ["Original", "Modified"]):
        im = da.plot(ax=ax, transform=ccrs.PlateCarree(), cmap="viridis")
        ax.coastlines()
        ax.set_title(label)
        plt.colorbar(im, ax=ax, shrink=0.7)
    plt.suptitle(title)
    plt.show()

def load_grib_var(gribfile, varname, grid="r360x180"):
    """
    Load a GRIB variable and remap it to a regular lat-lon grid
    suitable for plotting.
    """
    with tempfile.NamedTemporaryFile(suffix=".nc", delete=False) as tmp:
        outfile = tmp.name

    cdo.remapnn(
        grid,
        input=f"-selname,{varname} {gribfile}",
        output=outfile,
        options="-f nc4"
    )

    ds = xr.open_dataset(outfile)

    da = list(ds.data_vars.values())[0]

    # drop time dimension if present
    if "time" in da.dims:
        da = da.isel(time=0)

    return da

def load_grib_var_spec(gribfile, varname, grid="r360x181"):
    with tempfile.NamedTemporaryFile(suffix=".nc", delete=False) as tmp:
        outfile = tmp.name

    try:
        # try gridpoint first
        cdo.remapnn(
            grid,
            input=f"-selname,{varname} {gribfile}",
            output=outfile,
            options="-f nc4"
        )
    except Exception:
        # fallback: spectral → gridpoint
        cdo.sp2gp(
            input=f"-selname,{varname} {gribfile}",
            output=outfile,
            options="-f nc4"
        )

    ds = xr.open_dataset(outfile)
    return list(ds.data_vars.values())[0]

def compare_maps(var, origfile, newfile): 
    """Plot original & modified variable on a world map.""" 
    da_orig = load_grib_var_spec(origfile, var) 
    da_new = load_grib_var_spec(newfile, var) 
    proj = ccrs.PlateCarree() 
    fig, ax = plt.subplots(1, 2, figsize=(14, 5), 
                           subplot_kw={"projection": proj}) 
    da_orig.plot(ax=ax[0], transform=proj) 
    ax[0].set_title(f"Original {var}") 
    ax[0].coastlines() 
    da_new.plot(ax=ax[1], transform=proj) 
    ax[1].set_title(f"Eocene {var}") 
    ax[1].coastlines() 
    plt.show()

def compare_maps_cl(var, origfile, newfile):
    """Plot original & modified variable on a world map with robust coordinate handling."""
    da_orig = load_grib_var_spec(origfile, var) 
    da_new = load_grib_var_spec(newfile, var) 

    # Helper to fix coordinates
    def fix_coords(da):
        # Wrap lon from 0-360 → -180..180
        if da.lon.max() > 180:
            da = da.assign_coords(lon=((da.lon + 180) % 360) - 180)
        # Sort lon
        if not np.all(np.diff(da.lon.values) > 0):
            da = da.sortby("lon")
        # Flip lat if decreasing
        if da.lat.values[0] > da.lat.values[-1]:
            da = da.isel(lat=slice(None, None, -1))
        return da

    da_orig = fix_coords(da_orig)
    da_new  = fix_coords(da_new)

    proj = ccrs.PlateCarree()
    fig, ax = plt.subplots(1, 2, figsize=(14, 5), subplot_kw={"projection": proj})

    # Select first time/level if they exist
    def select_2d(da):
        if "time" in da.dims:
            da = da.isel(time=0)
        if "level" in da.dims:
            da = da.isel(level=0)
        return da

    da_orig_2d = select_2d(da_orig)
    da_new_2d  = select_2d(da_new)

    # Force 2D plotting
    for da, ax_, title in zip([da_orig_2d, da_new_2d], ax, ["Original", "Eocene"]):
        da.plot.pcolormesh(
            ax=ax_, x="lon", y="lat", transform=proj, cmap="viridis", shading="auto"
        )
        ax_.set_title(f"{title} {var}")
        ax_.coastlines()

    plt.show()

def plot_spectral_sanity(varname, file, spectral_trunc=63, grid_type="L"):
    """
    Quick sanity check for spectral files.
    
    varname: name of the variable to inspect (e.g., "z")
    file: path to GRIB file
    spectral_trunc: spectral truncation (e.g., 63 for TL63)
    grid_type: "L" or "CO" (linear or complete)
    """

    # Load the spectral file
    ds = xr.open_dataset(file, engine="cfgrib")
    if varname not in ds:
        raise ValueError(f"Variable {varname} not found in {file}")
    da = ds[varname]

    # Inspect dimensions
    print(f"\nVariable '{varname}' dims: {da.dims}")
    print(da)

    # Compute approximate lat/lon for sanity plotting
    nlat = spectral2gaussian(spectral_trunc, grid_type)
    nlon = 2 * nlat
    lat = np.linspace(-90, 90, nlat)
    lon = np.linspace(0, 360, nlon)
    
    # Make a meshgrid
    lon2d, lat2d = np.meshgrid(lon, lat)

    # Simple sanity check: take first time and first level (if present)
    data = da.isel(time=0) if "time" in da.dims else da
    data = data.isel(level=0) if "level" in da.dims else data

    # If spectral resolution > lat/lon, we just tile / truncate for visualization
    # (this is not accurate, just for rough comparison)
    data_plot = np.resize(data.values, (nlat, nlon))

    # Plot
    proj = ccrs.PlateCarree()
    fig, ax = plt.subplots(figsize=(8, 4), subplot_kw={"projection": proj})
    im = ax.pcolormesh(lon2d, lat2d, data_plot, shading="auto", cmap="viridis")
    ax.coastlines()
    ax.set_title(f"Sanity check: {varname}")
    plt.colorbar(im, ax=ax, orientation="vertical", label=varname)
    plt.show()