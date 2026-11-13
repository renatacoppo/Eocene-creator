#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
This is a command line tool to create with CDO the descriptor file necessary to
perform a wide range of horizontal interpolation of initial conditions

Authors
Paolo Davini (CNR-ISAC, Nov 2023)
"""

import argparse
import os
import subprocess
from ecefast.core.grib import extract_grid_info, ecmwf_grid

# grid list
grids = ["TL63", "TL95", "TCO95", "TL159", "TCO199", "TCO319", "TCO399"]


def main() -> None:
    """Write ``grids/<grid>.txt`` (CDO grid description) for each grid in ``grids``."""
    parser = argparse.ArgumentParser(description="Create CDO grid descriptor files of the OIFS grids.")
    parser.add_argument(
        "--oifs-bc",
        required=True,
        help="ECMWF climate files folder (climate.v015), e.g. the Atos mirror; needs read rights",
    )
    args = parser.parse_args()
    oifs_bc = args.oifs_bc

    for grid in grids:
        grid = grid.upper()
        print("Processing " + grid + "...")

        grid_type, truncation, _ = extract_grid_info(grid + "L31")
        ecmwf_kind = str(truncation) + ecmwf_grid(grid_type)
        REF_FILE = "10_bats_glcc.grb"
        file_path = os.path.join(oifs_bc, ecmwf_kind, REF_FILE)
        target_path = os.path.join("grids", grid + ".txt")
        # pippo = cdo.griddes(input=file_path, stdout=target_path)
        with open(target_path, "w", encoding="utf8") as fff:
            subprocess.run(["cdo", "griddes", file_path], stdout=fff, check=True)


if __name__ == "__main__":
    main()
