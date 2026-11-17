"""Checks and maps of a NEMO domain, for ``ecefast <period> plot``.

- **Ocean basins**: the connected ocean regions of a domain. Cells are connected through their faces (where NEMO
  has a velocity point), across the east-west period and across the north fold. Basins other than the largest are
  closed seas or lakes: wanted for some (Caspian Sea), a sign of a closed strait for others.
- **One-cell passages**: ocean cells with land on both sides along ``x`` or along ``y``, where a strait or a
  channel is one cell wide.
- **Land-sea mask comparisons** of a domain with another domain on the same grid (cells that change, depth
  differences), or with any field on another grid (another NEMO domain, the source of a bathymetry, the OIFS
  land-sea mask), sampled at the domain's T points from the nearest point.

Maps are in index space (``x``, ``y``), so a cell can be found in the domain, with latitude contours for
orientation.
"""

from dataclasses import dataclass

import numpy as np
import xarray as xr
from matplotlib.figure import Figure
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

from ecefast.core.plotting import draw_categories, draw_field, new_figure, sample_nearest, symmetric_limit

from .bathymetry.base import BathymetryProcessor

# Sign of an ocean value of each MASK_PRESETS convention (bathymetry/base.py): depth > 0, elevation < 0
OCEAN_SIGN = {"positive_depth": 1, "negative_elevation": -1}

# classes of the domain map
LAND, OCEAN, PASSAGE, ISOLATED = 0, 1, 2, 3
DOMAIN_CATEGORIES = {
    LAND: ("land", "#d9d9d9"),
    OCEAN: ("ocean, main basin", "#c6dbef"),
    PASSAGE: ("one-cell passage", "#e66101"),
    ISOLATED: ("other basin", "#5e3c99"),
}
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


def read_domain(path: str, label: str) -> Domain:
    """Read the T-point coordinates, ocean mask and depth of a NEMO ``domain_cfg.nc``.

    Parameters
    ----------
    path : str
        The ``domain_cfg.nc``.
    label : str
        Name of the domain in titles and in the summary.

    Returns
    -------
    Domain
        The domain.
    """
    with xr.open_dataset(path) as ds:
        ds = ds[["glamt", "gphit", "bottom_level", "bathy_metry"]].squeeze(drop=True).load()
    ocean = ds.bottom_level.values > 0
    depth = ds.bathy_metry.where(ocean)
    depth.attrs["units"] = "m"
    return Domain(label, path, ds.glamt.values, ds.gphit.values, ocean, depth)


def source_ocean(processor: type[BathymetryProcessor], path: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Ocean mask of the source dataset of a bathymetry, on its own grid.

    Ocean follows the processor's ``mask_type`` (``MASK_PRESETS``): depth > 0 or elevation < 0.

    Parameters
    ----------
    processor : type of BathymetryProcessor
        The bathymetry (its ``variable`` and ``mask_type``).
    path : str
        The source file (the processor's ``source_file``, expanded).

    Returns
    -------
    tuple of numpy.ndarray
        Longitude, latitude and ocean mask of the source points, all of the same 2D shape.
    """
    with xr.open_dataset(path) as ds:
        values = ds[processor.variable].squeeze(drop=True).load()
        if "glamt" in ds:  # a NEMO domain: curvilinear T points
            lon, lat = ds.glamt.squeeze(drop=True).values, ds.gphit.squeeze(drop=True).values
        else:
            lon, lat = np.meshgrid(values[values.dims[1]].values, values[values.dims[0]].values)
    ocean = OCEAN_SIGN[processor.mask_type] * np.nan_to_num(values.values) > 0
    return lon, lat, ocean


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
    index = np.arange(ny * nx).reshape(ny, nx)
    east = ocean & np.roll(ocean, -1, axis=1)
    north = ocean[:-1] & ocean[1:]
    pairs = [(index[east], np.roll(index, -1, axis=1)[east]), (index[:-1][north], index[1:][north])]
    # cells with the same coordinates are the same cell (north fold)
    key = np.round(np.mod(lon, 360.0), 4).ravel() * 1e4 + np.round(lat, 4).ravel()
    order = np.argsort(key, kind="stable")
    same = key[order][1:] == key[order][:-1]
    first, second = order[:-1][same], order[1:][same]
    both = ocean.ravel()[first] & ocean.ravel()[second]
    pairs.append((first[both], second[both]))
    a = np.concatenate([p[0] for p in pairs])
    b = np.concatenate([p[1] for p in pairs])
    graph = coo_matrix((np.ones(a.size), (a, b)), shape=(ny * nx, ny * nx))
    count, labels = connected_components(graph, directed=False)
    labels = labels.reshape(ny, nx)
    ids, cells = np.unique(labels[ocean], return_counts=True)
    rank = np.full(count, -1)
    rank[ids[np.argsort(-cells, kind="stable")]] = np.arange(ids.size)
    return np.where(ocean, rank[labels], -1)


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


def domain_classes(domain: Domain) -> tuple[np.ndarray, np.ndarray]:
    """Classes of the domain map (``DOMAIN_CATEGORIES``) and the basin numbers (:func:`ocean_basins`)."""
    basins = ocean_basins(domain.ocean, domain.lon, domain.lat)
    classes = np.full(domain.ocean.shape, LAND)
    classes[domain.ocean] = OCEAN
    classes[one_cell_passages(domain.ocean)] = PASSAGE
    classes[basins > 0] = ISOLATED
    return classes, basins


def domain_summary(domain: Domain, basins: np.ndarray, classes: np.ndarray) -> dict:
    """Numbers of a domain for ``summary.yml``: ocean cells, basins (each with a cell and its position) and
    one-cell passages."""
    other = []
    for number in range(1, basins.max() + 1):
        j, i = np.argwhere(basins == number)[0]
        other.append(
            {
                "cells": int((basins == number).sum()),
                "j": int(j),
                "i": int(i),
                "lon": round(float(domain.lon[j, i]), 2),
                "lat": round(float(domain.lat[j, i]), 2),
            }
        )
    return {
        "domain": domain.path,
        "ocean_cells": int(domain.ocean.sum()),
        "basins": int(basins.max() + 1),
        "other_basins": other,
        "one_cell_passages": int((classes == PASSAGE).sum()),
    }


def _field(values: np.ndarray, units: str = "") -> xr.DataArray:
    """A field in index space (``y``, ``x``)."""
    return xr.DataArray(values, dims=("y", "x"), attrs={"units": units})


def plot_domain(domain: Domain, classes: np.ndarray) -> Figure:
    """Map of the depth, and map of the basins and one-cell passages of a domain (:func:`domain_classes`)."""
    fig, axes = new_figure(2, width=7.5)
    draw_field(fig, axes[0], domain.depth, f"{domain.label}: depth", domain.lat, cmap="viridis_r")
    draw_categories(fig, axes[1], _field(classes), DOMAIN_CATEGORIES, f"{domain.label}: basins", domain.lat)
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


def ocean_at(domain: Domain, lon: np.ndarray, lat: np.ndarray, ocean: np.ndarray) -> np.ndarray:
    """An ocean mask on another grid, sampled at the T points of ``domain`` from the nearest point.

    Parameters
    ----------
    domain : Domain
        The domain whose cells receive the mask.
    lon, lat, ocean : numpy.ndarray
        Coordinates (degrees) and ocean mask of the other grid, all of the same shape.

    Returns
    -------
    numpy.ndarray
        The ocean mask on the cells of ``domain``.
    """
    return sample_nearest(lon, lat, ocean, domain.lon, domain.lat).astype(bool)


def plot_agreement(domain: Domain, other: np.ndarray, other_label: str, title: str) -> tuple[Figure, dict[str, int]]:
    """Map of where the ocean mask of ``domain`` and another mask on its cells agree.

    Parameters
    ----------
    domain : Domain
        The domain.
    other : numpy.ndarray
        The other ocean mask on the cells of ``domain`` (see :func:`ocean_at`).
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
