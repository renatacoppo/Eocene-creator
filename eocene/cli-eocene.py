#!/usr/bin/env python
"""Command-line interface for running the Eocene modifications workflow, including OIFS, NEMO, and runoff mapper"""

import argparse
import shutil
import os
import xarray as xr
import numpy as np

from eocene.common import load_yaml, setup_logger
from eocene.oifs.eoceneOIFS import EoceneOIFS
from eocene.nemo.eoceneNEMO import EoceneNEMO
from eocene.rnfm.eoceneRNFM import iter_track, create_basin_data

def run_copy(input_dir, output_dir):
    """Copy the input folder to the output folder to preserve original data."""
    
    logger.info(f"Copying input data from {input_dir} to {output_dir}")
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    if os.path.exists(output_dir):
        logger.info(f"Output directory {output_dir} already exists. It will be overwritten.")
        shutil.rmtree(output_dir)

    # loop through input directory and copy relevant subdirectories
    for item in os.listdir(input_dir):
        logger.info(f"Processing {item}...")
        if item in ["oifs", "nemo"]:
            
            for subitem in os.listdir(os.path.join(input_dir, item)):
                if subitem in ["TL255L91", "TL159L91", "pisces", "domain"]:
                    continue
                src = os.path.join(input_dir, item, subitem)
                dst = os.path.join(output_dir, item, subitem)
                logger.info(f"Copying {src} to {dst}")
                shutil.copytree(src, dst, symlinks=True)
        if item in ["cmip6-data"]:
            src = os.path.join(input_dir, item)
            dst = os.path.join(output_dir, item)
            logger.info(f"Copying {src} to {dst}")
            os.symlink(src, dst)  # use symlink for large CMIP6 data

def run_oifs(config):
    """Run the OIFS modifications based on the provided configuration."""

    logger.info("Starting OIFS modifications")

    # eocene class init
    eocene_oifs = EoceneOIFS(
        idir=config["dirs"]["input"],
        odir=config["dirs"]["output"],
        herold=config["dirs"]["herold"],
        startdate='19900101'
    )

    # Load Herold datasets (land sea mask, orography, sd_orography)
    lsm_eocene = xr.open_dataset(eocene_oifs.prepare_herold(flag="landsea_mask"))
    orog = xr.open_dataset(eocene_oifs.prepare_herold(flag="orography"))
    sd_orog = xr.open_dataset(eocene_oifs.prepare_herold(flag="sd_orography"))

    # Prepare land-sea mask for present-day
    lsm_present = eocene_oifs.prepare_landsea_mask_present()

    # Create OIFS modifications
    eocene_oifs.create_climate(lsm_present=lsm_present, landsea=lsm_eocene)
    eocene_oifs.create_bare_soil(lsm_present=lsm_present, landsea=lsm_eocene)
    eocene_oifs.create_sh(orog=orog['orography'])
    eocene_oifs.create_init(lsm_eocene["landsea_mask"], sd_orog["sd_orography"])
    eocene_oifs.create_iniua()
    eocene_oifs.aerosols()

def run_nemo(config):
    """Run the NEMO modifications based on the provided configuration."""
    
    logger.info("Starting NEMO modifications")

    # eocene class init
    eocene_nemo = EoceneNEMO(
        herold_folder=config["dirs"]["herold"],
        input_folder=config["dirs"]["input"],
        output_folder=config["dirs"]["output"]
    )

    # copy domain and maskutil files
    for filename in ["domain_cfg.nc", "maskutil.nc"]:
        src = os.path.join(config["dirs"]["domain"], filename)
        dst = os.path.join(config["dirs"]["output"], "nemo", "domain", "PALEORCA2", filename)
        if os.path.exists(dst):
            os.remove(dst)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        logger.info(f"Copying {src} to {dst}")
        shutil.copy(src, dst)

    # Create NEMO modifications
    eocene_nemo.create_tidal_mixing()
    eocene_nemo.create_geothermal_flux()
    eocene_nemo.create_ocean_init()

def run_runoff(config):

    logger.info('Reading oroslope file...')
    oroslopefile = os.path.join(config["dirs"]["herold"], "herold_etal_eocene_runoff_1x1.nc")
    runoff_file = os.path.join(config["dirs"]["input"], "runoff-mapper/runoff_maps.nc")
    final_file = os.path.join(config["dirs"]["output"], "runoff-mapper/runoff_maps.nc")
    oroslope = xr.load_dataset(oroslopefile)
    oroslope = oroslope.rename({'xc': 'longitude', 'yc': 'latitude'})
    oroslope = oroslope.assign_coords(longitude = oroslope.longitude[0], latitude = oroslope.latitude[:, 0])
    flowdir = oroslope['RTM_FLOW_DIRECTION'].values

    logger.info('Launching calc!')
    rnf_map_merged_final, rivers_merged_final, rivers_end_point, not_assigned = iter_track(flowdir, lat = oroslope.latitude)

    if len(not_assigned) > 0:
        logger.warning('Some points have not been assigned:')
        logger.warning(not_assigned)

    # Building arrival point id
    arrival_id = np.zeros(rnf_map_merged_final.shape) - 2
    for num in rivers_merged_final:
        for po in rivers_merged_final[num]:
            arrival_id[po[0], po[1]] = num

    logger.info('Check!')
    logger.info(f"{rnf_map_merged_final.min()} {rnf_map_merged_final.max()}")
    logger.info(f"{arrival_id.min()} {arrival_id.max()}")

    ## Setting calving equal to runoff
    logger.warning("WARNING!! Setting calving_id equal to arrival_id! To be changed if ice sheets are present")
    calving_id = arrival_id.copy()

    rnf_pd = xr.load_dataset(runoff_file)
    os.makedirs(os.path.dirname(final_file), exist_ok=True)
    create_basin_data(final_file, rnf_pd, rnf_map_merged_final, arrival_id, calving_id, oroslope.longitude, oroslope.latitude)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Duplicate job configuration for experiments.")
    parser.add_argument("-c", "--config", required=True, help="Path to the original job configuration file.")
    parser.add_argument("-l", "--log", default="INFO", help="logger level (e.g., DEBUG, INFO, WARNING).")
    parser.add_argument("-r", "--run", choices=["oifs", "nemo", "rnfm", "all"], default="all", help="Which part of the workflow to run.")
    parser.add_argument("--copy", action="store_true", help="Whether to copy the original configuration file to the output directory.")

    args = parser.parse_args()

    logger = setup_logger(level=args.log)
    config = load_yaml(args.config)

    if args.copy:
        run_copy(config["dirs"]["input"], config["dirs"]["output"])
        
    logger.info(f"Loaded configuration: {config}")
    if args.run in ["oifs", "all"]:
        run_oifs(config)
    if args.run in ["nemo", "all"]:
        run_nemo(config)
    if args.run in ["rnfm", "all"]:
        run_runoff(config)



