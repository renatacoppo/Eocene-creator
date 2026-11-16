"""Transport sections of the NEMO diagnostic ``diadct``: the input of SECTIONS_DIADCT and a reader of its output.

SECTIONS_DIADCT (NEMO ``tools/SECTIONS_DIADCT``, run by the backends of :mod:`ecefast.tools.ecearth`) turns a list
of sections given in lon/lat into the grid points of each section, and writes them to ``section_ijglobal.diadct``,
a Fortran unformatted sequential file read by NEMO ``diadct.F90``. The indices are 1-based on the global grid of
``domain_cfg.nc`` without halo: the ``section_ijglobal.diadct`` of eORCA1 in ECE4-DATA matches the eORCA1
``domain_cfg.nc`` that way. So the tool is given the grid of the final ``domain_cfg.nc``.

The tool uses only the horizontal grid, not the land-sea mask: a section is the same on every bathymetry of a grid,
and NEMO skips its land points.
"""

import logging
import os
import struct
from pathlib import Path

import netCDF4
import xarray as xr

from ecefast.core.io import atomic_write

logger = logging.getLogger(__name__)

# Variables SECTIONS_DIADCT reads from coordinates.nc (readcoordmesh.f90)
COORDINATE_VARIABLES = ("glamt", "gphit", "glamf", "gphif", "e1t")
# Record layout of section_ijglobal.diadct (writesections.f90 and declarations.f90 of SECTIONS_DIADCT in
# EC-Earth4 NEMO 4.2): one record per field; the section name is CHARACTER(len=60), the end points REAL(8)
SECTION_NAME_LENGTH = 60


def write_sections_coordinates(domain_cfg: str | os.PathLike, output: str | os.PathLike) -> None:
    """Write the ``coordinates.nc`` that SECTIONS_DIADCT reads, from a ``domain_cfg.nc``.

    The tool takes the grid size from the first two dimensions of the file in definition order (``jpi``, then
    ``jpj``), while ``domain_cfg.nc`` defines ``y`` before ``x``: the file is written with netCDF4 to define ``x``
    first. The variables are 2-D ``(y, x)``, float64, without ``time_counter``. It is an intermediate file of the
    tool, not an EC-Earth file.

    Parameters
    ----------
    domain_cfg : str or os.PathLike
        NEMO 4.2 ``domain_cfg.nc`` (variables ``(time_counter, y, x)`` or ``(y, x)``).
    output : str or os.PathLike
        The ``coordinates.nc`` to write (atomically); its directory must exist.

    Raises
    ------
    KeyError
        If ``domain_cfg`` lacks one of :data:`COORDINATE_VARIABLES`.
    """
    with xr.open_dataset(domain_cfg) as ds:
        missing = [name for name in COORDINATE_VARIABLES if name not in ds]
        if missing:
            raise KeyError(f"{domain_cfg}: no {', '.join(missing)}, needed by SECTIONS_DIADCT")
        fields = {name: ds[name].squeeze(drop=True).values for name in COORDINATE_VARIABLES}
    ny, nx = fields["glamt"].shape
    logger.info("Writing SECTIONS_DIADCT coordinates (%d x %d) from %s", nx, ny, domain_cfg)
    with atomic_write(output) as tmp, netCDF4.Dataset(tmp, "w") as nc:
        nc.createDimension("x", nx)  # first: jpi
        nc.createDimension("y", ny)
        for name, values in fields.items():
            nc.createVariable(name, "f8", ("y", "x"))[:] = values
        nc.history = f"Coordinates for SECTIONS_DIADCT from {domain_cfg} (ecefast)"


def _records(data: bytes):
    """Records of a Fortran unformatted sequential file (4-byte little-endian markers)."""
    pos = 0
    while pos < len(data):
        (size,) = struct.unpack("<i", data[pos : pos + 4])
        yield data[pos + 4 : pos + 4 + size]
        pos += size + 8


def read_sections(path: str | os.PathLike) -> list[dict]:
    """Read ``section_ijglobal.diadct``: per section its name, end points and grid points.

    Parameters
    ----------
    path : str or os.PathLike
        File written by SECTIONS_DIADCT. An empty file has no sections.

    Returns
    -------
    list of dict
        Per section, in file order: ``number``, ``name``, ``coordinates`` (lon1, lat1, lon2, lat2 of the list of
        sections), ``points`` (list of 1-based ``(i, j)`` on the grid without halo; empty if the section does not
        cross the grid) and ``directions``.
    """
    records = _records(Path(path).read_bytes())
    sections = []
    for record in records:
        (number,) = struct.unpack("<i", record)
        name = next(records)[:SECTION_NAME_LENGTH].decode().strip()
        for _ in range(3):  # llstrpond, ll_ice_section, ll_date_line
            next(records)
        coordinates = struct.unpack("<4d", next(records))
        for _ in range(7):  # nb_class, zsigi, zsigp, zsal, ztem, zlay, slopeSection
            next(records)
        (npoints,) = struct.unpack("<i", next(records))
        points = [struct.unpack("<2i", next(records)) for _ in range(npoints)]
        directions = list(struct.unpack(f"<{npoints}i", next(records))) if npoints else []
        sections.append(
            {"number": number, "name": name, "coordinates": coordinates, "points": points, "directions": directions}
        )
    return sections
