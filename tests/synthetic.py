"""Small synthetic inputs shared by several tests (``tests/`` is on ``sys.path``: ``pythonpath`` in ``pyproject.toml``)."""

from pathlib import Path

import numpy as np
import xarray as xr

NY, NX = 6, 8


def write_domain_inputs(coords_file: Path, bathy_file: Path) -> None:
    """Write PALEORCA2-like coordinates without halo and a bathymetry, as the domain pipeline makes them.

    The bathymetry has a land strip (two columns), a 50 m point (five T levels) and a missing value (land).
    """
    coords_file.parent.mkdir(parents=True, exist_ok=True)
    bathy_file.parent.mkdir(parents=True, exist_ok=True)
    lon = np.linspace(0, 315, NX)[None].repeat(NY, axis=0)
    lat = np.linspace(-60, 60, NY)[:, None].repeat(NX, axis=1)
    coords = {}
    for point, shift in zip("tuvf", (0.0, 0.5, 0.0, 0.5)):
        coords[f"glam{point}"] = (("y", "x"), lon + shift)
        coords[f"gphi{point}"] = (("y", "x"), lat + shift)
        coords[f"e1{point}"] = (("y", "x"), np.full((NY, NX), 2.0e5))
        coords[f"e2{point}"] = (("y", "x"), np.full((NY, NX), 2.0e5))
    xr.Dataset(coords).to_netcdf(coords_file)

    depth = np.full((NY, NX), 4000.0)
    depth[:, :2] = 0.0  # a land strip
    depth[2, 4] = 50.0  # shallow point: five T levels
    depth[3, 5] = np.nan  # missing value = land
    xr.Dataset(
        {"bathy_metry": (("time_counter", "y", "x"), depth[None])},
        coords={"lon": (("y", "x"), lon), "lat": (("y", "x"), lat)},
    ).to_netcdf(bathy_file)
