
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Functions to create boundary conditions for NEMO EOCENE

"""

import os
import logging
import numpy as np
import xarray as xr
import pandas as pd
from scipy.spatial import cKDTree
from cdo import Cdo

cdo = Cdo()
loggy = logging.getLogger(__name__)

def _lonlat_to_xyz(lon, lat):
    """Convert lon/lat in degrees to unit-sphere cartesian coordinates."""
    lon, lat = np.deg2rad(lon), np.deg2rad(lat)
    return np.column_stack([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)])

def present_day_ocean_mask(domain_file, lon, lat, nz):
    """
    3D present-day ocean mask (z, y, x) on a target lon/lat grid,
    from the bottom_level of a present-day NEMO domain (nearest neighbour).
    Level k (0-based) is ocean where bottom_level >= k+1.
    """
    domain = xr.open_dataset(domain_file).squeeze("time_counter", drop=True)
    bottom = domain["bottom_level"].values.ravel()
    tree = cKDTree(_lonlat_to_xyz(domain["glamt"].values.ravel(), domain["gphit"].values.ravel()))
    _, idx = tree.query(_lonlat_to_xyz(lon.ravel(), lat.ravel()))
    bottom_tgt = bottom[idx].reshape(lon.shape)
    domain.close()
    levels = np.arange(1, nz + 1)[:, np.newaxis, np.newaxis]
    return xr.DataArray(bottom_tgt[np.newaxis, :, :] >= levels, dims=("z", "y", "x"))

def woa_zonal_mean(thetao, ocean_mask):
    """Zonal mean over present-day ocean, broadcast in longitude, gaps filled."""
    zm = thetao.where(ocean_mask).mean("x", skipna=True)   # (time_counter, z, y)
    zm = zm.interpolate_na("z", method="nearest", fill_value="extrapolate")  # levels below the deepest ocean at that latitude
    zm = zm.interpolate_na("y", method="nearest", fill_value="extrapolate")  # all-land latitudes (Antarctica)
    return zm.broadcast_like(thetao)

class EoceneNEMO():

    def __init__(self, herold_folder, input_folder, output_folder, grid= "r720x360"):
        self.herold_folder = herold_folder
        self.input_folder = input_folder
        self.output_folder = output_folder
        self.cdo = Cdo()

        self.grid=grid

    def create_tidal_mixing(self, hcri_value=500.0, cleanup=True):

        m2_varname="eo_tidal_dissipation"

        herold_file_orig = os.path.join(self.herold_folder, "Green_Huber_eocene_tidal_dissipation_1x1.nc")
        herold_file_remap = os.path.join(self.herold_folder, "Green_Huber_eocene_tidal_dissipation_r720x360.nc")
        herold_bath_orig = os.path.join(self.herold_folder, "herold_etal_eocene_topo_1x1.nc")
        herold_bath_remap = os.path.join(self.herold_folder, "herold_etal_eocene_topo_1x1_r720x360.nc")
        zdfiwm_file = os.path.join(self.input_folder, "nemo/initial/zdfiwm_forcing_r720x360.nc")
        output_file = os.path.join(self.output_folder, "nemo/initial/zdfiwm_forcing_r720x360.nc")
        

        if cleanup and os.path.exists(output_file):
            os.remove(output_file)
            loggy.info("Cleaning file: %s", output_file)

        herold_file_remap = self.cdo.remapcon(self.grid, input=herold_file_orig)
        herold_bath_remap = self.cdo.remapcon(self.grid, input=herold_bath_orig)

        ds_m2 = xr.open_dataset(herold_file_remap)
        ds_bt = xr.open_dataset (herold_bath_remap)
        ds_pd = xr.open_dataset(zdfiwm_file)

        m2 = ds_m2[m2_varname]

        # Interpolate topo onto the ds_pd grid
        topo_interp = ds_bt["topo"].interp(
            lat=ds_pd.latitude,
            lon=ds_pd.longitude,
            method="linear"
        )

        ocean_topo = topo_interp.where(topo_interp < 0.0)

        # make a copy of present-day file
        ds_out = ds_pd.copy(deep=True)

        # inject M2 into power_cri (1/3 only)
        ds_out['power_cri'][:] = (1.0 / 3.0) * m2.values

        # modify bathymetry
        ds_out['bathymetry'][:] = ocean_topo

        # zero in other energy reservoirs
        ds_out['power_nsq'][:] = 0.0
        ds_out['power_sho'][:] = 0.0
        ds_out['power_bot'][:] = 0.0

        # set vertical length scales
        ds_out['scale_cri'][:] = hcri_value
        ds_out['scale_bot'][:] = 0.0   # unused if power_bot = 0

        # convert NaN into zeroes
        ds_out = ds_out.fillna(0)

        # write output file
        os.makedirs(os.path.join(self.output_folder, "nemo/initial"), exist_ok=True)
        ds_out.to_netcdf(output_file)
        loggy.info("Written NEMO 4.2 tidal file: %s", output_file)

        ds_m2.close()
        ds_pd.close()

        return None
    
    def create_geothermal_flux(self, cap_value=400, cleanup=True):

        gh_file = os.path.join(self.input_folder,"nemo/initial/Goutorbe_ghflux.nc")
        age_file = os.path.join(self.herold_folder,"age_depth_bath_55.xyadb")
        gh_file_out = os.path.join(self.output_folder,"nemo/initial/Goutorbe_ghflux.nc")

        if cleanup and os.path.exists(gh_file_out):
            os.remove(gh_file_out)
            loggy.info("Cleaning file: %s", gh_file_out)
        
        # Loading Geothermal flux NEMO file
        ds_gh = xr.open_dataset(gh_file)
        lat_tgt = ds_gh.lat.values
        lon_tgt = ds_gh.lon.values

        age = pd.read_csv(age_file, sep=r"\s+", header=None, usecols=[0,1,2], names=["lon","lat","age"], engine="c")
        t = age.set_index(["lat", "lon"])["age"].to_xarray()

        q = xr.where(
            t <= 55,
            510 * t**(-0.5),
            48 + 96 * np.exp(-0.0278 * t)
        )
        
        q_min = float(q.min())
        q = q.fillna(q_min)
    
        # Flip lat if needed (so it’s increasing)
        q = q.sortby("lat")

        # 1D interpolation along lon
        tmp = np.empty((q.lat.size, lon_tgt.size))
        for i in range(q.lat.size):
            tmp[i, :] = np.interp(lon_tgt, q.lon.values, q.values[i, :])

        # 1D interpolation along lat
        q_interp_values = np.empty((lat_tgt.size, lon_tgt.size))
        for j in range(len(lon_tgt)):
            q_interp_values[:, j] = np.interp(lat_tgt, q.lat.values, tmp[:, j])

        # Wrap as DataArray on NEMO grid
        q_interp = xr.DataArray(
            q_interp_values,
            coords={"lat": lat_tgt, "lon": lon_tgt},
            dims=("lat", "lon"),
            name="gh_flux"
        )

        # Cap values
        q_interp = xr.where(q_interp > cap_value, cap_value, q_interp)

        if lat_tgt[0] > lat_tgt[-1]:
            q_interp = q_interp.sortby("lat", ascending=False)
        # Assign into Goutorbe_ghflux.nc
        ds_gh["gh_flux"][0, :, :] = q_interp

        
        ds_gh.to_netcdf(gh_file_out)
        loggy.info("Written NEMO 4.2 tidal file: %s", gh_file_out)
        ds_gh.close()

        return None

    def create_ocean_init(self, profile=None, so_value=34.7, output_file=None):
        """
        Create ocean initial conditions (thetao and so) for NEMO
        based on WOA climatology and an idealized temperature profile.

        Parameters
        ----------
        profile : str or None
            None (default): build both profiles below, one file each.
            "deepmip_cold": idealized cold DeepMIP-like profile (output suffix deepmip-30).
            "woa_pi": zonal mean of present-day WOA over the present-day ocean,
                      broadcast in longitude (output suffix woa-pi).
        so_value : float
            Salinity to assign everywhere (default = 34.7).
        output_file : str or None
            Output path for a single profile. Default: the input path of
            ``nemo/initial/woa13-levitus-L31.nc`` under the output folder, with
            ``_<suffix>`` before the extension. Not allowed with ``profile=None``.

        Returns
        -------
        xarray.Dataset or dict of xarray.Dataset
            The written dataset; with ``profile=None``, a dict keyed by profile.

        Raises
        ------
        ValueError
            If ``profile`` is unknown, or ``output_file`` is given with ``profile=None``.
        """

        if profile is None:
            if output_file is not None:
                raise ValueError(
                    "output_file needs a single profile ('deepmip_cold' or 'woa_pi'); "
                    "profile=None builds both files with their default names"
                )
            return {
                name: self.create_ocean_init(profile=name, so_value=so_value)
                for name in ("deepmip_cold", "woa_pi")
            }

        if profile not in ("deepmip_cold", "woa_pi"):
            raise ValueError(f"Unknown profile: {profile}. Options are: deepmip_cold, woa_pi")

        woa_file = os.path.join(self.input_folder, "nemo/initial/woa13-levitus-L31.nc")
        domain_file = os.path.join(self.input_folder, "nemo/domain/PALEORCA2/domain_cfg.nc")
        woa = xr.open_dataset(woa_file)
        domain = xr.open_dataset(domain_file)

        # Assign depths from domain_cfg
        woa = woa.assign_coords(z=domain["nav_lev"])

        # Extract coordinates
        depths = woa["z"].values       # (nz,)
        lat = woa["lat"].values   # (ny, nx) usually
        lon = woa["lon"].values   # (ny, nx) usually
        lat_rad = np.deg2rad(lat)

        # Build 3D mesh (depth, lat, lon)
        Z, LAT, LON = np.meshgrid(depths, lat_rad[:,0], lon[0,:], indexing="ij")


        if profile == "deepmip_cold":
            # Temperature profile formula
            thetao = np.where(
                Z <= 1000,
                ((1000 - Z) / 1000) * 20 * np.cos(LAT) + 10,
                10,
            )

            #thetao = np.where(
            #    Z <= 5000,
            #    ((5000 - Z) / 5000) * 20 * np.cos(LAT) + 15,
            #    15,
            #)

            thetao = np.broadcast_to(thetao, woa["thetao"].shape)   # keep the 12 months
            suffix = "deepmip-30"

        elif profile == "woa_pi":
            # Present-day ocean mask from the ORCA2 domain (WOA is filled over land)
            orca2_file = os.path.join(self.input_folder, "nemo/domain/ORCA2/domain_cfg.nc")
            pd_ocean_mask = present_day_ocean_mask(orca2_file, lon, lat, len(depths))
            thetao = woa_zonal_mean(woa["thetao"], pd_ocean_mask).values
            suffix = "woa-pi"

        # Salinity constant
        so = np.full_like(thetao, so_value)

        woa = woa.assign(
            thetao=(("time_counter", "z", "y", "x"), thetao, woa["thetao"].attrs),
            so=(("time_counter", "z", "y", "x"), so, woa["so"].attrs),
        )

        # === Decide output path ===
        if output_file is None:

            rel_path = os.path.relpath(woa_file, self.input_folder)
            base, ext = os.path.splitext(rel_path)
            output_file = os.path.join(self.output_folder, f"{base}_{suffix}{ext}")

        os.makedirs(os.path.dirname(output_file), exist_ok=True)

        # overwrite-safe
        if os.path.exists(output_file):
            os.remove(output_file)

        woa.to_netcdf(output_file, mode="w")

        loggy.info("Ocean initial conditions written to %s", output_file)

        return woa
    
    def create_runoff (self):
        
        runoff = os.path.join(self.input_folder, "nemo/climatology/runoff_DaiTrenberth_PALEORCA2.nc")
        runoff_output = os.path.join(self.output_folder, "nemo/climatology/runoff_DaiTrenberth_PALEORCA2.nc")

        ds_rnf = xr.open_dataset(runoff)

        ds_out = ds_rnf.copy(deep=True)
        ds_out['socoefr'][:] = 0.0
        ds_out['sorunoff'][:] = 0.0

        # convert NaN into zeroes
        ds_out = ds_out.fillna(0)

        # write output file
        os.makedirs(os.path.join(self.output_folder, "nemo/climatology"), exist_ok=True)
        ds_out.to_netcdf(runoff_output)
        loggy.info("Written NEMO 4.2 runoff file: %s", runoff_output)

        ds_rnf.close()

        return None
