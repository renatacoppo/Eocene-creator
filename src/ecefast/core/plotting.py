"""Shared helpers of the ``ecefast <period> plot`` command: GRIB files on a regular grid, conservative remapping and
nearest-neighbour sampling between grids, comparison and category maps, and figure files.

Figures have no map projection and no coastlines: present-day coastlines would be wrong on an Eocene field. Fields
with 1D coordinates are drawn against them (lon/lat); fields on a curvilinear NEMO grid in index space (``x``,
``y``), with latitude contours for orientation. Figures are :class:`matplotlib.figure.Figure` objects, not
``pyplot`` ones, so plotting needs no display and leaves no global state.
"""

import logging
import os
import tempfile

import numpy as np
import xarray as xr
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.figure import Figure
from scipy.spatial import cKDTree

from .cdo import get_cdo
from .io import atomic_write

logger = logging.getLogger(__name__)

# regular grid that gridpoint GRIB fields are remapped to (nearest neighbour), 1 degree with both poles
REGULAR_GRID = "r360x181"
# resolution of the PNG files
DPI = 150
# latitudes drawn as thin contours on maps in index space, for orientation
LATITUDE_CONTOURS = [-60, -30, 0, 30, 60]
# percentiles of the colour scales of a robust comparison (fields with a few very large values)
ROBUST_PERCENTILES = (2, 98)


def save_figure(fig: Figure, path: str | os.PathLike) -> None:
    """Write ``fig`` to the PNG file ``path`` atomically, creating its directory.

    Parameters
    ----------
    fig : matplotlib.figure.Figure
        The figure.
    path : str or os.PathLike
        PNG file.
    """
    os.makedirs(os.path.dirname(os.fspath(path)) or ".", exist_ok=True)
    with atomic_write(path) as tmp:
        fig.savefig(tmp, dpi=DPI, format="png", bbox_inches="tight")
    logger.debug("Plot saved: %s", path)


def load_grib(path: str, names: list[str] | None = None, grid: str = REGULAR_GRID) -> xr.Dataset:
    """Read a GRIB file on a regular lon/lat grid.

    Gridpoint fields are remapped to ``grid`` with nearest neighbour (so class fields such as vegetation types keep
    their values); spectral fields go to their Gaussian grid with ``sp2gp``. Time steps are not decoded: the steps
    of some EC-Earth GRIB files cannot be, and the plots do not need them.

    Parameters
    ----------
    path : str
        GRIB file (one grid type: all gridpoint or all spectral).
    names : list of str, optional
        Variables to read (CDO names); ``None`` reads all of them.
    grid : str
        CDO target grid of the gridpoint fields.

    Returns
    -------
    xarray.Dataset
        The fields, in memory, without the coordinate bounds.
    """
    selected = f"-selname,{','.join(names)} {path}" if names else path
    cdo = get_cdo()
    spectral = any("spectral" in line for line in cdo.griddes(input=selected))
    with tempfile.TemporaryDirectory() as tmp:
        outfile = os.path.join(tmp, "fields.nc")
        if spectral:
            cdo.sp2gp(input=selected, output=outfile, options="-f nc4")
        else:
            cdo.remapnn(grid, input=selected, output=outfile, options="-f nc4")
        with xr.open_dataset(outfile, decode_times=False) as ds:
            ds = ds.load()
    return ds.drop_vars([name for name in ds.data_vars if name.endswith("_bnds")])


def remap_conservative(source: str, target: str) -> np.ndarray:
    """Remap one field onto another grid with first-order conservative remapping (``cdo remapcon``).

    Parameters
    ----------
    source : str
        NetCDF file with one field on a grid whose cell bounds CDO knows (a regular lon/lat grid, or a grid with
        bounds), or a CDO operator chain ending in such a file.
    target : str
        CDO description of the target grid with cell bounds: a NetCDF file or a grid name.

    Returns
    -------
    numpy.ndarray
        The field on the target grid: the area-weighted mean of the source cells under each target cell, NaN where
        a target cell has no area or no source cell under it.
    """
    with tempfile.TemporaryDirectory() as tmp:
        outfile = os.path.join(tmp, "remapped.nc")
        get_cdo().remapcon(target, input=source, output=outfile, options="-f nc4")
        with xr.open_dataset(outfile, decode_times=False) as ds:
            (name,) = [name for name in ds.data_vars if not name.endswith("_bnds")]
            return ds[name].squeeze(drop=True).values


def _unit_vectors(lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    """Points on the unit sphere (``n x 3``) of the longitudes and latitudes (degrees)."""
    lon, lat = np.deg2rad(np.ravel(lon)), np.deg2rad(np.ravel(lat))
    return np.column_stack([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)])


def sample_nearest(
    src_lon: np.ndarray, src_lat: np.ndarray, values: np.ndarray, lon: np.ndarray, lat: np.ndarray
) -> np.ndarray:
    """Values of a field at the points (``lon``, ``lat``), from its nearest source point on the sphere.

    Works between any two grids (regular, Gaussian, curvilinear): only the point coordinates are used.

    Parameters
    ----------
    src_lon, src_lat : numpy.ndarray
        Coordinates of the source points (degrees), any shape; 1D coordinates of a regular grid must be expanded
        first (``numpy.meshgrid``).
    values : numpy.ndarray
        Source values, the shape of ``src_lon``.
    lon, lat : numpy.ndarray
        Target points (degrees), any shape.

    Returns
    -------
    numpy.ndarray
        The sampled values, the shape of ``lon``.
    """
    _, index = cKDTree(_unit_vectors(src_lon, src_lat)).query(_unit_vectors(lon, lat))
    return np.ravel(values)[index].reshape(np.shape(lon))


def new_figure(panels: int, width: float = 6.5, height: float = 4.5) -> tuple[Figure, list]:
    """A figure with ``panels`` axes side by side.

    Parameters
    ----------
    panels : int
        Number of panels.
    width, height : float
        Size of one panel (inches).

    Returns
    -------
    tuple
        The figure and the list of its axes.
    """
    fig = Figure(figsize=(width * panels, height), layout="constrained")
    return fig, list(fig.subplots(1, panels, squeeze=False)[0])


def _two_d(field: xr.DataArray, label: str) -> xr.DataArray:
    """``field`` without dimensions of size 1; it must be 2D."""
    field = field.squeeze(drop=True)
    if field.ndim != 2:
        raise ValueError(f"'{label}' field has dimensions {field.dims}, expected 2")
    return field


def _draw(ax, field: xr.DataArray, **kwargs):
    """Draw a 2D field: against its coordinates if they are 1D, else in index space (``origin='lower'``)."""
    if all(dim in field.coords for dim in field.dims):
        return field.plot.pcolormesh(ax=ax, add_colorbar=False, add_labels=False, **kwargs)
    mappable = ax.imshow(np.asarray(field), origin="lower", interpolation="nearest", aspect="auto", **kwargs)
    ax.set_xlabel(field.dims[1])
    ax.set_ylabel(field.dims[0])
    return mappable


def _latitudes(ax, lat: np.ndarray | None) -> None:
    """Draw thin latitude contours on a map in index space."""
    if lat is None:
        return
    contours = ax.contour(lat, levels=LATITUDE_CONTOURS, colors="0.5", linewidths=0.4, linestyles="--")
    ax.clabel(contours, fmt="%d°", fontsize=6)


def draw_outline(ax, land: xr.DataArray | None) -> None:
    """Draw the 0.5 contour of a land fraction (the coastline of its grid); nothing if ``land`` is None."""
    if land is None:
        return
    land = land.squeeze(drop=True)
    if all(dim in land.coords for dim in land.dims):
        land.plot.contour(ax=ax, levels=[0.5], colors="k", linewidths=0.5, add_labels=False)
    else:
        ax.contour(np.asarray(land), levels=[0.5], colors="k", linewidths=0.5)


def draw_field(fig: Figure, ax, field: xr.DataArray, title: str = "", lat: np.ndarray | None = None, **kwargs):
    """Draw a 2D field on ``ax`` with a colour bar labelled with its ``units``.

    Parameters
    ----------
    fig : matplotlib.figure.Figure
        The figure of ``ax``.
    ax : matplotlib.axes.Axes
        The panel.
    field : xarray.DataArray
        The field; dimensions of size 1 are dropped.
    title : str
        Panel title.
    lat : numpy.ndarray, optional
        Latitude of the cells of a field in index space: drawn as thin contours for orientation.
    **kwargs
        Passed to the drawing (``cmap``, ``vmin``, ``vmax``).

    Returns
    -------
    The drawn mappable.
    """
    field = _two_d(field, title)
    mappable = _draw(ax, field, **kwargs)
    _latitudes(ax, lat)
    ax.set_title(title)
    fig.colorbar(mappable, ax=ax, shrink=0.8, label=field.attrs.get("units", ""))
    return mappable


def category_colormap(categories: dict[int, tuple[str, str]]) -> tuple[ListedColormap, BoundaryNorm]:
    """Colormap and norm that give each integer value of ``categories`` its colour.

    Parameters
    ----------
    categories : dict
        ``{value: (label, colour)}``, any integer values.

    Returns
    -------
    tuple
        ``(cmap, norm)`` for ``imshow`` or ``pcolormesh``.
    """
    values = sorted(categories)
    cmap = ListedColormap([categories[v][1] for v in values]).with_extremes(bad="none")
    bounds = [values[0] - 0.5] + [(a + b) / 2 for a, b in zip(values[:-1], values[1:])] + [values[-1] + 0.5]
    return cmap, BoundaryNorm(bounds, cmap.N)


def draw_categories(
    fig: Figure,
    ax,
    field: xr.DataArray,
    categories: dict[int, tuple[str, str]],
    title: str = "",
    lat: np.ndarray | None = None,
):
    """Draw an integer class field (mask, vegetation type) on ``ax`` with a labelled colour bar.

    Parameters
    ----------
    fig : matplotlib.figure.Figure
        The figure of ``ax``.
    ax : matplotlib.axes.Axes
        The panel.
    field : xarray.DataArray
        2D class field. Values not in ``categories`` (and NaN) are left blank.
    categories : dict
        ``{value: (label, colour)}``.
    title : str
        Panel title.
    lat : numpy.ndarray, optional
        Latitude of the cells of a field in index space: drawn as thin contours for orientation.

    Returns
    -------
    The drawn mappable.
    """
    field = _two_d(field, title)
    cmap, norm = category_colormap(categories)
    mappable = _draw(ax, field.where(field.isin(list(categories))), cmap=cmap, norm=norm)
    _latitudes(ax, lat)
    ax.set_title(title)
    values = sorted(categories)
    cbar = fig.colorbar(mappable, ax=ax, ticks=values, shrink=0.8)
    cbar.ax.set_yticklabels([categories[v][0] for v in values], fontsize=7)
    return mappable


def symmetric_limit(values: np.ndarray | xr.DataArray, percentile: float = 100) -> float:
    """Largest absolute finite value (or its ``percentile``), for a colour scale centred on 0; 1 if there is none,
    or it is 0."""
    values = np.asarray(values, dtype=float)
    finite = np.abs(values[np.isfinite(values)])
    limit = float(np.percentile(finite, percentile)) if finite.size else 0.0
    return limit or 1.0


def plot_comparison(
    reference: xr.DataArray,
    test: xr.DataArray,
    labels: tuple[str, str] = ("reference", "test"),
    title: str = "",
    same_surface: xr.DataArray | None = None,
    outlines: tuple[xr.DataArray | None, xr.DataArray | None] = (None, None),
    categories: dict[int, tuple[str, str]] | None = None,
    robust: bool = False,
    **kwargs,
) -> Figure:
    """Plot a field of two trees side by side with the same colour scale, and their difference.

    Parameters
    ----------
    reference, test : xarray.DataArray
        The fields, on the same grid. Dimensions of size 1 are dropped; what is left must be 2D.
    labels : tuple of str
        Titles of the reference and test panels.
    title : str
        Figure title.
    same_surface : xarray.DataArray, optional
        True where both trees have the same surface type (land or sea): the difference is shown only there, since
        a value over land and one over sea are not comparable.
    outlines : tuple of xarray.DataArray or None
        Land fraction of each tree, drawn as its 0.5 contour on its panel (the test one also on the difference).
    categories : dict, optional
        ``{value: (label, colour)}`` of a class field (vegetation type): two panels with a labelled colour bar,
        no difference.
    robust : bool
        Colour scales from the 2nd and 98th percentiles (``ROBUST_PERCENTILES``) instead of the extremes, for
        fields with a few very large values (tidal power).
    **kwargs
        Passed to the drawing of the two fields (``cmap``, ``vmin``, ``vmax``). By default ``vmin`` and ``vmax``
        span both fields.

    Returns
    -------
    matplotlib.figure.Figure
        The figure.

    Raises
    ------
    ValueError
        If a field is not 2D after dropping dimensions of size 1.
    """
    reference, test = _two_d(reference, labels[0]), _two_d(test, labels[1])
    if categories is not None:
        present = set(np.unique(reference.values[np.isfinite(reference.values)])) | set(
            np.unique(test.values[np.isfinite(test.values)])
        )
        categories = {value: item for value, item in categories.items() if value in present} or categories
        fig, axes = new_figure(2)
        for ax, field, label, outline in zip(axes, (reference, test), labels, outlines):
            draw_categories(fig, ax, field, categories, label)
            draw_outline(ax, outline)
        fig.suptitle(title)
        return fig

    both = np.concatenate([np.ravel(reference.values), np.ravel(test.values)])
    low, high = ROBUST_PERCENTILES if robust else (0, 100)
    kwargs.setdefault("vmin", float(np.nanpercentile(both, low)))
    kwargs.setdefault("vmax", float(np.nanpercentile(both, high)))
    fig, axes = new_figure(3)
    for ax, field, label, outline in zip(axes, (reference, test), labels, outlines):
        draw_field(fig, ax, field, label, **kwargs)
        draw_outline(ax, outline)
    difference = test - reference
    difference.attrs["units"] = test.attrs.get("units", "")
    if same_surface is not None:
        difference = difference.where(same_surface.squeeze(drop=True))
    limit = symmetric_limit(difference, high if robust else 100)
    suffix = " (same surface type)" if same_surface is not None else ""
    draw_field(fig, axes[2], difference, f"{labels[1]} - {labels[0]}{suffix}", cmap="RdBu_r", vmin=-limit, vmax=limit)
    draw_outline(axes[2], outlines[1])
    fig.suptitle(title)
    return fig


def _with_attrs(field: xr.DataArray, like: xr.DataArray) -> xr.DataArray:
    field.attrs = dict(like.attrs)
    return field


def _time_dim(field: xr.DataArray) -> str | None:
    """The dimension of a monthly field (more than one time step), or None."""
    return next((dim for dim in field.dims if "time" in dim and field.sizes[dim] > 1), None)


def _layer_dims(field: xr.DataArray) -> list[str]:
    """Dimensions other than time and the two horizontal ones (the last two) with more than one value."""
    time = _time_dim(field)
    return [dim for dim in field.dims[:-2] if dim != time and field.sizes[dim] > 1]


def _maps(field: xr.DataArray) -> dict[str, xr.DataArray]:
    """The 2D maps of a field: itself, or the annual mean and seasonal range of a monthly field. A field with
    layers (e.g. the snow layers of ``sd``) is drawn at its first layer."""
    time = _time_dim(field)
    field = _with_attrs(field.isel({dim: 0 for dim in _layer_dims(field)}), field)
    if time is None:
        return {"": field}
    return {
        "mean": _with_attrs(field.mean(time), field),
        "range": _with_attrs(field.max(time) - field.min(time), field),
    }


def _map_title(name: str, field: xr.DataArray, file: str, panel: str) -> str:
    long_name = field.attrs.get("long_name", "")
    what = {"mean": ", annual mean", "range": ", seasonal range (largest - smallest month)"}.get(panel, "")
    layers = _layer_dims(field)
    first = f", first {layers[0]} layer" if layers else ""
    return f"{name}{f' ({long_name})' if long_name else ''}{what}{first}: {file}"


def compare_datasets(
    reference: xr.Dataset,
    test: xr.Dataset,
    name: str,
    out_dir: str,
    labels: tuple[str, str],
    same_surface: xr.DataArray | None = None,
    outlines: tuple[xr.DataArray | None, xr.DataArray | None] = (None, None),
    categories: dict[str, dict[int, tuple[str, str]]] | None = None,
    robust: bool = False,
) -> dict:
    """Draw every variable of a file that differs between two trees (:func:`plot_comparison`).

    Monthly fields (more than one time step) get two figures, the annual mean and the seasonal range (largest minus
    smallest month); fields with layers are drawn at their first layer. Variables that do not differ are only
    listed in the summary.

    Parameters
    ----------
    reference, test : xarray.Dataset
        The file in the two trees, read on the same grid.
    name : str
        Name of the file: the figures go to ``<out_dir>/<name>/<variable>[_mean|_range].png``.
    out_dir : str
        Folder of the figures.
    labels : tuple of str
        Names of the reference and test trees.
    same_surface : xarray.DataArray, optional
        Where both trees have the same surface type: the difference is shown only there, for the fields on its
        grid that are not classes.
    outlines : tuple of xarray.DataArray or None
        Land fraction of each tree, drawn as coastlines.
    categories : dict, optional
        ``{variable: {value: (label, colour)}}`` of the class fields.
    robust : bool
        Colour scales from percentiles (see :func:`plot_comparison`).

    Returns
    -------
    dict
        For ``summary.yml``: ``changed`` (variable: largest absolute difference), ``unchanged``, and the variables
        found in one tree only (``only_in_reference``, ``only_in_test``).
    """
    categories = categories or {}
    summary: dict = {
        "changed": {},
        "unchanged": [],
        "only_in_reference": sorted(set(reference.data_vars) - set(test.data_vars)),
        "only_in_test": sorted(set(test.data_vars) - set(reference.data_vars)),
    }
    for variable in [v for v in test.data_vars if v in reference.data_vars]:
        before, after = reference[variable], test[variable]
        if before.shape != after.shape:
            logger.warning("Plots: %s of %s has different shapes in the two trees, not drawn", variable, name)
            continue
        if np.allclose(before.values, after.values, equal_nan=True):
            summary["unchanged"].append(variable)
            continue
        summary["changed"][variable] = round(float(np.nanmax(np.abs(after.values - before.values))), 6)
        before_maps, after_maps = _maps(before), _maps(after)
        for panel, ref_map in before_maps.items():
            if ref_map.squeeze(drop=True).ndim != 2:
                logger.warning("Plots: %s of %s is not a 2D field (%s), not drawn", variable, name, ref_map.dims)
                break
            on_grid = same_surface is not None and ref_map.squeeze(drop=True).shape == same_surface.shape
            fig = plot_comparison(
                ref_map,
                after_maps[panel],
                labels,
                _map_title(variable, after, name, panel),
                same_surface=same_surface if on_grid and variable not in categories else None,
                outlines=outlines,
                categories=categories.get(variable),
                robust=robust,
            )
            save_figure(fig, os.path.join(out_dir, name, f"{variable}{f'_{panel}' if panel else ''}.png"))
    logger.info("Plots: %s, %d variables differ, %d do not", name, len(summary["changed"]), len(summary["unchanged"]))
    return summary
