#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A tool to produce the mask_util from mesh_mask
Also modifies the domain_cfg file by renaming the vertical dimension

DEPRECATED: This standalone script is maintained for backwards compatibility only.
The functionality has been moved to NEMOWorkflow._process_domain_cfg() and
NEMOWorkflow._extract_maskutil() methods in cli-domain-paleorca.py.
"""

import argparse
import os
import shutil
import xarray as xr


def domain_cfg(src_dir, tgt_dir, name):
    """
    Modify the domain_cfg file by renaming the vertical dimension and resetting it. 

    Args:
    src_dir (str): Path to the source directory containing the domain_cfg file. 
    tgt_dir (str): Path to the target directory where the modified domain_cfg file will be saved.
    name (str): Bathymetry name to identify the correct domain_cfg_{name}.nc file.
    """

    domain_file = f'domain_cfg_{name}.nc'
    
    # load the xarray files
    domain = xr.open_dataset(f'{src_dir}/{domain_file}')

    # rename and reset the vertical dimension
    domain = domain.rename_dims({'nav_lev': 'z'})
    domain = domain.reset_index('nav_lev').reset_coords('nav_lev')

    # set the fill values
    encoding_var = {var: {'_FillValue': None} for var in domain.data_vars}
    encoding_coord = {var: {'_FillValue': None} for var in domain.coords}
    encoding = {**encoding_var, **encoding_coord}

    # add paleorca attributes
    domain.attrs['cn_cfg'] = "PALEORCA"
    domain.attrs['nn_cfg'] = 2

    # write the file
    os.makedirs(tgt_dir, exist_ok=True)
    domain.to_netcdf(f'{tgt_dir}/domain_cfg.nc', encoding=encoding, unlimited_dims=['time_counter'])

def maskutil(src_dir, tgt_dir, name):
    """
    Extracts mask variables from a mesh dataset and saves them to a new maskutil.nc file.

    Args:
    src_dir (str): Path to the source directory containing the mesh_mask.nc file.
    tgt_dir (str): Path to the target directory where the maskutil.nc file will be saved.
    name (str): Bathymetry name to identify the correct mesh_mask_{name}.nc file.

    Returns:
    None
    """
    mesh_file = f'mesh_mask_{name}.nc'
    mesh = xr.open_dataset(f'{src_dir}/{mesh_file}')
    masks = mesh[['tmaskutil','umaskutil','vmaskutil']]
    masks = masks.rename_dims({'time_counter': 't'}).drop_vars('time_counter')
    masks.attrs = {'Conventions': "CF-1.1"}
    os.makedirs(tgt_dir, exist_ok=True)
    masks.to_netcdf(f'{tgt_dir}/maskutil.nc', unlimited_dims=['t'])

    shutil.copy(f'{src_dir}/{mesh_file}', f'{tgt_dir}/mesh_mask_{name}.nc')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='A tool to modify domain_cfg ORCA2 file')

    parser.add_argument('--src_dir', type=str,
                        help='Path to src domain directory (domainCFG path)')
    parser.add_argument('--tgt_dir', type=str,
                        help='Path to target directory')
    parser.add_argument('--name', type=str, required=True,
                        help='Bathymetry name (reads domain_cfg_{name}.nc and mesh_mask_{name}.nc)')

    args = parser.parse_args()

    domain_cfg(args.src_dir, args.tgt_dir, args.name)
    maskutil(args.src_dir, args.tgt_dir, args.name)
