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

def nullify_grib(
    inputfile: str,
    outputfile: str,
    variables: list[str],
    filter_method: str = "shortName",
    debug: bool = False,
) -> None:
    """
    Set one or more variables in a GRIB file to zero.

    Unpacks the requested variables from the GRIB file, multiplies them by
    zero with CDO, and writes the zeroed fields back into the file in place
    of the originals via ``replace_field``.

    Args:
        inputfile: Path to the source GRIB file.
        outputfile: Path to write the modified GRIB file to.
        variables: List of variable identifiers to zero out. Interpretation
            (shortName vs paramId/"codeNNN") depends on ``filter_method``.
        filter_method: Matching method passed through to ``replace_field``,
            either "shortName" or "paramId". Defaults to "shortName".
        debug: If True, keep a copy of the zeroed field as a netcdf file
            ("debug_nullify_grib.nc") for inspection instead of discarding
            it. Defaults to False.

    Returns:
        None. The zeroed output is written to ``outputfile``.
    """
    loggy.info(f"Nullifying variables {variables} in GRIB file {inputfile}")

    if not os.path.exists(inputfile):
        loggy.warning(f"{inputfile} does not exist!")
        return

    varlist = ",".join(variables)
    loggy.debug(f"Variable list: {varlist}")

    singlefile = cdo.selname(varlist, input=inputfile, options="--eccodes")
    zeroed_file = cdo.mulc(0, input=singlefile, options="--eccodes")

    if debug:
        debug_path = f"debug_nullify_grib_{'_'.join(variables)}.nc"
        cdo.copy(input=zeroed_file, output=debug_path)
        loggy.debug(f"Debug copy of zeroed field written to {debug_path}")

    replace_field(inputfile, zeroed_file, outputfile, variables, filter_method=filter_method, debug=debug)


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

def modify_single_grib(
    inputfile: str,
    outputfile: str,
    variables: list[str],
    myfunction: callable,
    spectral: bool = False,
    filter_method: str = "shortName",
    debug: bool = False,
    **kwargs,
) -> None:
    """
    Modify one or more variables in a GRIB file using a custom function.

    Unpacks the requested variables, converts them to a regular grid (or
    spherical harmonics if ``spectral=True``), applies ``myfunction`` to the
    resulting xarray dataset, converts the result back to GRIB (preserving
    the original GRIB edition), and writes it back into the file in place
    of the originals via ``replace_field``.

    Args:
        inputfile: Path to the source GRIB file.
        outputfile: Path to write the modified GRIB file to.
        variables: List of variable identifiers to modify. Interpretation
            (shortName vs paramId/"codeNNN") depends on ``filter_method``.
        myfunction: Callable applied to the opened dataset. Called as
            ``myfunction(field, var=variables, **kwargs)`` and must return
            a modified xarray.Dataset.
        spectral: If True, convert to/from spherical harmonics (sp2gpl /
            gp2spl) instead of a regular grid. Defaults to False.
        filter_method: Matching method passed through to ``replace_field``,
            either "shortName" or "paramId". Defaults to "shortName".
        debug: If True, keep a copy of the modified GRIB as a netcdf file
            ("debug_modify_single_grib.nc") for inspection instead of
            discarding it. Defaults to False.
        **kwargs: Additional keyword arguments forwarded to ``myfunction``.

    Returns:
        None. The modified output is written to ``outputfile``.
    """
    if not os.path.exists(inputfile):
        loggy.warning(f"{inputfile} does not exist!")
        return

    loggy.info(f"Modifying variables {variables} in {inputfile}")

    varlist = ",".join(variables)
    singlefile = cdo.selname(varlist, input=inputfile, options="--eccodes")
    grib_version = detect_grib_version(singlefile)
    loggy.debug(f"Detected GRIB version: {grib_version}")

    # Convert to netcdf: if spectral use sp2gpl, else use setgridtype
    if spectral:
        netcdf = cdo.sp2gpl(input=singlefile, options=NC4)
    else:
        netcdf = cdo.setgridtype("regular", input=singlefile, options=NC4)
    loggy.info(f"Modifying GRIB file {inputfile} using function {myfunction.__name__}")

    # Open the netcdf and modify it
    field = xr.open_dataset(netcdf, engine="netcdf4", decode_times=False)
    field = myfunction(field, var=variables, **kwargs)

    # Save to a temporary file and swap it in for the original netcdf
    with tempfile.NamedTemporaryFile(delete=False) as tmpfile:
        temp_path = tmpfile.name
    field.to_netcdf(temp_path)
    shutil.move(temp_path, netcdf)

    loggy.info(f"Repacking modified GRIB for {variables}")
    loggy.info(f"Converting back to GRIB file {singlefile}")

    grib = GRIB1 if grib_version == 1 else GRIB2

    if spectral:
        cdo.gp2spl(input=netcdf, output=singlefile, options=grib)
    else:
        cdo.remapnn(inputfile, input=netcdf, output=singlefile, options=grib)

    if debug:
        debug_path = "debug_modify_single_grib.nc"
        cdo.copy(input=singlefile, output=debug_path)
        loggy.debug(f"Debug copy of modified field written to {debug_path}")

    replace_field(inputfile, singlefile, outputfile, variables, filter_method=filter_method, debug=debug)

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

def replace_field(
    inputfile: str,
    singlefile: str,
    outputfile: str,
    variable: str | list[str],
    filter_method: str = "shortName",
    debug: bool = False,
) -> None:
    """
    Replace one or more fields in a GRIB file using grib_copy.

    Filters ``inputfile`` down to everything except the target variable(s),
    then concatenates that filtered content with ``singlefile`` (the
    replacement field(s)) to produce ``outputfile``. If nothing remains
    after filtering (e.g. ``inputfile`` contained only the target
    variable(s)), ``singlefile`` is copied directly to ``outputfile``.

    Args:
        inputfile: Path to the source GRIB file whose field(s) will be
            replaced.
        singlefile: Path to the GRIB file containing the replacement
            field(s). Removed after use unless ``debug`` is True.
        outputfile: Path to write the resulting GRIB file to. May be the
            same path as ``inputfile``.
        variable: Variable identifier, or list of identifiers, to replace.
            A single string is treated as a one-element list.
        filter_method: How to match ``variable`` against GRIB messages,
            either "shortName" or "paramId" (expects "codeNNN"-style
            values). Defaults to "shortName".
        debug: If True, keep the intermediate filtered and moved-input
            files instead of deleting them. Defaults to False.

    Returns:
        None. The combined output is written to ``outputfile``.

    Raises:
        ValueError: If ``filter_method`` is not "shortName" or "paramId".
    """
    loggy.debug(f"Replacing variables {variable} in {inputfile}")

    # Unique, self-describing temp filenames instead of fixed shared names
    with tempfile.NamedTemporaryFile(prefix="replace_field_filtered_", suffix=".grib", delete=False) as f:
        filtered_path = f.name
    moved_input_path = None

    # Allow inputfile == outputfile by working from a moved copy
    if inputfile == outputfile:
        with tempfile.NamedTemporaryFile(prefix="replace_field_movedinput_", suffix=".grib", delete=False) as f:
            moved_input_path = f.name
        shutil.move(inputfile, moved_input_path)
        inputfile = moved_input_path

    if os.path.exists(outputfile):
        os.remove(outputfile)

    if isinstance(variable, str):
        variable = [variable]

    if filter_method == "shortName":
        # condition: where shortName is NOT the variable to be replaced
        where_expr = ",".join([f"shortName!={v}" for v in variable])
    elif filter_method == "paramId":
        # condition: where paramId is NOT the variable to be replaced
        where_expr = ",".join([f"paramId!={int(v.replace('code', ''))}" for v in variable])
    else:
        raise ValueError(f"Unknown filter method: {filter_method}")

    subprocess.run(["grib_copy", "-w", where_expr, inputfile, filtered_path], check=True)

    if os.path.getsize(filtered_path) > 0:
        subprocess.run(["grib_copy", filtered_path, singlefile, outputfile], check=True)
    else:
        shutil.copyfile(singlefile, outputfile)

    if not debug:
        if os.path.exists(filtered_path):
            os.remove(filtered_path)
        os.remove(singlefile)
        if moved_input_path and os.path.exists(moved_input_path):
            os.remove(moved_input_path)
    else:
        loggy.debug(
            f"Keeping intermediate files for inspection (debug=True): "
            f"{filtered_path}, {singlefile}"
            + (f", {moved_input_path}" if moved_input_path else "")
        )
    
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


def regrid_dataset(data, regrid_to_reference, method="remapbil"):
    """
    Regrid a DataArray or Dataset to the grid of a reference object using CDO.

    Parameters
    ----------
    data : xr.DataArray or xr.Dataset
        Data to regrid.
    regrid_to_reference : xr.DataArray or xr.Dataset
        Object whose horizontal grid will be used.
    method : str, optional
        CDO remapping operator (default: 'remapbil').

    Returns
    -------
    xr.DataArray or xr.Dataset
        Regridded object of the same type as the input.
    """

    is_dataarray = isinstance(data, xr.DataArray)

    if is_dataarray:
        varname = data.name or "var"
        ds_in = data.to_dataset(name=varname)
    else:
        ds_in = data

    if isinstance(regrid_to_reference, xr.DataArray):
        ds_ref = regrid_to_reference.to_dataset(
            name=regrid_to_reference.name or "grid"
        )
    else:
        ds_ref = regrid_to_reference

    with tempfile.TemporaryDirectory() as tmpdir:

        infile = os.path.join(tmpdir, "input.nc")
        gridfile = os.path.join(tmpdir, "grid.nc")
        outfile = os.path.join(tmpdir, "output.nc")

        ds_in.to_netcdf(infile)
        ds_ref.to_netcdf(gridfile)

        getattr(cdo, method)(
            gridfile,
            input=infile,
            output=outfile
        )

        ds_out = xr.open_dataset(outfile).load()

    if is_dataarray:
        return ds_out[varname]
    else:
        return ds_out

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