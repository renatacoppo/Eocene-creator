"""Some utilities for OIFS grid definition"""
import re
import os
import tempfile
import shutil
import logging
import numpy as np
import xarray as xr
import xesmf as xe
import subprocess
from cdo import Cdo
cdo = Cdo()

loggy = logging.getLogger(__name__)

# CDO grib2 options
GRIB2="-f grb2 --eccodes"
GRIB1="-f grb1 --eccodes"
NC4='-f nc4 --eccodes'


def nullify_grib(inputfile, outputfile, variables, filter_method="shortName"):
    """"
    Set to zero a variable in a GRIB file.
    This is done by unpacking the GRIB file, setting it to zero with CDO and then repacking it
    """ 

    loggy.info(f"Nullifying variable {variables} in GRIB file {inputfile}")
    
    if os.path.exists(inputfile):

        varlist=','.join(variables)
        loggy.debug(f"Variable list: {varlist}")

        singlefile = cdo.selname(varlist, input=inputfile, options="--eccodes")
        tempfile = cdo.mulc(0, input=singlefile, options="--eccodes")
        cdo.copy(input=tempfile, output="nullify.nc")
        replace_field(inputfile, tempfile, outputfile, variables, filter_method=filter_method)
        os.remove("nullify.nc")
    else: 
        loggy.warning(f'{inputfile} does not exist!')


def modify_grib(inputfile, outputfile, myfunction, spectral=False, **kwargs):
    """
    Modify a GRIB file using a function.
    Unpack grib1 and grib2, convert them to gaussian regular, 
    apply the function and the convert them back to grib1 and grib2.
    This is deprecated in OIFS cy48 since all data should be GRIB2
    """

    loggy.info(f"Modifying GRIB file {inputfile} using {myfunction.__name__}")

    # Unpack the GRIB file
    grib1, grib2 = unpack_grib_file(inputfile, "tmp")

    for file in [grib1, grib2]:
    
        if os.path.exists(file):
            loggy.info(f"Converting to netcdf file {file}")

            # Convert to netcdf: if spectral use sp2gpl, else use setgridtype
            if spectral:
                loggy.debug("Using spectral conversion (sp2gpl)")
                netcdf = cdo.sp2gpl(input=file, options=NC4)
            else:
                loggy.debug("Using gridtype conversion (regular)")
                netcdf = cdo.setgridtype("regular", input=file, options=NC4)
            loggy.info(f"Modifying GRIB file {file} using function {myfunction.__name__}")

            # open the netcdf and modify it
            loggy.debug(f"Opening dataset {netcdf}")
            field = xr.open_dataset(netcdf,  engine="netcdf4")
            field = myfunction(field, **kwargs)
            
            # Save to a temporary file and remove
            with tempfile.NamedTemporaryFile(delete=False) as tmpfile:
                temp_path = tmpfile.name
            field.to_netcdf(temp_path)
            shutil.move(temp_path, netcdf)
            
            loggy.info(f"Converting back to GRIB file {file}")
            grib = GRIB1 if file == grib1 else GRIB2
            if spectral:
                cdo.gp2spl(input=netcdf, output=file, options=grib)
            else:
                cdo.remapnn(inputfile, input=netcdf, output=file, options=grib)

    repack_grib_file(grib1, grib2, outputfile, clean=True)

def modify_single_grib(inputfile, outputfile, variables, myfunction, spectral=False, filter_method="shortName", **kwargs):
    """
    Modify a GRIB file using a function.
    Unpack grib1 and grib2, convert them to gaussian regular, 
    apply the function and the convert them back to grib1 and grib2.
    """

    # Unpack the GRIB file
    
    if os.path.exists(inputfile):
        loggy.info(f"Modifying variables {variables} in {inputfile}")

        varlist=','.join(variables)
        singlefile = cdo.selname(varlist, input=inputfile, options="--eccodes")
        grib_version = detect_grib_version(singlefile)
        loggy.debug(f"Detected GRIB version: {grib_version}")

        # Convert to netcdf: if spectral use sp2gpl, else use setgridtype
        if spectral:
            netcdf = cdo.sp2gpl(input=singlefile, options=NC4)
        else:
            netcdf = cdo.setgridtype("regular", input=singlefile, options=NC4)
        loggy.info(f"Modifying GRIB file {inputfile} using function {myfunction.__name__}")

        # open the netcdf and modify it
        field = xr.open_dataset(netcdf,  engine="netcdf4", decode_times=False)
        field = myfunction(field, var=variables, **kwargs)
        
        # Save to a temporary file and remove
        with tempfile.NamedTemporaryFile(delete=False) as tmpfile:
            temp_path = tmpfile.name
        field.to_netcdf(temp_path)
        shutil.move(temp_path, netcdf)

        loggy.info(f"Repacking modified GRIB for {variables}")
        loggy.info(f"Converting back to GRIB file {singlefile}")

        grib = GRIB1 if grib_version==1 else GRIB2

        if spectral:
            cdo.gp2spl(input=netcdf, output=singlefile, options=grib)
        else:
            cdo.remapnn(inputfile, input=netcdf, output=singlefile, options=grib)
        cdo.copy(input=singlefile, output='singlefile.nc')

        replace_field(inputfile, singlefile, outputfile, variables, filter_method=filter_method)
        os.remove("singlefile.nc")
    else: 
        loggy.warning(f'{inputfile} does not exist!')

def truncate_grib_file(inputfile, outputfile, variables, orig=63, trunc=1):
    """
    Truncate the GRIB file to a specific size.
    """
    varlist=','.join(variables)
    loggy.info(f"Truncating variables {varlist} from {inputfile}")

    trunc = cdo.sp2sp(str(trunc), input=f"-selname,{varlist} {inputfile}", options=NC4)
    compact = cdo.sp2sp(str(orig), input=trunc, options=GRIB2)
    where_expr = ",".join([f"shortName!={v}" for v in variables])
    loggy.debug(f"Filtering expression: {where_expr}")

    with tempfile.NamedTemporaryFile(delete=False) as tmpfile:
            temp_path = tmpfile.name
    subprocess.run(["grib_copy", "-w", where_expr, inputfile, temp_path], check=True)
    subprocess.run(["grib_copy", compact, temp_path, outputfile], check=True)


def detect_grib_version(filepath):
    """Detect the GRIB version of a file."""
    with open(filepath, "rb") as f:
        header = f.read(8)  # read enough bytes
        if header[:4] != b"GRIB":
            return None  # Not a GRIB file
        return header[7]  # Edition number (1 or 2)

def replace_field(inputfile, singlefile, outputfile, variable, filter_method="shortName"):
    """
    Replace a field in a GRIB file using grib_copy.
    """
    
    loggy.debug(f"Replacing variables {variable} in {inputfile}")
    
    # allow for replacament
    if inputfile == outputfile:
        shutil.move(inputfile, "tmp.grib")
        inputfile = "tmp.grib"

    if os.path.exists(outputfile):
        os.remove(outputfile)
    if os.path.exists("filtered.grib"):
        os.remove("filtered.grib")
    if isinstance(variable, str):
        variable = [variable]
    if filter_method == "shortName":
        # condition: where shortName is NOT the variable to be replaced
        where_expr = ",".join([f"shortName!={v}" for v in variable])
    elif filter_method == "paramId":
        # condition is not the paramId of the variable to be replaced
        where_expr = ",".join([f"paramId!={int(v.replace('code',''))}" for v in variable])
    else:
        raise ValueError(f"Unknown filter method: {filter_method}")
    subprocess.run([
        "grib_copy", "-w", where_expr,  #
        inputfile, "filtered.grib"], check=True)
    if os.path.exists("filtered.grib"):
        subprocess.run(["grib_copy", "filtered.grib", singlefile, outputfile], check=True)
        os.remove("filtered.grib")
    else:
        shutil.copyfile(singlefile, outputfile)
    os.remove(singlefile)
    if os.path.exists("tmp.grib"):
        os.remove("tmp.grib")
    
def modify_value(field, var, newvalue):
    """
    Modify a field in the GRIB file setting it to a constant
    """
    for v in var:
        if v in field.variables:
            loggy.debug(f"Setting variable {v} to constant value {newvalue}")
            field[v].data = np.full(field[v].shape, newvalue)
    return field

def replace_value(field, var, newfield):
    """
    Replace the field in a dataset with a dataarray
    """
    if 'time' not in newfield.dims:
        loggy.debug("Expanding time dimension for new field")
        newfield = newfield.expand_dims('time', axis=0)

    newfield = newfield.transpose('time', 'lat', 'lon')

    for v in var:
        if v in field.variables:
            loggy.debug(f"Replacing variable {v} in the field")
            field[v].data = newfield.data
    return field


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
    
def spectral2gaussian(spectral, kind):
    """Convert spectral resolution to gaussian"""
    if kind.upper() == "CO":
        return int(spectral) + 1
    if kind == "L":
        return int((int(spectral) + 1) / 2)

    raise ValueError("Unknown grid type")


def regrid_dataset(data, regrid_to_reference):
    """
    Regrid a DataArray to match the grid of another DataArray.
    """
    regridder = xe.Regridder(
        data, 
        regrid_to_reference, 
        method='bilinear'
    )
    return regridder(data)

def unpack_grib_file(inputfile, tmpfile):
    """
    Unpack a GRIB file using grib_copy.
    This is used to split the GRIB messages into GRIB1 and GRIB2.
    """
    loggy.info(f"Unpacking GRIB file {inputfile} into {tmpfile}_grib1 and {tmpfile}_grib2")
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
        loggy.info(f"Repacking GRIB file {grib2} into {outputfile}")
        subprocess.run(["grib_copy", grib2, outputfile], check=True)
    elif not os.path.exists(grib2):
        loggy.info(f"Repacking GRIB file {grib1} into {outputfile}")
        subprocess.run(["grib_copy", grib1, outputfile], check=True)
    else:
        loggy.info(f"Repacking GRIB file {grib1} and {grib2} into {outputfile}")
        subprocess.run(["grib_copy", grib1, grib2, outputfile], check=True)   

    # cleanup
    if clean:
        for file in [grib1, grib2]:
            if os.path.exists(file):
                loggy.debug(f"Removing temporary file {file}")
                os.remove(file)


def count_grib_messages(inputfile):
    """Return the number of messages in a GRIB file."""
    result = subprocess.run(
        ["grib_count", inputfile],
        check=True, capture_output=True, text=True
    )
    n = int(result.stdout.strip())
    loggy.debug(f"{inputfile} contains {n} messages")
    return n

def flatten_grib_steps(inputfile, n_messages=None):
    """
    For each message in a GRIB file, set dataDate to its validityDate and
    zero out step/forecastTime, then reassemble in place.
    Equivalent of the bash flatten-to-analysis loop.
    """
    if n_messages is None:
        n_messages = count_grib_messages(inputfile)

    loggy.info(f"Flattening {n_messages} messages in {inputfile}")

    tmp_in = "tmp_input.grb"
    shutil.copyfile(inputfile, tmp_in)

    with tempfile.NamedTemporaryFile(suffix=".grb", delete=False) as out_f:
        outputfile_tmp = out_f.name

    with open(outputfile_tmp, "wb") as out_stream:
        for i in range(1, n_messages + 1):
            with tempfile.NamedTemporaryFile(suffix=".grb", delete=False) as msg_f:
                msg_file = msg_f.name
            with tempfile.NamedTemporaryFile(suffix=".grb", delete=False) as flat_f:
                flat_file = flat_f.name

            subprocess.run(["grib_copy", "-w", f"count={i}", tmp_in, msg_file], check=True)

            vdate = subprocess.run(
                ["grib_get", "-p", "validityDate", msg_file],
                check=True, capture_output=True, text=True
            ).stdout.strip()
            loggy.debug(f"Message {i}: validityDate={vdate}")

            subprocess.run([
                "grib_set", "-s",
                f"dataDate={vdate},step=0,startStep=0,endStep=0,forecastTime=0",
                msg_file, flat_file
            ], check=True)

            with open(flat_file, "rb") as f:
                out_stream.write(f.read())

            os.remove(msg_file)
            os.remove(flat_file)

    shutil.move(outputfile_tmp, inputfile)
    os.remove(tmp_in)