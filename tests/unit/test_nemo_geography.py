"""Unit tests of the rule-based geography of data version v2 (``components/nemo/bathymetry/geography.py``).

Grids are drawn as text, north at the top: ``~`` ocean, ``#`` land. The top row is land unless a test is about
the north fold, so the fold does not connect anything.
"""

import numpy as np
import pytest

from ecefast.components.nemo.bathymetry import geography as g

pytestmark = pytest.mark.unit


def grid(*rows: str) -> np.ndarray:
    """An ocean mask from text rows, north first."""
    return np.array([[c == "~" for c in row] for row in rows[::-1]])


def draw(ocean: np.ndarray) -> list[str]:
    """The text rows of an ocean mask, north first."""
    return ["".join("~" if v else "#" for v in row) for row in ocean[::-1]]


def depth_of(ocean: np.ndarray, value: float = 1000.0) -> np.ndarray:
    return np.where(ocean, value, 0.0)


def edges_set(shape, jperio) -> set[tuple[int, int]]:
    a, b = g.side_edges(shape, jperio)
    return {(int(x), int(y)) for x, y in zip(a, b)} | {(int(y), int(x)) for x, y in zip(a, b)}


# --- connectivity --------------------------------------------------------------------------------------------------


def test_side_edges_east_west_period() -> None:
    edges = edges_set((4, 6), g.T_PIVOT)
    assert (0 * 6 + 5, 0 * 6 + 0) in edges  # last and first column
    assert (0 * 6 + 0, 1 * 6 + 1) not in edges  # no corner contact


def test_side_edges_t_pivot_fold() -> None:
    """T pivot: (i, top) is the same cell as (-i, top), and its northern neighbour is (-i, top - 1)."""
    edges = edges_set((4, 6), g.T_PIVOT)
    assert (3 * 6 + 1, 3 * 6 + 5) in edges
    assert (3 * 6 + 1, 2 * 6 + 5) in edges


def test_side_edges_f_pivot_fold() -> None:
    """F pivot: the northern neighbour of (i, top) is (nx - 1 - i, top)."""
    edges = edges_set((4, 6), g.F_PIVOT)
    assert (3 * 6 + 1, 3 * 6 + 4) in edges
    assert (3 * 6 + 1, 2 * 6 + 4) not in edges


def test_side_edges_rejects_other_folds() -> None:
    with pytest.raises(ValueError, match="jperio=5"):
        g.side_edges((4, 6), 5)


def test_one_cell_wide_uses_the_fold() -> None:
    """A top-row cell with land east, west and south is one cell wide through its neighbour across the fold."""
    ocean = grid(
        "#~####",  # (2, 1): with T pivot its northern neighbour is (1, 5)
        "#####~",
        "######",
    )
    assert g.one_cell_wide(ocean, g.T_PIVOT)[2, 1]
    assert not g.one_cell_wide(ocean, g.F_PIVOT)[2, 1]  # F pivot: its neighbour is (2, 4), land


def test_fold_nodes() -> None:
    """T pivot: the right half of the top row takes the index of its copy in the left half; cells 0 and nx / 2
    are their own copy. F pivot: every cell is its own node."""
    nodes = g.fold_nodes((2, 6), g.T_PIVOT)
    np.testing.assert_array_equal(nodes[0], np.arange(6))
    np.testing.assert_array_equal(nodes[1], [6, 7, 8, 9, 8, 7])
    np.testing.assert_array_equal(g.fold_nodes((2, 6), g.F_PIVOT).ravel(), np.arange(12))


# --- rule 1: corner contacts ---------------------------------------------------------------------------------------


def test_corner_contact_between_two_bodies_is_opened() -> None:
    ocean = grid(
        "########",
        "#~~#####",
        "#~~#####",
        "###~~~~#",
        "###~~~~#",
        "########",
    )
    fraction = np.zeros(ocean.shape)
    fraction[3, 3] = 0.4  # the land cell north of (2, 3): larger ocean fraction than (2, 2)
    fraction[2, 2] = 0.1
    depth = depth_of(ocean)
    opened = g.open_corner_contacts(ocean, depth, fraction, 30.0, g.T_PIVOT, g.side_edges(ocean.shape, g.T_PIVOT))
    assert opened == [(3, 3)]
    assert ocean[3, 3] and depth[3, 3] == 30.0
    assert len(np.unique(g.label_bodies(ocean, g.side_edges(ocean.shape, g.T_PIVOT)))) == 2  # one body + land


def test_corner_contact_inside_one_body_is_left_closed() -> None:
    """Two parts of the same water body that touch at a corner across a peninsula: opening it would cut the land."""
    ocean = grid(
        "#######",
        "#~~~~~#",
        "#~###~#",
        "#~#~~~#",
        "#~~####",
        "#######",
    )
    before = ocean.copy()
    edges = g.side_edges(ocean.shape, g.T_PIVOT)
    opened = g.open_corner_contacts(ocean, depth_of(ocean), np.ones(ocean.shape), 30.0, g.T_PIVOT, edges)
    assert opened == []
    assert (ocean == before).all()


def test_corner_already_joined_through_another_is_left_closed() -> None:
    """After the first opening joins (2, 3) to the main body, the second corner of (2, 3) is not opened too."""
    ocean = grid(
        "########",
        "##~~~###",
        "##~#~###",
        "#~#~####",
        "########",
    )
    fraction = np.zeros(ocean.shape)
    fraction[1, 2] = 0.4
    edges = g.side_edges(ocean.shape, g.T_PIVOT)
    assert g.open_corner_contacts(ocean, depth_of(ocean), fraction, 30.0, g.T_PIVOT, edges) == [(1, 2)]


# --- north fold ----------------------------------------------------------------------------------------------------


def test_fold_row_made_symmetric_left_half_wins() -> None:
    ocean = grid(
        "#~~#~~##",  # top row (j = 2): the copies (1, 7), (2, 6) and (3, 5) differ; 0 and 4 are their own copy
        "~~~~~~~~",
        "########",
    )
    depth = depth_of(ocean)
    assert g.symmetrize_fold(ocean, depth, g.T_PIVOT) == 3
    assert draw(ocean)[0] == "#~~#~#~~"
    i = np.arange(8)
    assert (ocean[-1, i] == ocean[-1, (-i) % 8]).all() and (depth[-1, i] == depth[-1, (-i) % 8]).all()
    assert g.symmetrize_fold(ocean, depth, g.F_PIVOT) == 0  # F pivot: no cell is held twice


def test_changes_on_the_fold_row_change_both_copies() -> None:
    ocean, depth = grid("########", "~~~~~~~~", "########"), np.zeros((3, 8))
    g.set_cell(ocean, depth, (2, 1), 284.0, g.T_PIVOT)
    assert ocean[2, 1] and ocean[2, 7] and depth[2, 7] == 284.0
    g.set_cell(ocean, depth, (2, 4), 30.0, g.T_PIVOT)  # its own copy
    assert ocean[2].sum() == 3
    assert g.fold_twin((1, 1), ocean.shape, g.T_PIVOT) is None
    assert g.fold_twin((2, 1), ocean.shape, g.F_PIVOT) is None


def test_apply_rules_leaves_a_symmetric_fold_row() -> None:
    ocean = grid(
        "#~~##~~#",  # not symmetric: (7, 1) ocean, (7, 7) land; (7, 6) ocean, (7, 2) ocean
        "~~~~~~~~",
        "~~~~~~~~",
        "########",
    )
    report = g.apply_rules(ocean, depth_of(ocean), np.ones(ocean.shape), 30.0, g.T_PIVOT)
    assert report.fold_cells > 0
    g.check_fold(ocean, g.T_PIVOT)


# --- rule 2: closed seas -------------------------------------------------------------------------------------------


def test_closed_seas_become_land() -> None:
    ocean = grid(
        "#########",
        "#~~~~#~~#",
        "#~~~~#~~#",
        "#~~~~####",
        "######~##",
        "#########",
    )
    seas = g.remove_closed_seas(ocean, g.side_edges(ocean.shape, g.T_PIVOT))
    assert seas == [4, 1]
    assert draw(ocean) == [
        "#########",
        "#~~~~####",
        "#~~~~####",
        "#~~~~####",
        "#########",
        "#########",
    ]


def test_water_across_the_dateline_is_one_body() -> None:
    ocean = grid(
        "######",
        "~~##~~",
        "~~##~~",
        "######",
    )
    assert g.remove_closed_seas(ocean, g.side_edges(ocean.shape, g.T_PIVOT)) == []


def test_sea_joined_at_a_corner_survives_the_rules() -> None:
    """Rule 1 runs before rule 2: a sea that touches the ocean only at a corner is joined, not removed."""
    ocean = grid(
        "##########",
        "#~~~~#####",
        "#~~~~#####",
        "#~~~~#####",
        "#####~~~~#",
        "#####~~~~#",
        "##########",
    )
    depth = depth_of(ocean)
    report = g.apply_rules(ocean, depth, np.full(ocean.shape, 0.3), 30.0, g.T_PIVOT)
    assert len(report.opened_corners) == 1
    assert report.closed_seas == []
    assert ocean.sum() == 4 * 3 + 4 * 2 + 1


# --- rule 3: inlets ------------------------------------------------------------------------------------------------


def test_inlet_is_removed_and_strait_kept() -> None:
    """A one-cell dead end becomes land; a one-cell strait to a basin, the only link, stays."""
    ocean = grid(
        "###########",
        "#~~~~~#~~~#",
        "#~~~~~~~~~#",  # (4, 6): one-cell strait between the two basins
        "#~~~~~#~~~#",
        "#~~~~~#####",
        "##~########",  # (1, 2): inlet, a dead end
        "###########",
    )
    removed = g.remove_inlets(ocean, g.T_PIVOT, g.side_edges(ocean.shape, g.T_PIVOT))
    assert removed == 1
    assert not ocean[1, 2]
    assert ocean[4, 6]


def test_inlets_are_removed_in_a_single_pass() -> None:
    """Only the dead ends of the mask as it is: a cell that becomes a dead end after the removal stays."""
    ocean = grid(
        "########",
        "#~~~~~~#",
        "#~~~~~~#",
        "####~###",  # (3, 4): one cell wide, dead end of a two-cell inlet
        "####~###",  # (2, 4)
        "###~~###",
        "########",
    )
    # (1, 3) is a one-cell dead end; (3, 4) and (2, 4) are one cell wide but lead to (1, 4), which is not
    removed = g.remove_inlets(ocean, g.T_PIVOT, g.side_edges(ocean.shape, g.T_PIVOT))
    assert removed == 1 and not ocean[1, 3]
    # (1, 4) is now a dead end, but it stays: the inlet is not eaten cell by cell
    assert ocean[1, 4] and ocean[2, 4] and ocean[3, 4]


def test_inlet_with_a_sill_is_kept() -> None:
    ocean = grid(
        "######",
        "#~~~~#",
        "#~~~~#",
        "##~###",
        "######",
    )
    keep = np.zeros(ocean.shape, dtype=bool)
    keep[1, 2] = True
    assert g.remove_inlets(ocean, g.T_PIVOT, g.side_edges(ocean.shape, g.T_PIVOT), keep=keep) == 0
    assert ocean[1, 2]


# --- rule 4: isolated islands --------------------------------------------------------------------------------------


def test_isolated_island_becomes_ocean() -> None:
    ocean = grid(
        "#########",
        "~~~~~~~~~",
        "~~#~~~##~",  # (3, 2): isolated; (3, 6) and (3, 7): a two-cell island, kept
        "~~~~~~~~~",
        "~~~~~#~~~",  # (1, 5): one land cell, but it touches the land of row 0, kept
        "#########",
    )
    depth = depth_of(ocean, 200.0)
    depth[2, 2] = 400.0
    islands = g.remove_isolated_islands(ocean, depth)
    assert islands == [(3, 2)]
    assert ocean[3, 2] and depth[3, 2] == pytest.approx((7 * 200.0 + 400.0) / 8)
    assert not ocean[3, 6] and not ocean[3, 7] and not ocean[1, 5]


# --- sills ---------------------------------------------------------------------------------------------------------


def lon_lat(shape):
    ny, nx = shape
    lon = np.arange(nx, dtype=float)[None].repeat(ny, axis=0)
    lat = np.arange(ny, dtype=float)[:, None].repeat(nx, axis=1)
    return lon, lat


def test_sill_opens_the_strait_and_sets_its_depth() -> None:
    ocean = grid(
        "#########",
        "#~~~#~~~#",
        "#~~~#~~~#",
        "#~~~#~~~#",
        "#########",
    )
    depth = depth_of(ocean)
    lon, lat = lon_lat(ocean.shape)
    cells = g.open_sills(ocean, depth, lon, lat, {"Strait": (4.2, 2.1, 284.0)}, g.T_PIVOT)
    assert cells == {"Strait": (2, 4)}
    assert ocean[2, 4] and depth[2, 4] == 284.0
    g.check_sills(ocean, cells, g.side_edges(ocean.shape, g.T_PIVOT))


def test_sill_must_be_the_only_link() -> None:
    ocean = grid(
        "#########",
        "#~~~~~~~#",
        "#~~~~~~~#",
        "#########",
    )
    with pytest.raises(ValueError, match="not the only link"):
        g.check_sills(ocean, {"Strait": (1, 4)}, g.side_edges(ocean.shape, g.T_PIVOT))


def test_sill_cell_that_became_land() -> None:
    ocean = grid("#####", "#~#~#", "#####")
    with pytest.raises(ValueError, match="became land"):
        g.check_sills(ocean, {"Strait": (1, 2)}, g.side_edges(ocean.shape, g.T_PIVOT))


def test_nearest_cell_across_the_dateline() -> None:
    lon = np.array([[0.0, 120.0, 240.0, 358.0]])
    lat = np.zeros((1, 4))
    assert g.nearest_cell(lon, lat, (-1.5, 0.0)) == (0, 3)


# --- all rules -----------------------------------------------------------------------------------------------------


def test_apply_rules_report_and_land_depth() -> None:
    ocean = grid(
        "###########",
        "#~~~~~~~#~#",  # (5, 9): a closed sea
        "#~~#~~~~###",  # (4, 3): an isolated island
        "#~~~~~~~###",
        "#~~~~~~~###",
        "####~######",  # (1, 4): an inlet
        "###########",
    )
    depth = depth_of(ocean)
    report = g.apply_rules(ocean, depth, np.ones(ocean.shape), 30.0, g.T_PIVOT)
    assert report.opened_corners == []
    assert report.closed_seas == [1]
    assert report.removed_inlets == 1
    assert report.removed_islands == [(4, 3)]
    assert (depth[~ocean] == 0).all() and (depth[ocean] > 0).all()
