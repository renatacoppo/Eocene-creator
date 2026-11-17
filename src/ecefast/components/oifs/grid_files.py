"""The grid files shipped with the package in ``grids/``, and the functions that made them.

- ``grids/T<kind><N>.txt``: CDO descriptions of the reduced Gaussian grids (``cdo griddes`` of an ECMWF climate
  file on that grid), made by :func:`write_grid_descriptions`;
- ``grids/L<levels>.txt``: hybrid level coefficients (A in Pa, B) in the format of ``cdo remapeta``, made by
  :func:`write_hybrid_coefficients` from the ECMWF model level tables ``grids/L<levels>.csv``.

The pipeline only reads the ``.txt`` files. The two ``write_*`` functions are maintenance tools, run by hand to
add a grid or a vertical resolution (Paolo Davini, CNR-ISAC, Nov 2023).
"""

import logging
import os
import subprocess
from pathlib import Path

import pandas as pd

from ecefast.core.cdo import get_cdo
from ecefast.core.grib import ecmwf_grid, extract_grid_info
from ecefast.core.io import atomic_write

logger = logging.getLogger(__name__)

GRIDS_DIR = Path(__file__).with_name("grids")
# reduced Gaussian grids with a description in grids/
GRID_DESCRIPTIONS = ["TL63", "TL95", "TCO95", "TL159", "TCO199", "TCO319", "TCO399"]
# vertical resolutions with hybrid coefficients in grids/ (L19.csv lacks the row n=0 and cannot be converted)
HYBRID_LEVELS = [31, 91]
# file of the ECMWF climate folder (climate.v015/<N><grid>/) whose grid is described
CLIMATE_REFERENCE_FILE = "10_bats_glcc.grb"


def grid_description(target_spectral: str) -> Path:
    """CDO description of a reduced Gaussian grid, e.g. ``grids/TL63.txt`` for ``TL63``."""
    return GRIDS_DIR / f"{target_spectral}.txt"


def hybrid_coefficients(levels: int | str) -> Path:
    """Hybrid level coefficients of a vertical resolution, e.g. ``grids/L31.txt`` for 31 levels."""
    return GRIDS_DIR / f"L{levels}.txt"


def write_grid_descriptions(climate_dir: str, out_dir: str | Path, grids: list[str] = GRID_DESCRIPTIONS) -> list[Path]:
    """Write the CDO description ``<out_dir>/<grid>.txt`` of each reduced Gaussian grid.

    Parameters
    ----------
    climate_dir : str
        ECMWF climate files folder (``climate.v015``), holding ``<N><grid>/10_bats_glcc.grb``.
    out_dir : str or Path
        Folder of the descriptions; :data:`GRIDS_DIR` to update the shipped ones.
    grids : list of str
        Grid names like ``TL63`` or ``TCO199``.

    Returns
    -------
    list of Path
        The files written.
    """
    # the binary is called directly: python-cdo strips every output line, which would change the indentation
    # of the shipped descriptions
    binary = get_cdo().CDO
    written = []
    for grid in grids:
        grid_type, truncation, _ = extract_grid_info(grid.upper() + "L31")
        source = os.path.join(climate_dir, str(truncation) + ecmwf_grid(grid_type), CLIMATE_REFERENCE_FILE)
        target = Path(out_dir) / f"{grid.upper()}.txt"
        logger.info("Describing the grid %s from %s", grid, source)
        with atomic_write(target) as tmp, open(tmp, "w", encoding="utf8") as out:
            subprocess.run([binary, "griddes", source], stdout=out, check=True)
        written.append(target)
    return written


def write_hybrid_coefficients(
    out_dir: str | Path, levels: list[int] = HYBRID_LEVELS, csv_dir: str | Path = GRIDS_DIR
) -> list[Path]:
    """Convert the ECMWF model level tables ``L<levels>.csv`` to ``cdo remapeta`` files ``L<levels>.txt``.

    Each line of the output is ``<n>\\t<a [Pa]>\\t<b>`` for the half levels ``n = 0 ... levels``.

    Parameters
    ----------
    out_dir : str or Path
        Folder of the ``.txt`` files; :data:`GRIDS_DIR` to update the shipped ones.
    levels : list of int
        Vertical resolutions to convert.
    csv_dir : str or Path
        Folder of the ECMWF tables, with columns ``n``, ``a [Pa]`` and ``b``.

    Returns
    -------
    list of Path
        The files written.

    Raises
    ------
    ValueError
        If a table does not hold the half levels ``0 ... levels`` in order.
    """
    written = []
    for nlev in levels:
        source = Path(csv_dir) / f"L{nlev}.csv"
        table = pd.read_csv(source)
        if table["n"].tolist() != list(range(nlev + 1)):
            raise ValueError(f"{source}: column 'n' must hold the half levels 0 ... {nlev} in order")
        content = "".join(f"{i}\t{a:.17f}\t{b:.17f}\n" for i, (a, b) in enumerate(zip(table["a [Pa]"], table["b"])))
        target = Path(out_dir) / f"L{nlev}.txt"
        with atomic_write(target) as tmp:
            Path(tmp).write_text(content, encoding="utf8")
        logger.info("Wrote the hybrid coefficients %s", target)
        written.append(target)
    return written
