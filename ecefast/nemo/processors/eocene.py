"""
EoceneBathymetry: processor for the Herold et al. (2014) Eocene paleotopography.

Remaps a negative-elevation field (ocean where value < 0) to PALEORCA2 using
bilinear interpolation.  No strait corrections are applied.
"""

from .base import BathymetryProcessor


class EoceneBathymetry(BathymetryProcessor):
    """
    Processor for the Herold et al. Eocene paleotopography.

    Source: herold_etal_stddev_subgrid_etopo1_to_eocene_1x1.nc, variable
            paleotopo (negative-elevation convention: ocean < 0, land ≥ 0).
    Remap:  bilinear (remapbil) to PALEORCA2 T-grid.
    Post:   none (no strait corrections needed for a paleo configuration).

    YAML instance fields
    --------------------
    source_file : path to Herold et al. NetCDF file
    """

    variable      = 'paleotopo'
    rename_to     = 'bathy_metry'
    mask_type     = 'negative_elevation'
    remap_method  = 'remapbil'
    output_prefix = 'HEROLD'
    # setgrid is None — source file already carries a proper grid description
