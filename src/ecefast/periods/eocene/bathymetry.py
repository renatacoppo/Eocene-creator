"""
EoceneBathymetry: processor for the Herold et al. (2014) Eocene paleotopography.

Remaps a negative-elevation field (ocean where value < 0) to PALEORCA2 using
bilinear interpolation.  No strait corrections are applied.
"""

from ecefast.components.nemo.bathymetry import BathymetryProcessor


class EoceneBathymetry(BathymetryProcessor):
    """Processor for the Herold et al. (2014) Eocene paleotopography.

    - Source: ``{herold}/herold_etal_stddev_subgrid_etopo1_to_eocene_1x1.nc``, variable ``paleotopo``
      (negative-elevation convention: ocean < 0, land >= 0).
    - Remap: bilinear (``remapbil``) to the target T-grid.
    - Post: none (no strait corrections for a paleo geography).
    """

    name = "eocene"
    source_file = "{herold}/herold_etal_stddev_subgrid_etopo1_to_eocene_1x1.nc"
    variable = "paleotopo"
    rename_to = "bathy_metry"
    mask_type = "negative_elevation"
    remap_method = "remapbil"
    output_prefix = "HEROLD"
    # Global subbasin mask only: the present-day basin polygons do not fit Eocene geography (unassigned NE Pacific,
    # Pacific west of South America labelled Atlantic, cuts through open water in the Tethys and north of
    # Australia). Assessment and options: notebooks/analysis/eocene-subbasins.ipynb, PR #39, issue #16.
    regional_subbasins = False
    # setgrid is None — source file already carries a proper grid description
