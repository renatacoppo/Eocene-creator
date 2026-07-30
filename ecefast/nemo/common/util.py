"""
Utility functions for NEMO domain processing.

Standalone functions for netCDF file manipulation and validation
that don't require workflow instance state.
"""
import logging
import os
import xarray as xr

logger = logging.getLogger("nemo.util")


def process_domain_cfg(src_dir, tgt_dir, name):
    """Modify domain_cfg file by renaming the vertical dimension and resetting it.
    
    Args:
        src_dir: Path to the source directory containing domain_cfg_{name}.nc
        tgt_dir: Path to the target directory where the modified file will be saved
        name: Bathymetry name to identify the correct domain_cfg_{name}.nc file
    """
    domain_file = f'domain_cfg_{name}.nc'
    logger.debug("Processing %s from %s", domain_file, src_dir)
    
    # Load the xarray dataset
    domain = xr.open_dataset(os.path.join(src_dir, domain_file))
    
    # Rename and reset the vertical dimension
    domain = domain.rename_dims({'nav_lev': 'z'})
    domain = domain.reset_index('nav_lev').reset_coords('nav_lev')
    
    # Set fill values to None to avoid issues
    encoding_var = {var: {'_FillValue': None} for var in domain.data_vars}
    encoding_coord = {var: {'_FillValue': None} for var in domain.coords}
    encoding = {**encoding_var, **encoding_coord}
    
    # Add PALEORCA attributes
    domain.attrs['cn_cfg'] = "PALEORCA"
    domain.attrs['nn_cfg'] = 2
    
    # Write the file
    os.makedirs(tgt_dir, exist_ok=True)
    output_path = os.path.join(tgt_dir, 'domain_cfg.nc')
    domain.to_netcdf(output_path, encoding=encoding, unlimited_dims=['time_counter'])
    logger.debug("Written %s", output_path)


def extract_maskutil(src_dir, tgt_dir, name):
    """Extract mask variables from mesh_mask and save to maskutil.nc.
    
    Args:
        src_dir: Path to the source directory containing mesh_mask_{name}.nc
        tgt_dir: Path to the target directory where maskutil.nc will be saved
        name: Bathymetry name to identify the correct mesh_mask_{name}.nc file
    """
    mesh_file = f'mesh_mask_{name}.nc'
    logger.debug("Extracting maskutil from %s", mesh_file)
    
    # Load mesh_mask and extract mask variables
    mesh = xr.open_dataset(os.path.join(src_dir, mesh_file))
    masks = mesh[['tmaskutil', 'umaskutil', 'vmaskutil']]
    masks = masks.rename_dims({'time_counter': 't'}).drop_vars('time_counter')
    masks.attrs = {'Conventions': "CF-1.1"}
    
    # Write maskutil file
    os.makedirs(tgt_dir, exist_ok=True)
    output_path = os.path.join(tgt_dir, 'maskutil.nc')
    masks.to_netcdf(output_path, unlimited_dims=['t'])
    logger.debug("Written %s", output_path)


def check_files_exist(src_dir, bathymetries, file_patterns, step_name):
    """Verify that required files exist for all bathymetries.
    
    Args:
        src_dir: Directory where files should be located
        bathymetries: List of bathymetry config dicts (must have 'name' key)
        file_patterns: List of filename patterns (e.g., ['domain_cfg_{name}.nc'])
        step_name: Name of the step that requires these files (for error message)
    
    Raises:
        FileNotFoundError: If required files are missing
    """
    missing_files = []
    
    for cfg in bathymetries:
        name = cfg['name']
        for pattern in file_patterns:
            filepath = os.path.join(src_dir, pattern.format(name=name))
            if not os.path.exists(filepath):
                missing_files.append(filepath)
    
    if missing_files:
        files_str = '\n  - '.join(missing_files)
        raise FileNotFoundError(
            f"Cannot run {step_name} without required files.\n"
            f"Missing files:\n  - {files_str}\n"
            f"Please enable and run the 'domain_cfg' step first."
        )
