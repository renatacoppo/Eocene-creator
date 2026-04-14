#!/bin/env/python 
import argparse
import logging
import xarray as xr

from common.yaml import load_yaml
from oifs.eoceneOIFS import EoceneOIFS

def run_oifs(config):
    """Run the OIFS modifications based on the provided configuration."""

    logging.info("Starting OIFS modifications")

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

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Duplicate job configuration for experiments.")
    parser.add_argument("-c", "--config", required=True, help="Path to the original job configuration file.")
    parser.add_argument("-l", "--log", default="INFO", help="Logging level (e.g., DEBUG, INFO, WARNING).")

    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log))
    config = load_yaml(args.config)
    
    logging.info(f"Loaded configuration: {config}")
    run_oifs(config)



