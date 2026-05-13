#!/usr/bin/env python3
"""Python function to generate a valid namelist_cfg for the DOMAINcfg run"""

import argparse
from jinja2 import Environment, FileSystemLoader
import xarray as xr


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

def main(args):
    """Main function to generate the namelist_cfg file based on the provided bathymetry and coordinates files."""

    file = xr.open_dataset(args.bathymetry)

    bathymetry_variable = [var for var in file.data_vars.keys() if 'lon' not in var.lower() and 'lat' not in var.lower()][0]
    lon_variable = find_variable(file, pattern='lon', exclude_pattern='bnds')
    lat_variable = find_variable(file, pattern='lat', exclude_pattern='bnds')
    
    # Check variable names in the dataset
    print(f"Bathymetry variables in the dataset: {bathymetry_variable}")
    print(f"Longitude variable in the dataset: {lon_variable}")
    print(f"Latitude variable in the dataset: {lat_variable}")

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
    env = Environment(loader=FileSystemLoader("."))
    template = env.get_template("namelist_cfg.j2")

    # 3. Render by unpacking the dictionary
    rendered_content = template.render(**context)

    # 4. Save to a file
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(rendered_content)

    print("File rendered successfully!")

if __name__ == "__main__":
    main(get_args())
 