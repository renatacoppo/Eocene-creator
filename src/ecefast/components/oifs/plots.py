"""Maps of the OIFS surface files of two EC-Earth trees, for ``ecefast <period> plot``.

Each file is read from both trees on a regular grid (:func:`ecefast.core.plotting.load_grib`). A variable that
differs gets one figure (reference, test, difference); monthly fields (``ICMCLECE4``) get two, the annual mean and
the seasonal range (largest minus smallest month). Vegetation and soil types are drawn as classes, without a
difference. Variables that do not differ are only listed in the summary.
"""

import logging
import os

import numpy as np
import xarray as xr

from ecefast.core.layout import oifs_initial_dir
from ecefast.core.plotting import load_grib, plot_comparison, save_figure

from .land_cover import land_cover_types, soil_types

logger = logging.getLogger(__name__)

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


def _with_attrs(field: xr.DataArray, like: xr.DataArray) -> xr.DataArray:
    field.attrs = dict(like.attrs)
    return field


def _orography(ds: xr.Dataset) -> xr.Dataset:
    """Surface geopotential ``z`` (m2 s-2) as orography (m)."""
    orography = _with_attrs(ds["z"] / STANDARD_GRAVITY, ds["z"])
    orography.attrs.update(units="m", long_name="orography (z / g)")
    return xr.Dataset({"orography": orography})


def _time_dim(field: xr.DataArray) -> str | None:
    """The dimension of a monthly field (more than one time step), or None."""
    return next((dim for dim in field.dims if "time" in dim and field.sizes[dim] > 1), None)


def _panels(field: xr.DataArray) -> dict[str, xr.DataArray]:
    """The 2D maps of a field: itself, or the annual mean and seasonal range of a monthly field. A field with
    layers (e.g. the snow layers of ``sd``) is drawn at its first layer."""
    time = _time_dim(field)
    layers = [dim for dim in field.dims if dim != time and dim not in ("lat", "lon") and field.sizes[dim] > 1]
    field = _with_attrs(field.isel({dim: 0 for dim in layers}), field)
    if time is None:
        return {"": field}
    mean = _with_attrs(field.mean(time), field)
    spread = _with_attrs(field.max(time) - field.min(time), field)
    return {"mean": mean, "range": spread}


def _title(name: str, field: xr.DataArray, file: str, panel: str) -> str:
    long_name = field.attrs.get("long_name", "")
    what = {"mean": ", annual mean", "range": ", seasonal range (largest - smallest month)"}.get(panel, "")
    layers = [dim for dim in field.dims if "time" not in dim and dim not in ("lat", "lon") and field.sizes[dim] > 1]
    first = f", first {layers[0]} layer" if layers else ""
    return f"{name}{f' ({long_name})' if long_name else ''}{what}{first}: {file}"


def compare_file(
    name: str,
    reference_path: str,
    test_path: str,
    out_dir: str,
    labels: tuple[str, str],
    land: tuple[xr.DataArray, xr.DataArray] | None = None,
) -> dict:
    """Draw every variable of an OIFS file that differs between two trees.

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
        For ``summary.yml``: ``changed`` (variable: largest absolute difference), ``unchanged``, and the variables
        found in one tree only (``only_in_reference``, ``only_in_test``).
    """
    names = SPECTRAL_FIELDS if name == "ICMSHECE4INIT" else None
    reference, test = load_grib(reference_path, names), load_grib(test_path, names)
    if names:
        reference, test = _orography(reference), _orography(test)
    summary: dict = {
        "changed": {},
        "unchanged": [],
        "only_in_reference": sorted(set(reference.data_vars) - set(test.data_vars)),
        "only_in_test": sorted(set(test.data_vars) - set(reference.data_vars)),
    }
    same_surface = None
    if land is not None:
        same_surface = (land[0] > LAND_THRESHOLD) == (land[1] > LAND_THRESHOLD)
    for variable in [v for v in test.data_vars if v in reference.data_vars]:
        before, after = reference[variable], test[variable]
        if before.shape != after.shape:
            logger.warning("Plots: %s of %s has different shapes in the two trees, not drawn", variable, name)
            continue
        if np.allclose(before.values, after.values, equal_nan=True):
            summary["unchanged"].append(variable)
            continue
        summary["changed"][variable] = round(float(np.nanmax(np.abs(after.values - before.values))), 6)
        before_maps, after_maps = _panels(before), _panels(after)
        for panel in before_maps:
            ref_map, test_map = before_maps[panel], after_maps[panel]
            if ref_map.squeeze(drop=True).ndim != 2:
                logger.warning("Plots: %s of %s is not a 2D field (%s), not drawn", variable, name, ref_map.dims)
                break
            on_plot_grid = land is not None and ref_map.squeeze(drop=True).shape == land[0].shape
            fig = plot_comparison(
                ref_map,
                test_map,
                labels,
                _title(variable, after, name, panel),
                same_surface=same_surface if on_plot_grid and variable not in CLASS_FIELDS else None,
                outlines=land if land is not None else (None, None),
                categories=CLASS_FIELDS.get(variable),
            )
            save_figure(fig, os.path.join(out_dir, name, f"{variable}{f'_{panel}' if panel else ''}.png"))
    logger.info("Plots: %s, %d variables differ, %d do not", name, len(summary["changed"]), len(summary["unchanged"]))
    return summary


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
