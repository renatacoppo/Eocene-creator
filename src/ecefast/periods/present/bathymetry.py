"""
PresentDayBathymetry: processor for the present-day bathymetry of a NEMO domain of the input tree.

This processor remaps the bathymetry of ``{input}/nemo/domain/<present.nemo.source_grid>/domain_cfg.nc``
(eORCA1 by default) onto the target grid and then applies hand-coded strait corrections (open/close specific
grid cells) to produce a geographically consistent target grid.

IMPORTANT: the strait corrections assume a specific source grid, target grid and remapping (eORCA1, remapnn to
PALEORCA2). Another combination needs its own corrections (``bathymetry_corrections.yaml``); without them the
step stops.
"""

import glob
import logging
import os

import xarray as xr
import matplotlib.pyplot as plt

from ecefast.components.nemo.bathymetry import BathymetryProcessor
from ecefast.components.nemo.config import get_corrections_for_grid

logger = logging.getLogger(__name__)

# file name of the land-sea mask comparison plot, next to the corrected bathymetry
PLOT_FILE = "landsea_mask_comparison.png"


class PresentDayBathymetry(BathymetryProcessor):
    """
    Processor for the present-day bathymetry of a NEMO domain of the input tree.

    Source: ``{input}/nemo/domain/<source_grid>/domain_cfg.nc``, variable bathy_metry (positive depth convention).
    Remap:  nearest-neighbour (remapnn) to the target T-grid.
    Post:   manual strait corrections + land-sea mask plot, one panel per domain of the input tree.
    """

    name = "present_day"
    source_file = "{input}/nemo/domain/{nemo.source_grid}/domain_cfg.nc"
    has_source_grid = True
    variable = "bathy_metry"
    mask_type = "positive_depth"
    remap_method = "remapnn"

    def __init__(self, cfg, paths, grids, params, cdo):
        super().__init__(cfg, paths, grids, params, cdo)
        # Derive setgrid from source-grid coordinates, honouring the source staggering of the config
        src = grids["source"]
        stagg = grids.get("staggering_source", "T")
        self.setgrid = os.path.join(paths["coordsdir"], src, f"coords_bounds_{stagg}.nc")
        # e.g. eORCA1_T_bathy_metry_remapnn_to_PALEORCA2_T.nc
        self.output_prefix = f"{src}_T"

    def reference_domains(self) -> list[str]:
        """The ``domain_cfg.nc`` of every NEMO domain of the input tree, shown next to the result in the plot."""
        return sorted(glob.glob(os.path.join(self.paths["input"], "nemo", "domain", "*", "domain_cfg.nc")))

    def reads(self) -> list[str]:
        """The base files, plus the domains of the input tree shown in the plot."""
        return super().reads() + [f for f in self.reference_domains() if f not in super().reads()]

    # ------------------------------------------------------------------
    # Postprocessing: strait corrections + plot
    # ------------------------------------------------------------------

    def postprocess(self, remap_file, output_dir):
        corrected = self.corrected_output(remap_file, output_dir)

        logger.debug("Applying strait corrections...")
        xfield = xr.open_dataset(remap_file)
        xfield.load()
        xfield.close()

        # Load strait corrections from config based on source grid, target grid and remap method
        open_regions, close_regions = get_corrections_for_grid(
            self.grids["source"], self.grids["target"], self.remap_method
        )

        # Apply open regions (set to local average depth)
        for region in open_regions.keys():
            xfield = open_region(xfield, region, open_regions)

        # Apply close regions (set to land/0)
        for region in close_regions.keys():
            xfield = close_region(xfield, region, close_regions)

        self._plot(xfield, output_dir)

        xfield.to_netcdf(corrected)
        return corrected

    def _plot(self, xfield, output_dir):
        """Land-sea mask of every domain of the input tree, then of the processed bathymetry.

        A domain without ``bathy_metry`` is left out with a warning (e.g. ``ORCA1`` in ECE4-DATA 4.1.11 names it
        ``bathy_meter``): the plot is a diagnostic, it does not stop the run.
        """
        panels, labels = [], []
        for path in self.reference_domains():
            with xr.open_dataset(path) as domain:
                if "bathy_metry" not in domain:
                    logger.warning("Mask plot: %s has no bathy_metry, left out of the plot", path)
                    continue
                panels.append(xr.where(domain["bathy_metry"] > 0, 1, 0).load())
            labels.append(f"{os.path.basename(os.path.dirname(path))} (input tree)")
        panels.append(xr.where(xfield["bathy_metry"] > 0, 1, 0))
        labels.append(f"{self.grids['target']} (processed)")

        fig, axes = plt.subplots(1, len(panels), figsize=(10 * len(panels), 6))
        if len(panels) == 1:
            axes = [axes]

        for ax, data, title in zip(axes, panels, labels):
            data.plot(ax=ax, cmap="YlGnBu", add_colorbar=True, cbar_kwargs={"label": "Land-Sea Mask", "ticks": [0, 1]})
            ax.set_title(title, fontsize=14, fontweight="bold")
            ax.set_xlabel("Longitude")
            ax.set_ylabel("Latitude")

        plt.tight_layout()
        plot_file = os.path.join(output_dir, PLOT_FILE)
        plt.savefig(plot_file, dpi=150, bbox_inches="tight")
        logger.debug("Plot saved: %s", plot_file)
        plt.close()


# ======================================================================
# Strait correction functions
# ======================================================================
# Note: Region indices are loaded from config/bathymetry_corrections.yaml
# and are specific to the target_grid + remap_method combination.
# ======================================================================


def set_minimum_bathymetry(xfield, min_land=30, min_depth=30):
    """Set all bathymetry values less than min_depth to min_depth."""
    xfield["bathy_metry"] = xfield["bathy_metry"].where(xfield["bathy_metry"] > min_land, 0)
    xfield["bathy_metry"] = xfield["bathy_metry"].where(
        ~((xfield["bathy_metry"] <= min_depth) & (xfield["bathy_metry"] > 0)), min_depth
    )
    return xfield


def average_depth(field, y_slice, x_slice, region_name):
    """Set a single cell to the mean depth of its 3×3 neighbourhood (non-zero only)."""
    data = field["bathy_metry"][:, (y_slice - 1) : (y_slice + 2), (x_slice - 1) : (x_slice + 2)].values
    value = data[data != 0].mean()
    logger.debug("Average depth for %s at (%s, %s): %.1f m", region_name, y_slice, x_slice, value)
    field["bathy_metry"][:, y_slice, x_slice] = value
    return field


def close_region(xfield, region, close_regions):
    """Close a region by setting bathymetry to 0 (land).

    Args:
        xfield: xarray Dataset
        region: Region name (str)
        close_regions: Dict of region_name -> list of (y_idx, x_idx) tuples

    Returns:
        Modified xarray Dataset
    """
    if region not in close_regions:
        raise ValueError(f"Region '{region}' not in close_regions dictionary.")

    for y_idx, x_idx in close_regions[region]:
        xfield["bathy_metry"][:, y_idx, x_idx] = 0
    return xfield


def open_region(xfield, region, open_regions):
    """Open a region by setting cells to the local average depth.

    Args:
        xfield: xarray Dataset
        region: Region name (str)
        open_regions: Dict of region_name -> list of [y, x] cells

    Returns:
        Modified xarray Dataset
    """
    if region not in open_regions:
        raise ValueError(f"Region '{region}' not in open_regions dictionary.")

    for y, x in open_regions[region]:
        xfield = average_depth(xfield, y, x, region)
    return xfield
