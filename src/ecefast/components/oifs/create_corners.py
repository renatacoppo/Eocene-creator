#!/usr/bin/env python
"""
Function to create corner coordinates for a grid based on input ICMGG files from OIFS.
Based on the original script from Florian Ziemen.

The OIFS generator builds the grid it needs itself (``ecefast.components.oifs.corners``); this script writes the
grids of ``resolutions`` from an input tree, with their masked variants.

Paolo Davini, Apr 2024
"""

import argparse

from ecefast.components.oifs.corners import read_reduced_grid, reduced_grid_corners, write_corner_grid
from ecefast.core.grib import extract_grid_info


resolutions = ["TL63L31", "TL159L91"]


def main() -> None:
    """Write the corner-coordinate grid files of each resolution in ``resolutions``."""
    parser = argparse.ArgumentParser(description="Create corner coordinates of the OIFS reduced Gaussian grids.")
    parser.add_argument("--oifs-dir", required=True, help="OIFS input folder (ECE4-DATA oifs/), with <res>/19900101/")
    parser.add_argument("--tgt-dir", required=True, help="output folder for the grid files")
    args = parser.parse_args()
    oifs_dir = args.oifs_dir
    tgt_dir = args.tgt_dir

    for resolution in resolutions:
        print("Processing resolution:", resolution)

        kind, spectral, _ = extract_grid_info(resolution)
        infile_name = f"{oifs_dir}/{resolution}/19900101/ICMGGECE4INIT"
        outfile_name = f"{tgt_dir}/T{kind}{spectral}_grid.nc"
        outfile_masked_name = f"{tgt_dir}/T{kind}{spectral}_grid_masked.nc"

        lat, reduced_points, mask = read_reduced_grid(infile_name, kind, spectral, tgt_dir)
        grid = reduced_grid_corners(lat, reduced_points)
        print("Writing output file...", outfile_name)
        write_corner_grid(outfile_name, *grid)
        print("Writing masked output file...", outfile_masked_name)
        write_corner_grid(outfile_masked_name, *grid, mask=mask)


if __name__ == "__main__":
    main()
