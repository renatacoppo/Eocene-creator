"""Cell corners of an OIFS reduced Gaussian grid, for conservative remapping (``cdo remapcon``).

The CDO descriptions of ``grids/T<kind><N>.txt`` give the cell centres only; ``remapcon`` needs the corners.
They are built from the reduced points of an ``ICMGGECE4INIT`` file on that grid and the latitudes of the
matching regular Gaussian grid. Based on the original script of Florian Ziemen (Paolo Davini, CNR-ISAC, Apr 2024).
"""

import logging
import os

import netCDF4 as nc
import numpy as np

from ecefast.core.cdo import get_cdo
from ecefast.core.grib import spectral2gaussian
from ecefast.core.io import atomic_write

logger = logging.getLogger(__name__)

# land-sea mask, read only for the grid (any field of ICMGGECE4INIT would do); written to the masked grid
MASK_VARIABLE = "var172"


def reduced_grid_corners(
    lat: np.ndarray, reduced_points: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Cell centres and corners of a reduced Gaussian grid, in degrees.

    Corners are assumed to lie at the midpoints between latitude bands and between the points of a band.

    Parameters
    ----------
    lat : numpy.ndarray
        Latitudes of the bands, north to south.
    reduced_points : numpy.ndarray
        Number of points of each band.

    Returns
    -------
    lons, lats : numpy.ndarray
        Cell centres, shape ``(sum(reduced_points),)``; longitudes in (-180, 180].
    corners_lon, corners_lat : numpy.ndarray
        Cell corners, shape ``(sum(reduced_points), 4)``.

    Raises
    ------
    ValueError
        If ``lat`` and ``reduced_points`` have a different length.
    """
    lat = np.asarray(lat, dtype="f8")
    if lat.shape[0] != len(reduced_points):
        raise ValueError("Number of latitudes does not match number of reduced points")
    total_points = int(np.sum(reduced_points))

    lats = np.zeros(total_points)
    lons = np.zeros(total_points)
    lons_left = np.zeros(total_points)
    lons_right = np.zeros(total_points)
    lats_upper = np.zeros(total_points)
    lats_lower = np.zeros(total_points)

    # the hypothesis is that the latitudinal bands are equally spaced, so that corners lie on the midpoints
    lat_upper = lat.copy()
    lat_upper[:-1] = lat_upper[:-1] + 0.5 * (lat_upper[:-1] - lat_upper[1:])
    lat_upper[-1] = -lat_upper[1]
    lat_lower = lat.copy()
    lat_lower[:-1] = lat_upper[1:]
    lat_lower[-1] = -lat_upper[0]

    covered = 0
    # similar assumption is done for the longitudes
    for j, num_points in enumerate(reduced_points):
        lats[covered : covered + num_points] = lat[j]
        lons[covered : covered + num_points] = np.arange(num_points) / num_points * 360
        lons_left[covered : covered + num_points] = (np.arange(num_points) - 0.5) / num_points * 360
        lons_right[covered : covered + num_points] = (np.arange(num_points) + 0.5) / num_points * 360
        lats_upper[covered : covered + num_points] = lat_upper[j]
        lats_lower[covered : covered + num_points] = lat_lower[j]
        covered += num_points

    for x in [lons, lons_left, lons_right]:
        x[x > 180] = x[x > 180] - 360.0

    corners_lat = np.array([lats_upper, lats_upper, lats_lower, lats_lower]).transpose()
    corners_lon = np.array([lons_left, lons_right, lons_right, lons_left]).transpose()
    return lons, lats, corners_lon, corners_lat


def write_corner_grid(
    outfile: str,
    lons: np.ndarray,
    lats: np.ndarray,
    corners_lon: np.ndarray,
    corners_lat: np.ndarray,
    mask: np.ndarray | None = None,
) -> None:
    """Write a grid with cell corners that CDO reads (``clon``, ``clat`` and their bounds, in radians).

    Parameters
    ----------
    outfile : str
        NetCDF file to write.
    lons, lats, corners_lon, corners_lat : numpy.ndarray
        As returned by :func:`reduced_grid_corners`, in degrees.
    mask : numpy.ndarray or None
        Land-sea mask, written as ``lsm``. Without it, a placeholder field ``lml`` is written, which CDO needs to
        see the grid.
    """
    with atomic_write(outfile) as tmp:
        ds = nc.Dataset(tmp, "w", format="NETCDF4")
        ds.createDimension("rgrid", len(lons))
        ds.createDimension("nv", 4)
        clon = ds.createVariable("clon", "f8", ("rgrid",))
        clat = ds.createVariable("clat", "f8", ("rgrid",))
        field = ds.createVariable("lml" if mask is None else "lsm", "f4", ("rgrid",))
        clon_bnds = ds.createVariable("clon_bnds", "f8", ("rgrid", "nv"))
        clat_bnds = ds.createVariable("clat_bnds", "f8", ("rgrid", "nv"))
        for x in [clon, clat, field]:
            x.units = "radian"
            x.coordinates = "clat clon"
        clon.bounds = "clon_bnds"
        clat.bounds = "clat_bnds"
        clon.standard_name = "longitude"
        clat.standard_name = "latitude"

        clon[:] = lons * np.pi / 180.0
        clat[:] = lats * np.pi / 180.0
        field[:] = clat[:] * clon[:] if mask is None else mask
        clon_bnds[:] = corners_lon * np.pi / 180
        clat_bnds[:] = corners_lat * np.pi / 180
        ds.close()


def read_reduced_grid(
    icmgg_file: str, kind: str, spectral: int, workdir: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Latitudes, reduced points and land-sea mask of the reduced Gaussian grid of an ICMGG file.

    Parameters
    ----------
    icmgg_file : str
        GRIB file on the grid, holding the land-sea mask (e.g. ``ICMGGECE4INIT``).
    kind, spectral : str, int
        Grid kind (``L`` or ``CO``) and spectral truncation, as from :func:`ecefast.core.grib.extract_grid_info`.
    workdir : str
        Directory of the temporary NetCDF files, removed before returning.

    Returns
    -------
    lat, reduced_points, mask : numpy.ndarray
    """
    netcdf_name = os.path.join(workdir, f"T{kind}{spectral}-tmp.nc")
    gaussian_name = os.path.join(workdir, f"T{kind}{spectral}-gaussian.nc")
    get_cdo().selname(MASK_VARIABLE, input=icmgg_file, output=netcdf_name, options="-f nc4")
    # CDO does not recognise the latitudes of the reduced grid in the NetCDF file; those of the regular Gaussian
    # grid with the same number of latitudes are the same
    get_cdo().const(f"1,F{spectral2gaussian(spectral, kind)}", output=gaussian_name, options="-f nc4")
    with nc.Dataset(gaussian_name) as ds:
        lat = ds.variables["lat"][:]
    with nc.Dataset(netcdf_name) as ds:
        reduced_points = ds.variables["reduced_points"][:]
        mask = ds.variables[MASK_VARIABLE][:]
    os.remove(netcdf_name)
    os.remove(gaussian_name)
    return lat, reduced_points, mask


def create_corner_grid(
    icmgg_file: str, kind: str, spectral: int, outfile: str, workdir: str, masked_outfile: str | None = None
) -> None:
    """Write the grid with cell corners (``T<kind><N>_grid.nc``) of the grid of ``icmgg_file``.

    Parameters
    ----------
    icmgg_file : str
        GRIB file on the grid, holding the land-sea mask (e.g. ``ICMGGECE4INIT``).
    kind, spectral : str, int
        Grid kind (``L`` or ``CO``) and spectral truncation.
    outfile : str
        NetCDF file to write.
    workdir : str
        Directory of the temporary files.
    masked_outfile : str or None
        Also write the same grid with the land-sea mask of ``icmgg_file`` (``T<kind><N>_grid_masked.nc``) here.
        The OIFS generator does not need it.
    """
    logger.info("Creating the grid with cell corners %s from %s", outfile, icmgg_file)
    lat, reduced_points, mask = read_reduced_grid(icmgg_file, kind, spectral, workdir)
    grid = reduced_grid_corners(lat, reduced_points)
    write_corner_grid(outfile, *grid)
    if masked_outfile is not None:
        write_corner_grid(masked_outfile, *grid, mask=mask)
