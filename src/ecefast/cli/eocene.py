#!/usr/bin/env python
"""Command-line interface for running the Eocene modifications workflow, including OIFS, NEMO, and runoff mapper"""

import argparse
import shutil
import os
import xarray as xr
import numpy as np

from ecefast.core import Config, ConfigError, load_config, setup_logger
from ecefast.core.cdo import cdo_version
from ecefast.core.steps import run_pipeline
from ecefast.core.workspace import Context, Stage
from ecefast.paleo.eocene.oifs.eoceneOIFS import EoceneOIFS
from ecefast.paleo.eocene.nemo.eoceneNEMO import EoceneNEMO
from ecefast.paleo.eocene.oasis.eoceneOASIS import EoceneOASIS
from ecefast.paleo.eocene.rnfm.eoceneRNFM import iter_track, create_basin_data


def run_oifs(config: Config, logger):
    """Run the OIFS modifications based on the provided configuration."""

    logger.info("Starting OIFS modifications")

    # eocene class init
    eocene_oifs = EoceneOIFS(
        idir=config.paths.input,
        odir=config.paths.output,
        herold=config.paths.herold,
        startdate="19900101",
        resolution=config.grids.oifs,
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
    eocene_oifs.create_sh(orog=orog["orography"])
    eocene_oifs.create_init(
        lsm_present=lsm_present, landsea=lsm_eocene["landsea_mask"], sd_orog=sd_orog["sd_orography"]
    )
    eocene_oifs.create_iniua()
    if config.eocene.oifs.aerosols:
        eocene_oifs.aerosols()


def run_nemo(config: Config, logger):
    """Run the NEMO modifications based on the provided configuration."""

    logger.info("Starting NEMO modifications")

    # eocene class init
    eocene_nemo = EoceneNEMO(
        herold_folder=config.paths.herold,
        input_folder=config.paths.input,
        output_folder=config.paths.output,
    )

    # copy domain and maskutil files
    for filename in ["domain_cfg.nc", "maskutil.nc"]:
        src = os.path.join(config.tools.precomputed.domain, filename)
        dst = os.path.join(config.paths.output, "nemo", "domain", config.grids.nemo, filename)
        if os.path.exists(dst):
            os.remove(dst)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        logger.info(f"Copying {src} to {dst}")
        shutil.copy(src, dst)

    # Create NEMO modifications
    eocene_nemo.create_tidal_mixing()
    eocene_nemo.create_geothermal_flux()
    eocene_nemo.create_ocean_init()
    eocene_nemo.create_runoff()


def run_runoff(config: Config, logger):

    logger.info("Reading oroslope file...")
    oroslopefile = os.path.join(config.paths.herold, "herold_etal_eocene_runoff_1x1.nc")
    runoff_file = os.path.join(config.paths.input, "runoff-mapper/runoff_maps.nc")
    final_file = os.path.join(config.paths.output, "runoff-mapper/runoff_maps.nc")
    oroslope = xr.load_dataset(oroslopefile)
    oroslope = oroslope.rename({"xc": "longitude", "yc": "latitude"})
    oroslope = oroslope.assign_coords(longitude=oroslope.longitude[0], latitude=oroslope.latitude[:, 0])
    flowdir = oroslope["RTM_FLOW_DIRECTION"].values

    logger.info("Launching calc!")
    rnf_map_merged_final, rivers_merged_final, rivers_end_point, not_assigned = iter_track(
        flowdir, lat=oroslope.latitude
    )

    if len(not_assigned) > 0:
        logger.warning("Some points have not been assigned:")
        logger.warning(not_assigned)

    # Building arrival point id
    arrival_id = np.zeros(rnf_map_merged_final.shape) - 2
    for num in rivers_merged_final:
        for po in rivers_merged_final[num]:
            arrival_id[po[0], po[1]] = num

    logger.info("Check!")
    logger.info(f"{rnf_map_merged_final.min()} {rnf_map_merged_final.max()}")
    logger.info(f"{arrival_id.min()} {arrival_id.max()}")

    ## Setting calving equal to runoff
    logger.warning("WARNING!! Setting calving_id equal to arrival_id! To be changed if ice sheets are present")
    calving_id = arrival_id.copy()

    rnf_pd = xr.load_dataset(runoff_file)
    os.makedirs(os.path.dirname(final_file), exist_ok=True)
    create_basin_data(
        final_file, rnf_pd, rnf_map_merged_final, arrival_id, calving_id, oroslope.longitude, oroslope.latitude
    )


def run_oasis(config: Config, logger):
    logger.info("Starting OASIS modifications")

    # eocene class init
    eocene_oasis = EoceneOASIS(idir=config.paths.input, odir=config.paths.output, nemo_resolution=config.grids.nemo)

    # Create OASIS modifications
    eocene_oasis.create_rstos(constant_sst=config.eocene.oasis.constant_sst)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Duplicate job configuration for experiments.")
    parser.add_argument("-c", "--config", required=True, help="Path to the original job configuration file.")
    parser.add_argument("-l", "--loglevel", default="INFO", help="logger level (e.g., DEBUG, INFO, WARNING).")
    parser.add_argument(
        "-r",
        "--run",
        choices=["oasis", "oifs", "nemo", "rnfm", "all"],
        default="all",
        help="Which part of the workflow to run.",
    )
    parser.add_argument(
        "--copy", action="store_true", help="Whether to copy the original configuration file to the output directory."
    )

    args = parser.parse_args(argv)

    logger = setup_logger(level=args.loglevel)
    logger.info(f"Logger initialized with level: {args.loglevel}")
    logger.info("CDO version: %s", cdo_version())
    config = load_config(args.config)
    if args.run in ["nemo", "all"] and config.tools.precomputed.domain is None:
        raise ConfigError(f"{args.config}: '--run {args.run}' needs 'tools.precomputed.domain' (the Eocene domain)")

    if args.copy:
        run_pipeline([Stage], Context(config))

    logger.info(f"Loaded configuration: {config}")
    if args.run in ["oasis", "all"]:
        run_oasis(config, logger)
    if args.run in ["oifs", "all"]:
        run_oifs(config, logger)
    if args.run in ["nemo", "all"]:
        run_nemo(config, logger)
    if args.run in ["rnfm", "all"]:
        run_runoff(config, logger)


if __name__ == "__main__":
    main()
