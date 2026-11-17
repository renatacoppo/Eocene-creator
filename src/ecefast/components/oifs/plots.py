"""Maps of the OIFS surface files of two EC-Earth trees, for ``ecefast <period> plot``.

The land-sea mask is also brought onto another grid by conservative remapping (:func:`land_fraction_on`), for the
coupling maps. Each file is read from both trees on a regular grid (:func:`ecefast.core.plotting.load_grib`) and every variable
that differs is drawn (:func:`ecefast.core.plotting.compare_datasets`); the spectral initial state only as
orography. Vegetation and soil types are drawn as classes, without a difference.
"""

import os

import numpy as np
import xarray as xr

from ecefast.core.grib import extract_grid_info
from ecefast.core.layout import oifs_initial_dir
from ecefast.core.plotting import compare_datasets, load_grib, remap_conservative

from .corners import create_corner_grid
from .land_cover import land_cover_types, soil_types

# standard gravity (m s-2), WMO; the IFS constant RG: surface geopotential z / g = orography
STANDARD_GRAVITY = 9.80665
# IFS treats a grid point as land where the land-sea mask lsm > 0.5 (IFS Documentation, Part IV, chapter 8)
LAND_THRESHOLD = 0.5
# variables of the spectral initial state that are drawn: only the surface geopotential, as orography
SPECTRAL_FIELDS = ["z"]
# class fields: drawn with a labelled colour bar, without a difference
TAB20 = [
    "#1f77b4", "#aec7e8", "#ff7f0e", "#ffbb78", "#2ca02c", "#98df8a", "#d62728", "#ff9896", "#9467bd", "#c5b0d5",
    "#8c564b", "#c49c94", "#e377c2", "#f7b6d2", "#7f7f7f", "#c7c7c7", "#bcbd22", "#dbdb8d", "#17becf", "#9edae5",
    "#393b79",
]  # fmt: skip
# class 0 (no vegetation, no soil: sea) in light grey
CLASS_FIELDS = {
    name: {value: (f"{value} {label}", TAB20[value - 1] if value else "#f0f0f0") for value, label in classes.items()}
    for name, classes in (("tvh", land_cover_types), ("tvl", land_cover_types), ("slt", soil_types))
}


def oifs_files(tree: str, grid: str, startdate: str, climate_version: str) -> dict[str, str]:
    """The OIFS surface files of a tree that the plots compare.

    Parameters
    ----------
    tree : str
        Root of an EC-Earth tree.
    grid, startdate, climate_version : str
        ``grids.oifs`` of the configuration.

    Returns
    -------
    dict
        ``{name: path}``: ``ICMGGECE4INIT``, ``ICMSHECE4INIT`` (initial state), ``ICMCLECE4`` and
        ``bare_soil_albedos`` (climate files).
    """
    initial = oifs_initial_dir(tree, grid, startdate)
    climate = os.path.join(tree, "oifs", grid, climate_version)
    return {
        "ICMGGECE4INIT": os.path.join(initial, "ICMGGECE4INIT"),
        "ICMSHECE4INIT": os.path.join(initial, "ICMSHECE4INIT"),
        "ICMCLECE4": os.path.join(climate, "ICMCLECE4"),
        "bare_soil_albedos": os.path.join(climate, "bare_soil_albedos.grb"),
    }


def read_land(path: str) -> xr.DataArray:
    """The land-sea mask ``lsm`` of an ``ICMGGECE4INIT`` on the regular plotting grid (land fraction, 0 to 1)."""
    return load_grib(path, ["lsm"])["lsm"].squeeze(drop=True)


def land_fraction_on(icmgg: str, grid: str, target: str, workdir: str) -> np.ndarray:
    """Share of each cell of another grid that OIFS land points cover, by conservative remapping.

    The land-sea mask is made binary on the OIFS grid first (land where ``lsm > LAND_THRESHOLD``, as IFS does),
    then remapped with ``cdo remapcon`` from the reduced Gaussian grid with cell corners
    (:func:`ecefast.components.oifs.corners.create_corner_grid`).

    Parameters
    ----------
    icmgg : str
        The ``ICMGGECE4INIT`` with the land-sea mask; it may mix GRIB1 and GRIB2 messages.
    grid : str
        Its OIFS grid, e.g. ``TL63L31``.
    target : str
        CDO grid file of the target grid, with cell bounds.
    workdir : str
        Directory for the intermediate files.

    Returns
    -------
    numpy.ndarray
        Land fraction (0 to 1) on the target grid; NaN in a target cell that has no area (degenerate bounds).

    Raises
    ------
    ValueError
        If ``grid`` is not an OIFS grid name (``T<L|CO><truncation>L<levels>``).
    """
    info = extract_grid_info(grid)
    if info is None:
        raise ValueError(f"'{grid}' is not an OIFS grid name such as TL63L31")
    kind, spectral, _ = info
    masked = os.path.join(workdir, "oifs_grid_masked.nc")
    create_corner_grid(icmgg, kind, spectral, os.path.join(workdir, "oifs_grid.nc"), workdir, masked)
    return remap_conservative(f"-gtc,{LAND_THRESHOLD} {masked}", target)


def _orography(ds: xr.Dataset) -> xr.Dataset:
    """Surface geopotential ``z`` (m2 s-2) as orography (m)."""
    orography = ds["z"] / STANDARD_GRAVITY
    orography.attrs = dict(ds["z"].attrs) | {"units": "m", "long_name": "orography (z / g)"}
    return xr.Dataset({"orography": orography})


def compare_file(
    name: str,
    reference_path: str,
    test_path: str,
    out_dir: str,
    labels: tuple[str, str],
    land: tuple[xr.DataArray, xr.DataArray] | None = None,
) -> dict:
    """Draw every variable of an OIFS file that differs between two trees (:func:`ecefast.core.plotting.compare_datasets`).

    Parameters
    ----------
    name : str
        Name of the file (a key of :func:`oifs_files`): the figures go to ``<out_dir>/<name>/``.
    reference_path, test_path : str
        The file in the two trees.
    out_dir : str
        Folder of the OIFS figures.
    labels : tuple of str
        Names of the reference and test trees.
    land : tuple of xarray.DataArray, optional
        Land fraction of the reference and test trees on the regular plotting grid (:func:`read_land`): drawn as
        coastlines, and the difference is shown only where both have the same surface type.

    Returns
    -------
    dict
        The summary of :func:`ecefast.core.plotting.compare_datasets`.
    """
    names = SPECTRAL_FIELDS if name == "ICMSHECE4INIT" else None
    reference, test = load_grib(reference_path, names), load_grib(test_path, names)
    if names:
        reference, test = _orography(reference), _orography(test)
    same_surface = None if land is None else (land[0] > LAND_THRESHOLD) == (land[1] > LAND_THRESHOLD)
    outlines = land if land is not None else (None, None)
    return compare_datasets(reference, test, name, out_dir, labels, same_surface, outlines, CLASS_FIELDS)


def compare_oifs(reference_files: dict[str, str], test_files: dict[str, str], out_dir: str, labels: tuple[str, str]):
    """Compare the OIFS surface files of two trees (:func:`oifs_files`), drawing what differs.

    Parameters
    ----------
    reference_files, test_files : dict
        The files of the two trees, ``{name: path}``.
    out_dir : str
        Folder of the OIFS figures.
    labels : tuple of str
        Names of the reference and test trees.

    Returns
    -------
    dict
        ``{name: summary}`` of every file (:func:`compare_file`).
    """
    land = (read_land(reference_files["ICMGGECE4INIT"]), read_land(test_files["ICMGGECE4INIT"]))
    return {
        name: compare_file(name, reference_files[name], test_files[name], out_dir, labels, land) for name in test_files
    }
