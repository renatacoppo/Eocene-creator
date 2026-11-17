"""Checks and maps of a NEMO domain, for ``ecefast <period> plot``.

- **Ocean basins**: the connected ocean regions of a domain. Cells are connected through their faces (where NEMO
  has a velocity point), across the east-west period and across the north fold. Basins other than the largest are
  closed seas or lakes: wanted for some (Caspian Sea), a sign of a closed strait for others.
- **Minimum depth**: the smallest ocean depth of a domain and the cells that have it, the shallowest columns.
- **Inlets**: dead-end channels one cell wide, where water enters from one side only and nothing flows through
  (:func:`ocean_inlets`).
- **One-cell passages**: ocean cells with land on both sides along ``x`` or along ``y``, where a strait or a
  channel is one cell wide.
- **Land-sea mask comparisons** of a domain with another domain on the same grid (cells that change, depth
  differences), or with a mask on another grid (another NEMO domain, the source of a bathymetry, the OIFS
  land-sea mask), remapped conservatively onto the domain's T cells (:func:`write_cell_bounds`, :func:`ocean_on`).
- **Forcing files** (``FORCING_FILES``): the geothermal heat flux and the tidal mixing forcing of two trees,
  every variable that differs.

Maps are in index space (``x``, ``y``), so a cell can be found in the domain, with latitude contours for
orientation.
"""

import argparse
import os
from dataclasses import dataclass

import numpy as np
import xarray as xr
from matplotlib.figure import Figure
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

from ecefast.core.io import atomic_write
from ecefast.core.plotting import (
    compare_datasets,
    draw_categories,
    draw_field,
    new_figure,
    remap_conservative,
    sample_nearest,
    symmetric_limit,
)
from ecefast.core.steps import PipelineError

from .bathymetry.base import BathymetryProcessor
from .orca_bounds import OrcaMesh

# names of the depth (m) in NEMO domain and bathymetry files, in order of preference: domain_cfg.nc, bathy_meter.nc
BATHYMETRY_NAMES = ("bathy_metry", "Bathymetry", "bathymetry", "bathy_meter")
# names of the T-point longitude and latitude, in order of preference: domain_cfg.nc, bathymetry files
COORDINATE_NAMES = (("glamt", "gphit"), ("nav_lon", "nav_lat"))
# NEMO forcing files compared by the plots, relative to a tree: the geothermal heat flux at the sea floor and the
# forcing of the internal-wave-driven (tidal) mixing, zdfiwm
FORCING_FILES = ("nemo/initial/Goutorbe_ghflux.nc", "nemo/initial/zdfiwm_forcing_r720x360.nc")

# Sign of an ocean value of each MASK_PRESETS convention (bathymetry/base.py): depth > 0, elevation < 0
OCEAN_SIGN = {"positive_depth": 1, "negative_elevation": -1}

# name of the ocean mask (1 ocean, 0 land) in the files written for conservative remapping
OCEAN_FIELD = "ocean"
# share of a cell that the ocean of another grid must cover for the cell to be ocean in a comparison: at least
# half, the rule that makes the land-sea mask of a bathymetry (remapcon fraction against 0.5, bathymetry/base.py)
OCEAN_COVER_THRESHOLD = 0.5

# classes of the domain map
LAND, OCEAN, PASSAGE, ISOLATED, INLET = 0, 1, 2, 3, 4
DOMAIN_CATEGORIES = {
    LAND: ("land", "#d9d9d9"),
    OCEAN: ("ocean, main basin", "#c6dbef"),
    PASSAGE: ("one-cell passage", "#e66101"),
    ISOLATED: ("other basin", "#5e3c99"),
    INLET: ("inlet (dead end, one cell wide)", "#d01c8b"),
}
# number of inlets, the longest ones, that the summary describes with their length and a cell
LONGEST_INLETS = 10
# classes of the map of the cells at the minimum depth; their colour differs from every class of the domain map
SHALLOWEST = 2
MINIMUM_DEPTH_CATEGORIES = {
    LAND: ("land", "#d9d9d9"),
    OCEAN: ("ocean, deeper", "#c6dbef"),
    SHALLOWEST: ("ocean, at the minimum depth", "#018571"),
}
# m; cells within this of the smallest depth of a domain are at its minimum depth (rounding of the depths)
MINIMUM_DEPTH_ATOL = 1e-3
# classes of a land-sea mask comparison
BOTH_LAND, BOTH_OCEAN, ONLY_TEST, ONLY_OTHER = 0, 1, 2, 3
AGREEMENT_KEYS = {
    BOTH_LAND: "land_in_both",
    BOTH_OCEAN: "ocean_in_both",
    ONLY_TEST: "ocean_only_in_test",
    ONLY_OTHER: "ocean_only_in_other",
}


@dataclass
class Domain:
    """What the plots use of a NEMO ``domain_cfg.nc``.

    Attributes
    ----------
    label : str
        Name in titles and in the summary.
    path : str
        The file.
    lon, lat : numpy.ndarray
        T-point coordinates (``glamt``, ``gphit``), ``(y, x)``.
    ocean : numpy.ndarray
        True on ocean columns (``bottom_level > 0``).
    depth : xarray.DataArray
        ``bathy_metry`` (m), NaN on land.
    """

    label: str
    path: str
    lon: np.ndarray
    lat: np.ndarray
    ocean: np.ndarray
    depth: xr.DataArray


def _first(ds: xr.Dataset, names: tuple[str, ...], path: str, what: str) -> str:
    """The first of ``names`` that ``ds`` holds."""
    found = next((name for name in names if name in ds), None)
    if found is None:
        raise PipelineError(f"{path}: no {what} variable (looked for {', '.join(names)})")
    return found


def read_domain(path: str, label: str) -> Domain:
    """Read the T-point coordinates, ocean mask and depth of a NEMO domain file.

    The depth is the first of ``BATHYMETRY_NAMES`` in the file, the coordinates the first pair of
    ``COORDINATE_NAMES``. Ocean columns are those with ``bottom_level > 0``, or with a depth above 0 in a file
    without ``bottom_level`` (a bathymetry file).

    Parameters
    ----------
    path : str
        The ``domain_cfg.nc`` (or a bathymetry file on the domain's grid).
    label : str
        Name of the domain in titles and in the summary.

    Returns
    -------
    Domain
        The domain.

    Raises
    ------
    PipelineError
        If the file has no depth or coordinate variable of a known name.
    """
    with xr.open_dataset(path) as ds:
        depth_name = _first(ds, BATHYMETRY_NAMES, path, "bathymetry")
        lon_name = _first(ds, tuple(lon for lon, _ in COORDINATE_NAMES), path, "longitude")
        lat_name = dict(COORDINATE_NAMES)[lon_name]
        names = [lon_name, lat_name, depth_name] + (["bottom_level"] if "bottom_level" in ds else [])
        ds = ds[names].squeeze(drop=True).load()
    depth = ds[depth_name].fillna(0.0)
    ocean = ds.bottom_level.values > 0 if "bottom_level" in ds else depth.values > 0
    depth = depth.where(ocean).rename("bathy_metry")
    depth.attrs = {"units": "m"}
    return Domain(label, path, ds[lon_name].values, ds[lat_name].values, ocean, depth)


def write_cell_bounds(domain_file: str, outfile: str, ocean: np.ndarray | None = None) -> None:
    """Write the T cells of a NEMO domain with their corners, as a grid CDO can remap conservatively from and onto.

    The corners are the F points around each T point (:class:`ecefast.components.nemo.orca_bounds.OrcaMesh`, the
    tool the domain pipeline uses for its own bounds). Cells of the north-fold row get corners beyond the fold and
    have no area; they duplicate cells across the fold.

    Parameters
    ----------
    domain_file : str
        The ``domain_cfg.nc`` (``glam*``, ``gphi*``, ``e1t``, ``e2t``).
    outfile : str
        NetCDF file to write: ``lat``, ``lon`` and their bounds, on the dimensions of the domain.
    ocean : numpy.ndarray, optional
        Ocean mask of the domain, written as the field ``ocean`` (1 ocean, 0 land) so the file can be remapped.
    """
    mesh = OrcaMesh(argparse.Namespace(meshmask=domain_file, stagg="T", level=False, zname="level"))
    cells = mesh.reorder_vars(mesh.get_ds_cf())
    if ocean is not None:
        # the mask becomes the one field of the file, in place of the cell area
        cells = cells.drop_vars("cell_area").assign({OCEAN_FIELD: (cells["lat"].dims, ocean.astype("f4"))})
    with atomic_write(outfile) as tmp:
        cells.to_netcdf(tmp)


def write_source_ocean(processor: type[BathymetryProcessor], path: str, outfile: str) -> None:
    """Write the ocean mask of the source dataset of a bathymetry, on its own grid, as a file CDO can remap.

    Ocean follows the processor's ``mask_type`` (``MASK_PRESETS``): depth > 0 or elevation < 0. A source on a NEMO
    domain is written with its cell corners (:func:`write_cell_bounds`); of a regular grid CDO finds the bounds
    itself.

    Parameters
    ----------
    processor : type of BathymetryProcessor
        The bathymetry (its ``variable`` and ``mask_type``).
    path : str
        The source file (the processor's ``source_file``, expanded).
    outfile : str
        NetCDF file to write, with the field ``ocean`` (1 ocean, 0 land).
    """
    with xr.open_dataset(path) as ds:
        values = ds[processor.variable].squeeze(drop=True).load()
        curvilinear = "glamt" in ds  # a NEMO domain
    ocean = OCEAN_SIGN[processor.mask_type] * np.nan_to_num(values.values) > 0
    if curvilinear:
        write_cell_bounds(path, outfile, ocean)
        return
    lat, lon = values.dims
    coords = {
        lat: (lat, values[lat].values, {"standard_name": "latitude", "units": "degrees_north"}),
        lon: (lon, values[lon].values, {"standard_name": "longitude", "units": "degrees_east"}),
    }
    with atomic_write(outfile) as tmp:
        xr.Dataset({OCEAN_FIELD: ((lat, lon), ocean.astype("f4"))}, coords=coords).to_netcdf(tmp)


def ocean_basins(ocean: np.ndarray, lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    """Number the connected ocean basins of a domain.

    Ocean cells are connected through their east, west, north and south faces, across the east-west period (the
    first and last columns are neighbours) and where two cells have the same coordinates (the duplicated rows of a
    T-point north fold). The connections across an F-point fold, whose cells are not duplicated, are not added.

    Parameters
    ----------
    ocean : numpy.ndarray
        Ocean mask ``(y, x)``.
    lon, lat : numpy.ndarray
        T-point coordinates ``(y, x)``, degrees.

    Returns
    -------
    numpy.ndarray
        Basin number of every cell: 0 the largest basin, 1 the next largest and so on; -1 on land.
    """
    ny, nx = ocean.shape
    a, b = (np.concatenate(pair) for pair in zip(_face_pairs(ocean), _same_cell_pairs(ocean, lon, lat)))
    graph = coo_matrix((np.ones(a.size), (a, b)), shape=(ny * nx, ny * nx))
    count, labels = connected_components(graph, directed=False)
    labels = labels.reshape(ny, nx)
    return _rank_by_size(ocean, labels, count)


def _face_pairs(ocean: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Flat indices of the pairs of ocean cells that share an east or a north face (east-west periodic)."""
    index = np.arange(ocean.size).reshape(ocean.shape)
    east = ocean & np.roll(ocean, -1, axis=1)
    north = ocean[:-1] & ocean[1:]
    first = np.concatenate([index[east], index[:-1][north]])
    second = np.concatenate([np.roll(index, -1, axis=1)[east], index[1:][north]])
    return first, second


def _same_cell_pairs(ocean: np.ndarray, lon: np.ndarray, lat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Flat indices of the pairs of ocean cells with the same coordinates: the same cell twice (north fold)."""
    key = np.round(np.mod(lon, 360.0), 4).ravel() * 1e4 + np.round(lat, 4).ravel()
    order = np.argsort(key, kind="stable")
    same = key[order][1:] == key[order][:-1]
    first, second = order[:-1][same], order[1:][same]
    both = ocean.ravel()[first] & ocean.ravel()[second]
    return first[both], second[both]


def _rank_by_size(cells: np.ndarray, labels: np.ndarray, count: int) -> np.ndarray:
    """Number the groups of ``labels`` on ``cells`` by size, 0 the largest; -1 outside ``cells``."""
    ids, sizes = np.unique(labels[cells], return_counts=True)
    rank = np.full(count, -1)
    rank[ids[np.argsort(-sizes, kind="stable")]] = np.arange(ids.size)
    return np.where(cells, rank[labels], -1)


def ocean_inlets(ocean: np.ndarray, lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    """Number the inlets of a domain: the dead-end channels one cell wide.

    A cell with ocean through one face only is the tip of an inlet: water enters it from one side, so nothing
    flows through. Removing the tips and repeating follows each inlet to its mouth, the first cell that opens on
    wider ocean (which is not part of it). The connections are those of :func:`ocean_basins`; cells with the same
    coordinates count as one cell. A notch of one cell in a coast is an inlet of length 1. Dead ends two or more
    cells wide are not found.

    Parameters
    ----------
    ocean : numpy.ndarray
        Ocean mask ``(y, x)``.
    lon, lat : numpy.ndarray
        T-point coordinates ``(y, x)``, degrees.

    Returns
    -------
    numpy.ndarray
        Inlet number of every cell: 0 the longest inlet, 1 the next longest and so on; -1 elsewhere.
    """
    size = ocean.size
    # one node for the cells with the same coordinates
    first, second = _same_cell_pairs(ocean, lon, lat)
    same = coo_matrix((np.ones(first.size), (first, second)), shape=(size, size))
    _, node = connected_components(same, directed=False)
    a, b = _face_pairs(ocean)
    a, b = node[a], node[b]
    faces = coo_matrix((np.ones(a.size), (a, b)), shape=(size, size)).tocsr()
    neighbours = ((faces + faces.T) > 0).astype(np.int32)
    neighbours.setdiag(0)
    alive = np.zeros(size, dtype=bool)
    alive[node[ocean.ravel()]] = True
    inlet = np.zeros(size, dtype=bool)
    while True:
        tips = alive & (neighbours @ alive.astype(np.int32) == 1)
        if not tips.any():
            break
        inlet |= tips
        alive &= ~tips
    # the inlet cells that touch are one inlet
    nodes = np.flatnonzero(inlet)
    count, numbers = connected_components(neighbours[nodes][:, nodes], directed=False)
    labels = np.full(size, -1)
    labels[nodes] = numbers
    cells = ocean & inlet[node].reshape(ocean.shape)
    return _rank_by_size(cells, labels[node].reshape(ocean.shape), max(count, 1))


def one_cell_passages(ocean: np.ndarray) -> np.ndarray:
    """Ocean cells with land on both sides along ``x`` (east-west periodic) or along ``y``.

    Parameters
    ----------
    ocean : numpy.ndarray
        Ocean mask ``(y, x)``.

    Returns
    -------
    numpy.ndarray
        True on the one-cell passages.
    """
    west, east = np.roll(ocean, 1, axis=1), np.roll(ocean, -1, axis=1)
    south, north = np.zeros_like(ocean), np.zeros_like(ocean)
    south[1:], north[:-1] = ocean[:-1], ocean[1:]
    return ocean & ((~west & ~east) | (~south & ~north))


def domain_classes(domain: Domain) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Classes of the domain map (``DOMAIN_CATEGORIES``), the basin numbers (:func:`ocean_basins`) and the inlet
    numbers (:func:`ocean_inlets`).

    A cell of an inlet is drawn as an inlet, not as a one-cell passage: the passages left are those with ocean at
    both ends. A cell of a basin other than the largest is drawn as that.
    """
    basins = ocean_basins(domain.ocean, domain.lon, domain.lat)
    inlets = ocean_inlets(domain.ocean, domain.lon, domain.lat)
    classes = np.full(domain.ocean.shape, LAND)
    classes[domain.ocean] = OCEAN
    classes[one_cell_passages(domain.ocean)] = PASSAGE
    classes[inlets >= 0] = INLET
    classes[basins > 0] = ISOLATED
    return classes, basins, inlets


def _groups(domain: Domain, numbers: np.ndarray, limit: int | None = None) -> list[dict]:
    """Size and one cell (indices and position) of each numbered group of cells, for ``summary.yml``."""
    groups = []
    for number in range(numbers.max() + 1 if limit is None else min(limit, numbers.max() + 1)):
        j, i = np.argwhere(numbers == number)[0]
        groups.append(
            {
                "cells": int((numbers == number).sum()),
                "j": int(j),
                "i": int(i),
                "lon": round(float(domain.lon[j, i]), 2),
                "lat": round(float(domain.lat[j, i]), 2),
            }
        )
    return groups


def domain_summary(domain: Domain, basins: np.ndarray, inlets: np.ndarray, classes: np.ndarray) -> dict:
    """Numbers of a domain for ``summary.yml``: ocean cells, the minimum depth (m) and the cells that have it, basins
    (each with a cell and its position), one-cell passages that are not inlets, and inlets (their number, their
    cells in the main basin, and the ``LONGEST_INLETS`` longest with their length and a cell)."""
    main = np.where(basins == 0, inlets, -1)
    minimum, shallowest = minimum_depth_cells(domain)
    return {
        "domain": domain.path,
        "ocean_cells": int(domain.ocean.sum()),
        "minimum_depth": round(minimum, 2),
        "minimum_depth_cells": int(shallowest.sum()),
        "basins": int(basins.max() + 1),
        "other_basins": _groups(domain, basins)[1:],
        "one_cell_passages": int((classes == PASSAGE).sum()),
        "inlets": int(np.unique(main[main >= 0]).size),
        "inlet_cells": int((classes == INLET).sum()),
        "longest_inlets": _groups(domain, _renumber(main), LONGEST_INLETS),
    }


def _renumber(numbers: np.ndarray) -> np.ndarray:
    """The same groups numbered 0, 1, ... without gaps, in the same order; -1 stays -1."""
    present = np.unique(numbers[numbers >= 0])
    lookup = np.full(max(int(numbers.max()), 0) + 2, -1)
    lookup[present] = np.arange(present.size)
    return lookup[numbers]


def _field(values: np.ndarray, units: str = "") -> xr.DataArray:
    """A field in index space (``y``, ``x``)."""
    return xr.DataArray(values, dims=("y", "x"), attrs={"units": units})


def minimum_depth_cells(domain: Domain) -> tuple[float, np.ndarray]:
    """The smallest ocean depth of a domain and the cells that have it.

    They are the cells that the minimum depth of the domain build raised (``<period>.nemo.minimum_depth``, on the
    vertical grid of the domain), the shallowest columns of the model.

    Parameters
    ----------
    domain : Domain
        The domain.

    Returns
    -------
    tuple
        The minimum depth (m; NaN for a domain without ocean) and the mask of the cells within
        ``MINIMUM_DEPTH_ATOL`` of it.
    """
    depth = domain.depth.values
    if not domain.ocean.any():
        return float("nan"), np.zeros(depth.shape, dtype=bool)
    minimum = float(np.nanmin(depth))
    return minimum, np.nan_to_num(depth, nan=np.inf) <= minimum + MINIMUM_DEPTH_ATOL


def plot_domain(domain: Domain, classes: np.ndarray) -> Figure:
    """Map of the depth, of the basins, one-cell passages and inlets (:func:`domain_classes`) and of the cells at the
    minimum depth (:func:`minimum_depth_cells`) of a domain."""
    fig, axes = new_figure(3, width=7.5)
    draw_field(fig, axes[0], domain.depth, f"{domain.label}: depth", domain.lat, cmap="viridis_r")
    draw_categories(fig, axes[1], _field(classes), DOMAIN_CATEGORIES, f"{domain.label}: basins", domain.lat)
    minimum, shallowest = minimum_depth_cells(domain)
    shallow = np.where(shallowest, SHALLOWEST, np.where(domain.ocean, OCEAN, LAND))
    title = f"{domain.label}: {int(shallowest.sum())} cells at the minimum depth ({minimum:.1f} m)"
    draw_categories(fig, axes[2], _field(shallow), MINIMUM_DEPTH_CATEGORIES, title, domain.lat)
    return fig


def mask_agreement(test: np.ndarray, other: np.ndarray) -> np.ndarray:
    """Compare two ocean masks on the same cells.

    Parameters
    ----------
    test, other : numpy.ndarray
        Ocean masks of the same shape.

    Returns
    -------
    numpy.ndarray
        ``BOTH_LAND``, ``BOTH_OCEAN``, ``ONLY_TEST`` (ocean only in ``test``) or ``ONLY_OTHER`` for every cell.
    """
    agreement = np.full(test.shape, BOTH_LAND)
    agreement[test & other] = BOTH_OCEAN
    agreement[test & ~other] = ONLY_TEST
    agreement[~test & other] = ONLY_OTHER
    return agreement


def agreement_counts(agreement: np.ndarray) -> dict[str, int]:
    """Number of cells of each class of :func:`mask_agreement`, for ``summary.yml``."""
    return {key: int((agreement == value).sum()) for value, key in AGREEMENT_KEYS.items()}


def agreement_categories(test_label: str, other_label: str) -> dict[int, tuple[str, str]]:
    """Labels and colours of the classes of :func:`mask_agreement`."""
    return {
        BOTH_LAND: ("land in both", "#d9d9d9"),
        BOTH_OCEAN: ("ocean in both", "#c6dbef"),
        ONLY_TEST: (f"ocean only in {test_label}", "#e66101"),
        ONLY_OTHER: (f"ocean only in {other_label}", "#5e3c99"),
    }


def fill_empty_cells(domain: Domain, values: np.ndarray) -> np.ndarray:
    """Give the cells of ``domain`` that a conservative remapping left empty (NaN) the value of the nearest cell.

    Empty cells are those of the north-fold row, which have no area in :func:`write_cell_bounds` and take the value
    of their twin across the fold, and cells that the other grid does not cover (south of a domain that stops at
    the Antarctic coast).

    Parameters
    ----------
    domain : Domain
        The domain.
    values : numpy.ndarray
        A field on its cells, NaN where empty.

    Returns
    -------
    numpy.ndarray
        The field without NaN.
    """
    empty = np.isnan(values)
    if not empty.any():
        return values
    full = ~empty
    filled = values.copy()
    filled[empty] = sample_nearest(
        domain.lon[full], domain.lat[full], values[full], domain.lon[empty], domain.lat[empty]
    )
    return filled


def ocean_on(domain: Domain, source: str, cells: str) -> np.ndarray:
    """An ocean mask on another grid, remapped conservatively onto the cells of ``domain``.

    A cell is ocean when the ocean of the other grid covers at least ``OCEAN_COVER_THRESHOLD`` of it.

    Parameters
    ----------
    domain : Domain
        The domain whose cells receive the mask.
    source : str
        File with the field ``ocean`` (1 ocean, 0 land) on the other grid (:func:`write_cell_bounds`,
        :func:`write_source_ocean`).
    cells : str
        The cells of ``domain`` with their corners (:func:`write_cell_bounds`).

    Returns
    -------
    numpy.ndarray
        The ocean mask on the cells of ``domain``.
    """
    return fill_empty_cells(domain, remap_conservative(source, cells)) >= OCEAN_COVER_THRESHOLD


def plot_agreement(domain: Domain, other: np.ndarray, other_label: str, title: str) -> tuple[Figure, dict[str, int]]:
    """Map of where the ocean mask of ``domain`` and another mask on its cells agree.

    Parameters
    ----------
    domain : Domain
        The domain.
    other : numpy.ndarray
        The other ocean mask on the cells of ``domain`` (see :func:`ocean_on`).
    other_label : str
        Name of the other mask.
    title : str
        Figure title.

    Returns
    -------
    tuple
        The figure, and the number of cells of each class (:func:`agreement_counts`).
    """
    agreement = mask_agreement(domain.ocean, other)
    fig, axes = new_figure(1, width=8)
    categories = agreement_categories(domain.label, other_label)
    draw_categories(fig, axes[0], _field(agreement), categories, title, domain.lat)
    return fig, agreement_counts(agreement)


def plot_same_grid(domain: Domain, other: Domain) -> tuple[Figure, dict[str, int | float]]:
    """Compare two domains on the same grid: the cells that change between land and ocean, and the depth difference
    where both are ocean.

    Parameters
    ----------
    domain, other : Domain
        The domains, on the same grid.

    Returns
    -------
    tuple
        The figure, and the number of cells of each class (:func:`agreement_counts`) with the largest absolute
        depth difference (m).

    Raises
    ------
    ValueError
        If the domains are not on grids of the same shape.
    """
    if domain.ocean.shape != other.ocean.shape:
        raise ValueError(f"{domain.path} and {other.path} are on different grids")
    agreement = mask_agreement(domain.ocean, other.ocean)
    difference = _field(domain.depth.values - other.depth.values, "m")
    limit = symmetric_limit(difference)
    fig, axes = new_figure(2, width=7.5)
    categories = agreement_categories(domain.label, other.label)
    draw_categories(fig, axes[0], _field(agreement), categories, "land-sea mask", domain.lat)
    draw_field(
        fig, axes[1], difference, "depth difference (ocean in both)", domain.lat, cmap="RdBu_r", vmin=-limit, vmax=limit
    )
    fig.suptitle(f"{domain.label} vs {other.label}")
    finite = difference.values[np.isfinite(difference.values)]
    largest = float(np.abs(finite).max()) if finite.size else 0.0
    return fig, agreement_counts(agreement) | {"largest_depth_difference": round(largest, 2)}


def forcing_files(tree: str) -> dict[str, str]:
    """The NEMO forcing files of a tree that the plots compare, ``{name: path}`` (name: file name without ``.nc``)."""
    return {os.path.splitext(os.path.basename(f))[0]: os.path.join(tree, f) for f in FORCING_FILES}


def compare_forcing(
    reference_files: dict[str, str], test_files: dict[str, str], out_dir: str, labels: tuple[str, str]
) -> dict:
    """Draw every variable of the NEMO forcing files that differs between two trees.

    The colour scales come from percentiles: the tidal mixing power has a few very large values.

    Parameters
    ----------
    reference_files, test_files : dict
        The files of the two trees (:func:`forcing_files`).
    out_dir : str
        Folder of the figures: ``<out_dir>/<name>/<variable>.png``.
    labels : tuple of str
        Names of the reference and test trees.

    Returns
    -------
    dict
        ``{name: summary}`` (:func:`ecefast.core.plotting.compare_datasets`).
    """
    summary = {}
    for name, test_path in test_files.items():
        with (
            xr.open_dataset(reference_files[name], decode_times=False) as reference,
            xr.open_dataset(test_path, decode_times=False) as test,
        ):
            summary[name] = compare_datasets(reference.load(), test.load(), name, out_dir, labels, robust=True)
    return summary
