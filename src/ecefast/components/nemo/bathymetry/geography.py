"""Rule-based geography of a NEMO land-sea mask (data version v2).

The rules replace the hand-made strait corrections of v1. They act on a boolean ocean mask on a NEMO grid and
see two cells as connected only when they share a side: the velocity points of the C grid lie on the cell sides,
so water does not flow through a corner. The grid is periodic east-west, and its top row folds onto itself
(``jperio`` 4: T-point pivot, as PALEORCA2 and ORCA2; ``jperio`` 6: F-point pivot, as eORCA1).

:func:`apply_rules` runs them in this order:

1. :func:`open_corner_contacts`: two water bodies that touch only at a corner are joined;
2. :func:`remove_closed_seas`: water not connected to the main ocean becomes land;
3. :func:`remove_inlets`: one-cell-wide dead ends become land;
4. :func:`remove_isolated_islands`: one-cell islands with no land around them become ocean.

Corner contacts are opened before closed seas are removed: in a remapped mask, seas such as the Mediterranean or
the Baltic often touch the ocean only at a corner, and would otherwise be removed.

Straits with a fixed sill depth (:func:`open_sills`, :func:`check_sills`) are opened before the rules.

With a T-point pivot the top row holds every cell twice: ``(i, top)`` and ``(-i, top)`` are the same cell, and NEMO
(DOMAINcfg included) overwrites the right half of the row with the mirrored left half. :func:`apply_rules` makes the
row symmetric first (:func:`symmetrize_fold`, left half wins) and every rule changes both copies of a cell, so
DOMAINcfg finds nothing to change.
"""

import logging
from dataclasses import dataclass, field

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

logger = logging.getLogger(__name__)

# north-fold types of NEMO (namelist parameter jperio)
T_PIVOT, F_PIVOT = 4, 6

Edges = tuple[np.ndarray, np.ndarray]


@dataclass
class RulesReport:
    """What :func:`apply_rules` changed: cells as ``(j, i)`` indices."""

    opened_corners: list[tuple[int, int]] = field(default_factory=list)
    closed_seas: list[int] = field(default_factory=list)  # size in cells of each water body removed
    removed_inlets: int = 0
    removed_islands: list[tuple[int, int]] = field(default_factory=list)
    fold_cells: int = 0  # cells of the right half of the fold row changed to match the left half


def side_edges(shape: tuple[int, int], jperio: int) -> Edges:
    """Pairs of flat cell indices that share a side, with the east-west period and the north fold.

    Parameters
    ----------
    shape : tuple of int
        ``(ny, nx)`` of the grid, without halo.
    jperio : int
        North fold: 4 (T-point pivot) or 6 (F-point pivot).

    Returns
    -------
    tuple of numpy.ndarray
        Two arrays of the same length; ``a[k]`` and ``b[k]`` share a side.

    Raises
    ------
    ValueError
        If ``jperio`` is neither 4 nor 6.
    """
    ny, nx = shape
    idx = np.arange(ny * nx).reshape(shape)
    first = [idx.ravel(), idx[:-1].ravel()]
    second = [np.roll(idx, -1, axis=1).ravel(), idx[1:].ravel()]  # east neighbour (periodic), north neighbour
    i, top = np.arange(nx), ny - 1
    if jperio == T_PIVOT:
        # (i, top) is the same cell as (-i, top), and its northern neighbour is (-i, top - 1)
        first += [idx[top, i], idx[top, i]]
        second += [idx[top, (-i) % nx], idx[top - 1, (-i) % nx]]
    elif jperio == F_PIVOT:
        # the northern neighbour of (i, top) is (nx - 1 - i, top)
        first.append(idx[top, i])
        second.append(idx[top, nx - 1 - i])
    else:
        raise ValueError(f"North fold jperio={jperio} is not handled: use {T_PIVOT} (T-point) or {F_PIVOT} (F-point)")
    return np.concatenate(first), np.concatenate(second)


def label_bodies(cells: np.ndarray, edges: Edges) -> np.ndarray:
    """Label the connected groups of ``cells`` (side connectivity); -1 outside ``cells``."""
    flat = cells.ravel()
    a, b = edges
    keep = flat[a] & flat[b]
    graph = coo_matrix((np.ones(keep.sum()), (a[keep], b[keep])), shape=(flat.size, flat.size))
    _, labels = connected_components(graph, directed=False)
    return np.where(flat, labels, -1).reshape(cells.shape)


def side_neighbours(cells: np.ndarray, edges: Edges) -> np.ndarray:
    """Cells that share a side with any of ``cells`` (``cells`` themselves only if they touch each other)."""
    flat = cells.ravel()
    a, b = edges
    out = np.zeros(flat.size, dtype=bool)
    out[b[flat[a]]] = True
    out[a[flat[b]]] = True
    return out.reshape(cells.shape)


def one_cell_wide(ocean: np.ndarray, jperio: int) -> np.ndarray:
    """Ocean cells with land on both sides along one axis and ocean on at least one side of the other.

    The northern neighbour of the top row is taken across the north fold.
    """
    nx = ocean.shape[1]
    west, east = np.roll(ocean, 1, axis=1), np.roll(ocean, -1, axis=1)
    north = np.zeros_like(ocean)
    north[:-1] = ocean[1:]
    i = np.arange(nx)
    north[-1] = ocean[-2, (-i) % nx] if jperio == T_PIVOT else ocean[-1, nx - 1 - i]
    south = np.zeros_like(ocean)
    south[1:] = ocean[:-1]
    return ocean & ((~west & ~east & (north | south)) | (~north & ~south & (west | east)))


def fold_twin(cell: tuple[int, int], shape: tuple[int, int], jperio: int) -> tuple[int, int] | None:
    """The other copy of a top-row cell with a T-point pivot, ``(top, -i)``; None if the cell has no other copy."""
    ny, nx = shape
    j, i = cell
    if jperio != T_PIVOT or j != ny - 1 or (-i) % nx == i:
        return None
    return j, (-i) % nx


def _fold_halves(nx: int) -> tuple[np.ndarray, np.ndarray]:
    """Columns of the left half of a T-point fold row and of their copies in the right half (cells 0 and nx / 2
    are their own copy)."""
    left = np.arange(1, nx // 2 + (nx % 2))
    return left, (-left) % nx


def fold_nodes(shape: tuple[int, int], jperio: int) -> np.ndarray:
    """Flat index of each cell, the two copies of a top-row cell (T-point pivot) sharing the index of the left one.

    Cells with the same number are the same cell of the model, so a count of cells or of neighbours counts them once.
    """
    nodes = np.arange(shape[0] * shape[1]).reshape(shape)
    if jperio == T_PIVOT:
        left, right = _fold_halves(shape[1])
        nodes[-1, right] = nodes[-1, left]
    return nodes


def symmetrize_fold(ocean: np.ndarray, depth: np.ndarray, jperio: int) -> int:
    """Make the top row symmetric with a T-point pivot: the left half wins, as in NEMO. Changes the arrays in place.

    Returns
    -------
    int
        The number of cells of the right half that changed.
    """
    if jperio != T_PIVOT:
        return 0
    left, right = _fold_halves(ocean.shape[1])
    changed = int((ocean[-1, right] != ocean[-1, left]).sum())
    ocean[-1, right] = ocean[-1, left]
    depth[-1, right] = depth[-1, left]
    return changed


def check_fold(ocean: np.ndarray, jperio: int) -> None:
    """Raise ValueError if the two copies of a top-row cell differ (T-point pivot)."""
    if jperio == T_PIVOT:
        nx = ocean.shape[1]
        i = np.arange(nx)
        if (ocean[-1, i] != ocean[-1, (-i) % nx]).any():
            raise ValueError("The two copies of a cell of the north-fold row differ")


def set_cell(ocean: np.ndarray, depth: np.ndarray, cell: tuple[int, int], value: float, jperio: int) -> None:
    """Make ``cell`` ocean with depth ``value`` (land if ``value`` is 0), and its fold twin too."""
    for target in (cell, fold_twin(cell, ocean.shape, jperio)):
        if target is not None:
            ocean[target] = value > 0
            depth[target] = value


def is_only_link(ocean: np.ndarray, cells: np.ndarray, edges: Edges) -> bool:
    """Whether removing ``cells`` splits the water around them in two or more bodies."""
    bodies = label_bodies(ocean & ~cells, edges)
    around = side_neighbours(cells, edges) & ocean & ~cells
    return len(np.unique(bodies[around])) >= 2


def open_corner_contacts(
    ocean: np.ndarray, depth: np.ndarray, fraction: np.ndarray, minimum_depth: float, jperio: int, edges: Edges
) -> list[tuple[int, int]]:
    """Rule 1: join two water bodies that touch only at a corner. Changes ``ocean`` and ``depth`` in place.

    Where two ocean cells touch only at a corner (both cells between them are land) and belong to different water
    bodies, the land cell between them with the larger ocean fraction becomes ocean at ``minimum_depth``. A corner
    between cells of the same water body is left alone: opening it would only cut a land bridge, such as a
    peninsula. The water bodies are recomputed after each opening, so a corner joined meanwhile through another
    one stays closed. Corners across the north fold are not searched.

    Returns
    -------
    list of tuple
        The cells opened.
    """
    ny, nx = ocean.shape
    labels = label_bodies(ocean, edges)
    opened = []
    for j in range(ny - 1):
        for i in range(nx):
            for di in (1, -1):
                i2 = (i + di) % nx
                a, b = (j, i2), (j + 1, i)  # the two cells that share a side with both (j, i) and (j + 1, i2)
                if not (ocean[j, i] and ocean[j + 1, i2]) or ocean[a] or ocean[b]:
                    continue
                if labels[j, i] == labels[j + 1, i2]:
                    continue
                cell = a if fraction[a] >= fraction[b] else b
                set_cell(ocean, depth, cell, minimum_depth, jperio)
                labels = label_bodies(ocean, edges)
                opened.append(cell)
    return opened


def remove_closed_seas(ocean: np.ndarray, edges: Edges) -> list[int]:
    """Rule 2: water that is not connected to the largest water body becomes land. Changes ``ocean`` in place.

    Returns
    -------
    list of int
        The size in cells of each water body removed, largest first.
    """
    labels = label_bodies(ocean, edges)
    ids, counts = np.unique(labels[labels >= 0], return_counts=True)
    if ids.size < 2:
        return []
    main = ids[counts.argmax()]
    ocean &= labels == main
    return sorted((int(c) for i, c in zip(ids, counts) if i != main), reverse=True)


def remove_inlets(ocean: np.ndarray, jperio: int, edges: Edges, keep: np.ndarray | None = None) -> int:
    """Rule 3: one-cell-wide dead ends become land, in a single pass. Changes ``ocean`` in place.

    A dead end is a group of one-cell-wide cells (:func:`one_cell_wide`) that touches the rest of the ocean through
    a single cell. Only the dead ends of the mask as it is are removed: the cells that become dead ends afterwards
    stay, so a narrow sea behind a one-cell strait is not eaten away cell by cell. The two copies of a cell of a
    symmetric fold row are one-cell-wide together and share a side, so they are removed together.

    Parameters
    ----------
    keep : numpy.ndarray, optional
        Cells never removed (the straits with a fixed sill).

    Returns
    -------
    int
        The number of cells removed.
    """
    narrow = one_cell_wide(ocean, jperio)
    segments = label_bodies(narrow, edges)
    original = ocean.copy()
    removed = 0
    for s in np.unique(segments[segments >= 0]):
        cells = segments == s
        if keep is not None and (cells & keep).any():
            continue
        if (side_neighbours(cells, edges) & original & ~cells).sum() == 1:
            ocean &= ~cells
            removed += int(cells.sum())
    return removed


def remove_isolated_islands(ocean: np.ndarray, depth: np.ndarray) -> list[tuple[int, int]]:
    """Rule 4: a land cell with no land among its eight neighbours becomes ocean. Changes the arrays in place.

    The new ocean cell gets the mean depth of its neighbours. The first and last rows are not searched.

    Returns
    -------
    list of tuple
        The cells turned into ocean.
    """
    ny, nx = ocean.shape
    land = ~ocean
    islands = []
    for j in range(1, ny - 1):
        for i in range(nx):
            if not land[j, i]:
                continue
            cols = [(i - 1) % nx, i, (i + 1) % nx]
            if land[j - 1 : j + 2][:, cols].sum() == 1:
                neighbours = depth[j - 1 : j + 2][:, cols]
                depth[j, i] = neighbours[neighbours > 0].mean()
                ocean[j, i] = True
                islands.append((j, i))
    return islands


def nearest_cell(lon: np.ndarray, lat: np.ndarray, point: tuple[float, float]) -> tuple[int, int]:
    """The cell whose centre is nearest to ``point`` = ``(lon, lat)`` in degrees."""
    lon0, lat0 = point
    dlon = (lon - lon0 + 180) % 360 - 180
    distance = np.hypot(dlon * np.cos(np.deg2rad(lat0)), lat - lat0)
    j, i = np.unravel_index(np.argmin(distance), lon.shape)
    return int(j), int(i)


def open_sills(
    ocean: np.ndarray,
    depth: np.ndarray,
    lon: np.ndarray,
    lat: np.ndarray,
    sills: dict[str, tuple[float, float, float]],
    jperio: int,
) -> dict[str, tuple[int, int]]:
    """Give the cell nearest to each strait its sill depth, opening it if it is land. Changes the arrays in place.

    Parameters
    ----------
    lon, lat : numpy.ndarray
        Cell centres of the grid (degrees).
    sills : dict
        Strait name -> ``(lon, lat, sill depth in m)``.

    Returns
    -------
    dict
        Strait name -> its cell ``(j, i)``.
    """
    cells = {}
    for name, (lon0, lat0, sill) in sills.items():
        cell = nearest_cell(lon, lat, (lon0, lat0))
        logger.debug(
            "Sill %s: cell %s, %s, depth %.0f m -> %.0f m",
            name,
            cell,
            "ocean" if ocean[cell] else "land",
            depth[cell],
            sill,
        )
        set_cell(ocean, depth, cell, sill, jperio)
        cells[name] = cell
    return cells


def check_sills(ocean: np.ndarray, cells: dict[str, tuple[int, int]], edges: Edges) -> None:
    """Check that each sill cell is ocean and the only link between two basins, so the sill depth controls the flow.

    Raises
    ------
    ValueError
        If a sill cell is land, or water can flow around it.
    """
    for name, cell in cells.items():
        if not ocean[cell]:
            raise ValueError(f"Sill {name}: cell {cell} became land")
        here = np.zeros_like(ocean)
        here[cell] = True
        if not is_only_link(ocean, here, edges):
            raise ValueError(
                f"Sill {name}: cell {cell} is not the only link between two basins, so its sill depth does not "
                "control the flow: water flows around it (the strait is wider than one cell there, or a geography "
                "rule opened another path). Check the sill position against the bathymetry"
            )


def apply_rules(
    ocean: np.ndarray,
    depth: np.ndarray,
    fraction: np.ndarray,
    minimum_depth: float,
    jperio: int,
    lon: np.ndarray | None = None,
    lat: np.ndarray | None = None,
    sills: dict[str, tuple[float, float, float]] | None = None,
) -> RulesReport:
    """Open the sills, then apply the four rules in order. Changes ``ocean`` and ``depth`` in place.

    Parameters
    ----------
    ocean : numpy.ndarray of bool
        Ocean mask.
    depth : numpy.ndarray
        Depth (m, positive), 0 on land.
    fraction : numpy.ndarray
        Ocean fraction of each cell, used by rule 1 to pick the cell to open.
    minimum_depth : float
        Depth of the cells opened by rule 1 (m).
    jperio : int
        North fold of the grid (4 or 6).
    lon, lat : numpy.ndarray, optional
        Cell centres, needed with ``sills``.
    sills : dict, optional
        Straits with a fixed sill depth, see :func:`open_sills`.

    Returns
    -------
    RulesReport
        What the rules changed.
    """
    edges = side_edges(ocean.shape, jperio)
    report = RulesReport()
    fraction = np.nan_to_num(fraction, nan=0.0)  # cells outside the source (e.g. south of ORCA2) have no fraction
    report.fold_cells = symmetrize_fold(ocean, depth, jperio)
    sill_cells = open_sills(ocean, depth, lon, lat, sills, jperio) if sills else {}
    keep = np.zeros_like(ocean)
    for cell in sill_cells.values():
        keep[cell] = True
        twin = fold_twin(cell, ocean.shape, jperio)
        if twin is not None:
            keep[twin] = True

    report.opened_corners = open_corner_contacts(ocean, depth, fraction, minimum_depth, jperio, edges)
    report.closed_seas = remove_closed_seas(ocean, edges)
    report.removed_inlets = remove_inlets(ocean, jperio, edges, keep=keep)
    report.removed_islands = remove_isolated_islands(ocean, depth)
    depth[~ocean] = 0.0
    check_fold(ocean, jperio)
    check_sills(ocean, sill_cells, edges)
    return report
