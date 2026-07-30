#!/usr/bin/env python3
"""Python function to generate a valid namelist_cfg for the DOMAINcfg run"""

import argparse
import logging
import os
from jinja2 import Environment, FileSystemLoader
import xarray as xr

logger = logging.getLogger("nemo.domain_tools")


def get_args():
    """Parse command-line arguments for the script."""
    parser = argparse.ArgumentParser(
        description="Generates a lat/lon file for the ORCA grid, with bounds.")
    parser.add_argument(
        "--bathymetry",
        type=str,
        help="Input bathymetry file name"
    )
    parser.add_argument(
        "--coordinates",
        type=str,
        help="Input coordinates file name"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="namelist_cfg",
        help="Output namelist file name (default: namelist_cfg)"
    )
    parser.add_argument(
        "--configuration",
        type=str,
        default="PALEORCA2",
        help="Configuration name to use in the namelist (default: PALEORCA2)"
    ) 
    parser.add_argument(
        "--levels",
        type=int,
        default=31,
        help="Number of vertical levels to use in the namelist (default: 31)"
    )

    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        help="Logging level: DEBUG, INFO, WARNING (default: INFO)"
    )

    return parser.parse_args()

def find_variable(file, pattern, exclude_pattern=None):
    """Find a variable by pattern in data_vars, fall back to coords."""
    for source in [file.data_vars, file.coords]:
        matches = [var for var in source.keys() if pattern in var.lower()]
        if exclude_pattern:
            matches = [var for var in matches if exclude_pattern not in var.lower()]
        if matches:
            return matches[0]
    raise ValueError(f"Variable matching '{pattern}' not found")


_BATHY_EXCLUDE = frozenset({'lon', 'lat', 'time', 'nav_lev', 'depth', 'bnds'})


def find_bathymetry_variable(file):
    """
    Identify the bathymetry variable in *file*, excluding coordinate-like names.

    Raises a descriptive ValueError when the result is ambiguous or absent.
    """
    candidates = [
        v for v in file.data_vars
        if not any(token in v.lower() for token in _BATHY_EXCLUDE)
    ]
    if len(candidates) == 1:
        return candidates[0]
    all_vars = list(file.data_vars)
    if not candidates:
        raise ValueError(
            f"No bathymetry variable found. data_vars: {all_vars}"
        )
    raise ValueError(
        f"Ambiguous bathymetry variable: {candidates}. All data_vars: {all_vars}"
    )

def main(args):
    """Main function to generate the namelist_cfg file based on the provided bathymetry and coordinates files."""
    level = getattr(logging, args.log_level.upper(), logging.INFO)
    root = logging.getLogger("nemo")
    root.setLevel(level)
    root.propagate = False
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(name)s | %(levelname)8s -> %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    root.addHandler(handler)

    file = xr.open_dataset(args.bathymetry)

    bathymetry_variable = find_bathymetry_variable(file)
    lon_variable = find_variable(file, pattern='lon', exclude_pattern='bnds')
    lat_variable = find_variable(file, pattern='lat', exclude_pattern='bnds')
    
    # Check variable names in the dataset
    logger.debug("Bathymetry variable: %s", bathymetry_variable)
    logger.debug("Longitude variable:  %s", lon_variable)
    logger.debug("Latitude variable:   %s", lat_variable)

    lat_dimension, lon_dimension = file[bathymetry_variable].squeeze().shape


    # 1. Define your data dictionary
    context = {
        "bathymetry_file": args.bathymetry,
        "bathymetry_variable": bathymetry_variable,
        "lon_variable": lon_variable,
        "lat_variable": lat_variable,
        "coordinates_file": args.coordinates,
        "configuration": args.configuration,
        "lon_dimension": lon_dimension,
        "lat_dimension": lat_dimension,
        "levels": args.levels
    }

    # 2. Set up the environment and load the template
    # Assuming your template is in a folder named 'templates'
    env = Environment(loader=FileSystemLoader(os.path.dirname(os.path.abspath(__file__))))
    template = env.get_template("namelist_cfg.j2")

    # 3. Render by unpacking the dictionary
    rendered_content = template.render(**context)

    # 4. Save to a file
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(rendered_content)

    logger.info("Namelist written: %s", args.output)

if __name__ == "__main__":
    main(get_args())
 