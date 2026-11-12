#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate ocean subbasin masks for NEMO simulations.

Creates masks for Atlantic, Pacific, Indian, Indo-Pacific, and Global basins
using fixed lon/lat polygons drawn on present-day geography; ocean points outside all polygons stay
unassigned. The pipeline runs it for every bathymetry; for paleo bathymetries check the result by eye
(``notebooks/analysis/eocene-subbasins.ipynb``).
"""

import argparse
import logging
import os
import numpy as np
import xarray as xr
from shapely.geometry import Point, Polygon, MultiPolygon

from ecefast.core.logger import setup_logger

# explicit name: this file runs as a script (pipeline subprocess), where __name__ is "__main__"
logger = logging.getLogger("ecefast.components.nemo.domain.subbasins")


def generate_subbasin_masks(src_dir, tgt_dir, name):
    """Generate subbasin masks from mesh_mask file.

    Args:
        src_dir: Path to directory containing mesh_mask_{name}.nc
        tgt_dir: Path to target directory for output
        name: Bathymetry name to identify the correct mesh_mask_{name}.nc file
    """
    mesh_file = f"mesh_mask_{name}.nc"
    logger.info("Generating subbasins from %s", mesh_file)

    # Load mesh_mask
    mesh = xr.open_dataset(os.path.join(src_dir, mesh_file))

    # Debug: show available variables and dimensions
    logger.debug("Available variables: %s", list(mesh.data_vars.keys()))
    logger.debug("Dimensions: %s", dict(mesh.sizes))

    # Extract surface mask and coordinates
    # mesh_mask typically has dimensions (time_counter, z, y, x) or (t, z, y, x)
    tmask = mesh["tmask"][0, 0, :, :].values  # (y, x) - surface layer

    # Coordinates can be stored in different ways:
    # Option 1: glamt/gphit with time dimension (NEMO 4.x)
    # Option 2: nav_lon/nav_lat without time dimension
    # Try both approaches
    if "glamt" in mesh and len(mesh["glamt"].dims) == 3:
        # Has time dimension: (time_counter, y, x)
        navlon = mesh["glamt"][0, :, :].values
        navlat = mesh["gphit"][0, :, :].values
    elif "glamt" in mesh and len(mesh["glamt"].dims) == 2:
        # No time dimension: (y, x)
        navlon = mesh["glamt"].values
        navlat = mesh["gphit"].values
    elif "nav_lon" in mesh:
        # Alternative naming
        navlon = mesh["nav_lon"].values
        navlat = mesh["nav_lat"].values
    else:
        raise ValueError(f"Cannot find longitude/latitude coordinates. Available vars: {list(mesh.data_vars.keys())}")

    logger.info("Grid shape: %s", tmask.shape)
    logger.info("Longitude range: [%.2f, %.2f]", navlon.min(), navlon.max())
    logger.info("Latitude range: [%.2f, %.2f]", navlat.min(), navlat.max())
    logger.info("Ocean points: %d", np.sum(tmask == 1))

    # Initialize mask arrays
    atlmsk = np.zeros_like(tmask, dtype=int)
    pacmsk = np.zeros_like(tmask, dtype=int)
    indmsk = np.zeros_like(tmask, dtype=int)
    indpacmsk = np.zeros_like(tmask, dtype=int)
    glomsk = np.zeros_like(tmask, dtype=int)

    # Define ocean basin polygons
    # NOTE: Polygons are defined in (longitude, latitude) coordinates

    # Atlantic Ocean (including Mediterranean and Arctic connections)
    atlantic_poly = Polygon(
        [
            (-100.0, 66.0),  # Arctic/North America
            (-85.0, 66.0),
            (-84.0, 71.0),
            (-83.0, 74.0),
            (-82.0, 79.0),
            (-80.0, 84.0),
            (-55.0, 89.0),  # Arctic
            (85.0, 87.0),  # Barents Sea
            (89.0, 85.0),
            (93.0, 72.0),  # Norwegian Sea
            (44.0, 35.0),  # Mediterranean/Red Sea boundary
            (20.0, 14.0),  # East Africa
            (28.0, -81.0),  # Southern Ocean (east)
            (-66.0, -81.0),  # Southern Ocean (west)
            (-74.0, 7.5),  # South America east coast
            (-84.0, 7.8),  # Panama
            (-86.0, 12.0),  # Central America
            (-92.0, 15.8),  # Mexico
            (-96.0, 15.8),
            (-102.0, 21.48),  # Mexico west coast
            (-100.0, 66.0),  # Close loop
        ]
    )

    # Pacific Ocean - Eastern part (Americas side)
    # Extends from dateline to Central American coast
    pacific_east = Polygon(
        [
            (-180.1, 66.0),  # Bering Strait area
            (-158.0, 65.0),
            (-120.0, 58.0),  # Alaska
            (-115.0, 45.0),  # Pacific Northwest
            (-108.0, 21.0),  # Baja California
            (-102.0, 21.48),
            (-96.0, 15.8),  # Central America west coast
            (-92.0, 15.8),
            (-86.0, 12.0),
            (-84.0, 7.8),  # Panama Pacific side
            (-74.0, 7.5),  # Colombia
            (-66.0, -81.0),  # Southern Ocean (west)
            (-180.1, -81.0),  # Southern Ocean at dateline
            (-180.1, 66.0),  # Close loop at dateline
        ]
    )

    # Pacific Ocean - Western part (Asia/Australia side)
    # Extends from Asian coast to dateline
    pacific_west = Polygon(
        [
            (180.0, 66.0),  # Bering Strait area at dateline
            (99.0, 48.0),  # East Asia
            (100.0, 1.0),  # Malaysia/Indonesia boundary
            (104.0, -6.0),  # Java
            (112.0, -7.8),  # Indonesia
            (120.0, -9.0),  # Timor Sea
            (142.0, -27.0),  # East Australia
            (150.0, -81.0),  # Southern Ocean (east of Australia)
            (180.0, -81.0),  # Southern Ocean at dateline
            (180.0, 66.0),  # Close loop at dateline
        ]
    )

    # Combine Pacific polygons
    pacific_poly = MultiPolygon([pacific_east, pacific_west])

    # Indian Ocean
    # From East Africa to Indonesia
    indian_poly = Polygon(
        [
            (44.0, 35.0),  # Red Sea/Persian Gulf
            (20.0, 14.0),  # East Africa
            (28.0, -81.0),  # Southern Ocean (west)
            (150.0, -81.0),  # Southern Ocean (east)
            (142.0, -27.0),  # East Australia
            (120.0, -9.0),  # Timor Sea
            (112.0, -7.8),  # Indonesia
            (104.0, -6.0),  # Java
            (100.0, 1.0),  # Malaysia/Sumatra
            (96.0, 16.0),  # Bay of Bengal
            (96.0, 35.0),  # Arabian Sea
            (44.0, 35.0),  # Close loop
        ]
    )

    # Validate polygons
    logger.debug("Validating polygons...")
    for poly_name, poly in [
        ("Atlantic", atlantic_poly),
        ("Pacific_East", pacific_east),
        ("Pacific_West", pacific_west),
        ("Indian", indian_poly),
    ]:
        if not poly.is_valid:
            logger.warning("%s polygon is INVALID!", poly_name)
        else:
            logger.debug("  %s: valid (area=%.2f)", poly_name, poly.area)

    # Build masks by checking each ocean point
    logger.debug("Classifying ocean points into basins...")
    for j in range(navlon.shape[0]):
        for i in range(navlon.shape[1]):
            if tmask[j, i] == 1:  # only ocean cells
                lon = navlon[j, i]
                lat = navlat[j, i]
                point = Point(lon, lat)

                # Use consistent contains() method for all basins
                if atlantic_poly.contains(point):
                    atlmsk[j, i] = 1
                elif pacific_poly.contains(point):  # Check Pacific (MultiPolygon)
                    pacmsk[j, i] = 1
                elif indian_poly.contains(point):
                    indmsk[j, i] = 1
                # If none match, point remains unassigned (0)

    # Statistics
    logger.info("Basin statistics:")
    logger.info("  Atlantic points: %d (%.1f%%)", np.sum(atlmsk), 100 * np.sum(atlmsk) / np.sum(tmask))
    logger.info("  Pacific points: %d (%.1f%%)", np.sum(pacmsk), 100 * np.sum(pacmsk) / np.sum(tmask))
    logger.info("  Indian points: %d (%.1f%%)", np.sum(indmsk), 100 * np.sum(indmsk) / np.sum(tmask))
    unassigned = np.sum(tmask) - np.sum(atlmsk) - np.sum(pacmsk) - np.sum(indmsk)
    logger.info("  Unassigned points: %d (%.1f%%)", unassigned, 100 * unassigned / np.sum(tmask))

    # Derived masks
    indpacmsk = ((pacmsk == 1) | (indmsk == 1)).astype(int)
    glomsk[tmask == 1] = 1

    # Create output dataset
    ds = xr.Dataset(
        data_vars={
            "atlmsk": (("y", "x"), atlmsk),
            "pacmsk": (("y", "x"), pacmsk),
            "indmsk": (("y", "x"), indmsk),
            "indpacmsk": (("y", "x"), indpacmsk),
            "glomsk": (("y", "x"), glomsk),
        },
        coords={"navlon": (("y", "x"), navlon), "navlat": (("y", "x"), navlat)},
    )

    # Add metadata
    ds["atlmsk"].attrs = {"long_name": "Atlantic Ocean mask", "units": "1"}
    ds["pacmsk"].attrs = {"long_name": "Pacific Ocean mask", "units": "1"}
    ds["indmsk"].attrs = {"long_name": "Indian Ocean mask", "units": "1"}
    ds["indpacmsk"].attrs = {"long_name": "Indo-Pacific Ocean mask", "units": "1"}
    ds["glomsk"].attrs = {"long_name": "Global ocean mask", "units": "1"}

    # Write to file
    os.makedirs(tgt_dir, exist_ok=True)
    output_path = os.path.join(tgt_dir, "subbasins.nc")
    ds.to_netcdf(output_path)
    logger.info("Written subbasin masks to %s", output_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate ocean subbasin masks for NEMO simulations")

    parser.add_argument(
        "--src_dir", type=str, required=True, help="Path to source directory containing mesh_mask_{name}.nc"
    )
    parser.add_argument("--tgt_dir", type=str, required=True, help="Path to target directory for output subbasins.nc")
    parser.add_argument("--name", type=str, required=True, help="Bathymetry name (identifies mesh_mask_{name}.nc)")
    parser.add_argument("--log-level", type=str, default="INFO", help="Log level (DEBUG, INFO, WARNING, ...)")

    args = parser.parse_args()
    setup_logger(args.log_level)

    generate_subbasin_masks(args.src_dir, args.tgt_dir, args.name)
