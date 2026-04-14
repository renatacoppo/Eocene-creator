"""Some utilities for OIFS grid definition"""
import re
import os
import numpy as np
import xarray as xr
import subprocess
from cdo import Cdo
cdo = Cdo()

# CDO grib2 options
GRIB2="-f grb2 --eccodes"
GRIB1="-f grb1 --eccodes"
NC4='-f nc4 --eccodes'

def unpack_grib_file(inputfile, tmpfile):
    """
    Unpack a GRIB file using grib_copy.
    This is used to split the GRIB messages into GRIB1 and GRIB2.
    """
    print(f"Unpacking GRIB file {inputfile} into {tmpfile}_grib1 and {tmpfile}_grib2")
    subprocess.run(["grib_copy", "-w", "edition=1", inputfile, f"{tmpfile}_grib1"], check=True)
    subprocess.run(["grib_copy", "-w", "edition=2", inputfile, f"{tmpfile}_grib2"], check=True)
    return f"{tmpfile}_grib1", f"{tmpfile}_grib2"

def repack_grib_file(grib1, grib2, outputfile, clean=True):

    """
    Repack a GRIB file using grib_copy.
    This is used to merge the GRIB1 and GRIB2 files back together.
    """
    if os.path.exists(outputfile):
        os.remove(outputfile)
    if not os.path.exists(grib1):
        print(f"Repacking GRIB file {grib2} into {outputfile}")
        subprocess.run(["grib_copy", grib2, outputfile], check=True)
    elif not os.path.exists(grib2):
        print(f"Repacking GRIB file {grib1} into {outputfile}")
        subprocess.run(["grib_copy", grib1, outputfile], check=True)
    else:
        print(f"Repacking GRIB file {grib1} and {grib2} into {outputfile}")
        subprocess.run(["grib_copy", grib1, grib2, outputfile], check=True)   

    # cleanup
    if clean:
        for file in [grib1, grib2]:
            if os.path.exists(file):
                os.remove(file)

def ecmwf_grid(kind):
    """Get the info on the grid to find the right ECMWF file"""
    
    ecmwf_name = {
        'L': 'l_2',
        'CO': '_4',
        'Q': '_2'
    }

    return ecmwf_name[kind.upper()]

def extract_grid_info(string):
    """Extract grid info from a string"""
    string = string.upper()
    pattern = r'T(CO|L)(\d+)L(\d+)'
    match = re.match(pattern, string)
    if match:
        grid_type = match.group(1)
        spectral = int(match.group(2))
        num_levels = int(match.group(3))
        return grid_type, spectral, num_levels
    
    return None