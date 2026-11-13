"""Where the initial state lives in an EC-Earth4 input tree (ECE4-DATA 4.1.10 and later).

ECE4-DATA keeps the initial state of every component under ``initial_state/``. The older paths
(``oifs/<grid>/<startdate>``, ``oasis/<grid>/rstos.nc``, ``nemo/initial/woa13-levitus-L*.nc``) are relative links
into it, kept for EC-Earth. ``stage`` keeps those links in the output tree, but the steps read and write only the
``initial_state/`` paths built here: this module is the one place to change if they become configurable.

Every function takes the root of a tree (``input``, ``output``) and returns a path under it. The root and the
names may be path templates (``"{input}"``, ``"{grids.oifs.name}"``), so step classes build their ``reads`` and
``writes`` with the same functions.
"""

import os

INITIAL_STATE = "initial_state"
# restart set of the OASIS restarts in ECE4-DATA: initial_state/oasis/<grid>/default/
OASIS_RESTART_SET = "default"


def oifs_initial_dir(root: str, grid: str, startdate: str) -> str:
    """Folder of the OIFS initial state (``ICMGGECE4INIT``, ``ICMGGECE4INIUA``, ``ICMSHECE4INIT``).

    Parameters
    ----------
    root : str
        Root of the tree.
    grid : str
        OIFS grid, e.g. ``TL63L31``.
    startdate : str
        Initial-state date, e.g. ``19900101``.

    Returns
    -------
    str
        ``<root>/initial_state/oifs/<grid>/<startdate>``.
    """
    return os.path.join(root, INITIAL_STATE, "oifs", grid, startdate)


def oasis_restart_dir(root: str, nemo_grid: str) -> str:
    """Folder of the OASIS restart ``rstos.nc`` of a NEMO grid.

    Parameters
    ----------
    root : str
        Root of the tree.
    nemo_grid : str
        NEMO grid, e.g. ``PALEORCA2``.

    Returns
    -------
    str
        ``<root>/initial_state/oasis/<nemo_grid>/default``.
    """
    return os.path.join(root, INITIAL_STATE, "oasis", nemo_grid, OASIS_RESTART_SET)


def nemo_ts_state_dir(root: str) -> str:
    """Folder of the NEMO temperature and salinity initial states (``woa13-levitus-L31.nc`` and its variants).

    Parameters
    ----------
    root : str
        Root of the tree.

    Returns
    -------
    str
        ``<root>/initial_state/nemo/ts_state``.
    """
    return os.path.join(root, INITIAL_STATE, "nemo", "ts_state")


def initial_state_copies(oifs_grid: str, nemo_grid: str) -> list[str]:
    """The folders of ``initial_state/`` that ``stage`` copies, relative to the tree: those of the grids in use.

    Parameters
    ----------
    oifs_grid, nemo_grid : str
        Grids of the run (``grids.oifs.name``, ``grids.nemo.name``).

    Returns
    -------
    list of str
        ``initial_state/oifs/<oifs_grid>``, ``initial_state/oasis/<nemo_grid>``, ``initial_state/nemo/ts_state``.
    """
    return [
        os.path.join(INITIAL_STATE, "oifs", oifs_grid),
        os.path.join(INITIAL_STATE, "oasis", nemo_grid),
        nemo_ts_state_dir(""),
    ]
