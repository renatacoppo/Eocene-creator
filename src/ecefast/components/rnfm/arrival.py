"""Arrival points of the runoff-mapper that deliver their water to NEMO through the OASIS weights.

The runoff-mapper sums the runoff of each drainage basin and spreads it uniformly per m² over the basin's arrival
cells (``arrival_point_id``, and ``calving_point_id`` for calving) on its F128 grid. OASIS then remaps the F128
ocean cells to the NEMO T grid with ``BILINEAR LR SCALAR`` weights, which do not conserve the total: an F128 cell
outside every bilinear stencil of the NEMO ocean delivers nothing, a cell next to a NEMO T-point delivers more than
it received. With the transfer factor of each F128 cell (water delivered to NEMO per unit of water put on it),
the fraction of a basin's runoff that reaches NEMO is the area-weighted mean transfer factor of its arrival cells.

The OASIS weights depend on ``drainage_basin_id`` only (rdy2cpl derives the F128 land-sea masks from it), not on
the arrival or calving cells. So the arrival cells can be moved without changing the weights: this module keeps the
drainage basins and rebuilds the arrival cells of the basins that deliver too little or too much.
"""

import logging
import shutil
from dataclasses import dataclass

import netCDF4
import numpy as np
import xarray as xr
from scipy.spatial import cKDTree

logger = logging.getLogger(__name__)

# Mean Earth radius (km), for the distances in the log
EARTH_RADIUS_KM = 6371.0
# A rebuilt basin delivers 1 +/- TARGET_ERROR of its runoff (the acceptance criterion of the runoff-maps plan)
TARGET_ERROR = 0.02
# Rebuilt arrival cells lie within this distance (km) of the basin's first arrival cell; a basin that cannot reach
# TARGET_ERROR within it is an error. Large enough for the coarse PALEORCA2 coast (the cells added to balance a
# basin are at most a few hundred km away on the present-day F128 grid).
MAX_SPREAD_KM = 1500.0
# Codes of the runoff-mapper maps (runoff_mapper_mod.F90): ocean without a discharge point
SEA = -2
# Variables of runoff_maps.nc with arrival cells: runoff, then calving
ARRIVAL_VARIABLES = ("arrival_point_id", "calving_point_id")


@dataclass
class BasinChange:
    """A basin whose arrival cells were rebuilt.

    Attributes
    ----------
    variable : str
        ``arrival_point_id`` or ``calving_point_id``.
    basin : int
        Basin id.
    before, after : float
        Fraction of the basin's water that reaches NEMO, with the old and the new arrival cells.
    cells_before, cells_after : int
        Number of arrival cells.
    moved_km : float
        Distance from the old arrival cells to the new ones; 0 when some old cells are kept.
    lat, lon : float
        Centre of the new arrival cells (degrees).
    """

    variable: str
    basin: int
    before: float
    after: float
    cells_before: int
    cells_after: int
    moved_km: float
    lat: float
    lon: float


def transfer_factors(
    src_address: np.ndarray,
    dst_address: np.ndarray,
    weights: np.ndarray,
    src_area: np.ndarray,
    dst_area: np.ndarray,
) -> np.ndarray:
    """Water delivered to the target grid per unit of water put on each source cell, for SCRIP remap weights.

    A flux ``F`` on source cell ``s`` gives ``w * F`` on each target cell ``d`` linked to it, so the water
    delivered is ``F * sum(w * A_d)`` for the water ``F * A_s`` put on it: ``T_s = sum(w * A_d) / A_s``.

    Parameters
    ----------
    src_address, dst_address : numpy.ndarray
        1-based cell addresses of the links (SCRIP ``src_address``, ``dst_address``); links with address 0 are
        ignored (OASIS pads the link list with them).
    weights : numpy.ndarray
        First weight of each link (SCRIP ``remap_matrix[:, 0]``).
    src_area, dst_area : numpy.ndarray
        Cell areas of the source and target grids, flattened in address order, in the same units.

    Returns
    -------
    numpy.ndarray
        Transfer factor of each source cell (0 for a cell without links).
    """
    src = np.asarray(src_address, dtype=np.int64) - 1
    dst = np.asarray(dst_address, dtype=np.int64) - 1
    valid = (src >= 0) & (dst >= 0)
    src, dst, w = src[valid], dst[valid], np.asarray(weights, dtype=np.float64)[valid]
    delivered = np.zeros(src_area.size)
    np.add.at(delivered, src, w * dst_area[dst])
    return delivered / src_area


def read_transfer_factors(rmp_file: str, areas_file: str, src_grid: str, dst_grid: str) -> np.ndarray:
    """Transfer factors of an OASIS remapping file (:func:`transfer_factors`), with the areas of ``areas.nc``.

    The ``src_grid_area`` and ``dst_grid_area`` of the OASIS remapping files are zero, so the areas come from the
    ``<grid>.srf`` variables of ``areas.nc`` (written by rdy2cpl, read by the runoff-mapper too).

    Parameters
    ----------
    rmp_file : str
        OASIS remapping file, e.g. ``rmp_F128R-ocean_to_PALEORCA2-T_BILINEAR.nc``.
    areas_file : str
        ``areas.nc`` of the same run.
    src_grid, dst_grid : str
        OASIS grid names, e.g. ``F128R-ocean`` and ``PALEORCA2-T``.

    Returns
    -------
    numpy.ndarray
        Transfer factor of each source cell, shape of ``<src_grid>.srf``.
    """
    with xr.open_dataset(rmp_file) as rmp, xr.open_dataset(areas_file) as areas:
        src_area = areas[f"{src_grid}.srf"].values.astype(np.float64)
        factors = transfer_factors(
            rmp["src_address"].values,
            rmp["dst_address"].values,
            rmp["remap_matrix"].values[:, 0],
            src_area.ravel(),
            areas[f"{dst_grid}.srf"].values.astype(np.float64).ravel(),
        )
    return factors.reshape(src_area.shape)


def unit_vectors(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """Points of a regular lat-lon grid as 3D unit vectors, shape ``(lat.size * lon.size, 3)``, row-major."""
    la, lo = np.meshgrid(np.deg2rad(lat), np.deg2rad(lon), indexing="ij")
    return np.stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)], axis=-1).reshape(-1, 3)


def delivered_fraction(cells: np.ndarray, factors: np.ndarray, area: np.ndarray) -> float:
    """Fraction of a basin's water that reaches the target grid: the area-weighted mean transfer factor of
    its arrival ``cells`` (flat indices)."""
    return float((factors[cells] * area[cells]).sum() / area[cells].sum())


def rebuild_basin(
    cells: np.ndarray,
    free: np.ndarray,
    factors: np.ndarray,
    area: np.ndarray,
    points: np.ndarray,
) -> tuple[np.ndarray, float]:
    """New arrival cells of one basin, delivering 1 +/- :data:`TARGET_ERROR` of its water.

    The old cells that deliver something are kept. If none does, the basin starts from the deliverable free cell
    nearest to the old ones (its sea is not in the NEMO grid: the water goes to the nearest coast). Then free
    deliverable cells are taken from the nearest outwards, each one only if it brings the delivered fraction closer
    to 1, until it is within :data:`TARGET_ERROR`.

    Parameters
    ----------
    cells : numpy.ndarray
        Flat indices of the basin's old arrival cells.
    free : numpy.ndarray
        Flat indices of the cells that may become arrival cells (ocean, no other basin, transfer factor > 0).
    factors, area : numpy.ndarray
        Transfer factor and area of every cell, flattened.
    points : numpy.ndarray
        Unit vectors of every cell, shape ``(n, 3)``.

    Returns
    -------
    numpy.ndarray
        Flat indices of the new arrival cells, sorted.
    float
        Distance (km) from the old cells to the first new cell when none of the old ones is kept, else 0.

    Raises
    ------
    ValueError
        If no free cell can take the water, or the target is not reached within :data:`MAX_SPREAD_KM`.
    """
    chosen = list(cells[factors[cells] > 0])
    if free.size == 0:
        raise ValueError("no free ocean cell delivers water to the target grid")
    moved_km = 0.0
    if not chosen:
        distance, nearest = cKDTree(points[free]).query(points[cells])
        first = free[nearest[np.argmin(distance)]]
        moved_km = chord_to_km(distance.min())
        chosen = [first]
    candidates = free[~np.isin(free, chosen)]
    distance = chord_to_km(cKDTree(points[chosen]).query(points[candidates])[0])
    order = np.argsort(distance, kind="stable")

    water = float((factors[chosen] * area[chosen]).sum())
    total = float(area[chosen].sum())
    for cell, km in zip(candidates[order], distance[order]):
        if abs(water / total - 1.0) <= TARGET_ERROR:
            break
        if km > MAX_SPREAD_KM:
            break
        new = (water + factors[cell] * area[cell]) / (total + area[cell])
        if abs(new - 1.0) < abs(water / total - 1.0):
            chosen.append(cell)
            water += factors[cell] * area[cell]
            total += area[cell]
    if abs(water / total - 1.0) > TARGET_ERROR:
        raise ValueError(
            f"delivers {water / total:.3f} of its water with every useful cell within {MAX_SPREAD_KM:.0f} km"
        )
    return np.sort(np.array(chosen, dtype=np.int64)), moved_km


def chord_to_km(chord: np.ndarray | float) -> np.ndarray | float:
    """Great-circle distance (km) of the chord length between two unit vectors."""
    return 2.0 * EARTH_RADIUS_KM * np.arcsin(np.clip(np.asarray(chord) / 2.0, 0.0, 1.0))


def fix_arrival_ids(
    ids: np.ndarray,
    factors: np.ndarray,
    area: np.ndarray,
    points: np.ndarray,
    max_error: float,
    variable: str = "arrival_point_id",
) -> tuple[np.ndarray, list[BasinChange]]:
    """Rebuild the arrival cells of the basins whose delivered fraction differs from 1 by more than ``max_error``.

    Basins are rebuilt in id order with :func:`rebuild_basin`. Their old cells that deliver nothing become sea
    (``-2``); cells of other basins and lakes (``-1``) are never taken.

    Parameters
    ----------
    ids : numpy.ndarray
        Arrival (or calving) ids on the runoff-mapper grid, 2D: basin id > 0, ``-1`` lake, ``-2`` sea.
    factors, area : numpy.ndarray
        Transfer factor and cell area on the same grid.
    points : numpy.ndarray
        Unit vectors of the cells, flattened in the same order (:func:`unit_vectors`).
    max_error : float
        Basins delivering a fraction outside ``1 +/- max_error`` are rebuilt.
    variable : str
        Name of the ids, for the log and the changes.

    Returns
    -------
    numpy.ndarray
        The new ids, same shape and dtype.
    list of BasinChange
        The rebuilt basins.

    Raises
    ------
    ValueError
        If a basin cannot be rebuilt (see :func:`rebuild_basin`), naming it.
    """
    new = ids.ravel().copy()
    factors, area = factors.ravel(), area.ravel()
    changes = []
    for basin in range(1, int(new.max()) + 1):
        cells = np.flatnonzero(new == basin)
        if cells.size == 0:
            continue
        before = delivered_fraction(cells, factors, area)
        if abs(before - 1.0) <= max_error:
            continue
        new[cells[factors[cells] == 0]] = SEA
        free = np.flatnonzero((new == SEA) & (factors > 0))
        try:
            chosen, moved_km = rebuild_basin(cells, free, factors, area, points)
        except ValueError as e:
            raise ValueError(f"{variable}: basin {basin} cannot be rebuilt: {e}") from e
        new[chosen] = basin
        x, y, z = points[chosen].mean(axis=0)
        lat, lon = np.rad2deg(np.arctan2(z, np.hypot(x, y))), np.rad2deg(np.arctan2(y, x))
        changes.append(
            BasinChange(
                variable,
                basin,
                before,
                delivered_fraction(chosen, factors, area),
                int(cells.size),
                int(chosen.size),
                float(moved_km),
                float(lat),
                float(lon),
            )
        )
    return new.reshape(ids.shape).astype(ids.dtype), changes


def fix_runoff_maps(maps: xr.Dataset, factors: np.ndarray, area: np.ndarray, max_error: float) -> list[BasinChange]:
    """Rebuild, in place, the arrival and calving cells of ``maps`` that deliver badly (:func:`fix_arrival_ids`).

    ``drainage_basin_id`` is not changed, so the OASIS weights stay the same. The global ``history`` attribute
    gets a line.

    Parameters
    ----------
    maps : xarray.Dataset
        ``runoff_maps.nc`` (``drainage_basin_id``, ``arrival_point_id``, ``calving_point_id`` on ``lat``, ``lon``),
        loaded.
    factors, area : numpy.ndarray
        Transfer factor and cell area of its grid, shape ``(lat, lon)``.
    max_error : float
        Basins delivering a fraction outside ``1 +/- max_error`` are rebuilt.

    Returns
    -------
    list of BasinChange
        The rebuilt basins of both variables.

    Raises
    ------
    ValueError
        If the grids do not match, or a basin cannot be rebuilt.
    """
    shape = maps["drainage_basin_id"].shape
    if factors.shape != shape or area.shape != shape:
        raise ValueError(f"runoff maps {shape} and remapping weights {factors.shape} are on different grids")
    points = unit_vectors(maps["lat"].values, maps["lon"].values)
    changes = []
    for variable in ARRIVAL_VARIABLES:
        ids, rebuilt = fix_arrival_ids(maps[variable].values, factors, area, points, max_error, variable)
        maps[variable].values = ids
        changes += rebuilt
    history = maps.attrs.get("history", "")
    line = (
        f"ecefast: arrival and calving points of the basins delivering outside 1 +/- {max_error} of their water "
        f"through the OASIS bilinear weights moved to cells delivering 1 +/- {TARGET_ERROR}"
    )
    maps.attrs["history"] = f"{history}\n{line}" if history else line
    return changes


def write_runoff_maps(template: str, maps: xr.Dataset, output: str) -> None:
    """Write ``maps`` as a copy of the file ``template`` with its arrival and calving ids and ``history`` replaced.

    Copying the original file keeps the order of its dimensions and variables, attributes and encoding, which
    xarray would change.

    Parameters
    ----------
    template : str
        The original ``runoff_maps.nc`` that ``maps`` was read from.
    maps : xarray.Dataset
        The maps with the new ids (:func:`fix_runoff_maps`).
    output : str
        File to write (a temporary path of :func:`~ecefast.core.io.atomic_write`).
    """
    shutil.copyfile(template, output)
    with netCDF4.Dataset(output, "a") as nc:
        for variable in ARRIVAL_VARIABLES:
            nc[variable][:] = maps[variable].values
        nc.history = maps.attrs["history"]


def log_changes(changes: list[BasinChange]) -> None:
    """Log the rebuilt basins: one line each, and a warning for those whose water goes to another coast."""
    for c in changes:
        logger.info(
            "%s basin %d: delivered %.2f -> %.2f, %d -> %d cells around (%.1f, %.1f)",
            c.variable,
            c.basin,
            c.before,
            c.after,
            c.cells_before,
            c.cells_after,
            c.lat,
            c.lon,
        )
        if c.moved_km > 0:
            logger.warning(
                "%s basin %d: its sea is not in the NEMO grid, water moved %.0f km to (%.1f, %.1f)",
                c.variable,
                c.basin,
                c.moved_km,
                c.lat,
                c.lon,
            )
