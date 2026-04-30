"""
PresentDayBathymetry: processor for the eORCA1 present-day bathymetry.

This processor remaps the present-day eORCA1 bathymetry onto PALEORCA2 and then
applies hand-coded strait corrections (open/close specific grid cells) to produce
a geographically consistent target grid.

IMPORTANT: the strait corrections assume a specific remapping (remapnn to PALEORCA2).
If the remap method or target grid changes, the cell indices will need to be revised.
"""

import logging
import os

import xarray as xr
import matplotlib.pyplot as plt

from .base import BathymetryProcessor

logger = logging.getLogger("nemo.processors.present_day")


class PresentDayBathymetry(BathymetryProcessor):
    """
    Processor for the eORCA1 present-day bathymetry.

    Source: NEMO domain_cfg.nc, variable bathy_metry (positive depth convention).
    Remap:  nearest-neighbour (remapnn) to PALEORCA2 T-grid.
    Post:   manual strait corrections + optional land-sea mask plot.

    YAML instance fields
    --------------------
    source_file : path to eORCA1 domain_cfg.nc
    orca2_file  : (optional) path to ORCA2 domain_cfg.nc — enables comparison plot
    orca1_file  : (optional) path to eORCA1 domain_cfg.nc for plot comparison
    """

    variable      = 'bathy_metry'
    mask_type     = 'positive_depth'
    remap_method  = 'remapnn'
    output_prefix = 'eORCA1_T'

    def __init__(self, cfg, paths, grids, params, cdo):
        super().__init__(cfg, paths, grids, params, cdo)
        # Derive setgrid from source-grid coordinates (not user-supplied in YAML)
        src = grids['source']
        self.setgrid = os.path.join(paths['coordsdir'], src, 'coords_bounds_T.nc')

    # ------------------------------------------------------------------
    # Postprocessing: strait corrections + optional plot
    # ------------------------------------------------------------------

    def postprocess(self, remap_file, output_dir):
        corrected = self.corrected_output(remap_file, output_dir)

        logger.debug("Applying strait corrections...")
        xfield = xr.open_dataset(remap_file)
        xfield.load()
        xfield.close()

        for region in ['Arctic', 'Baltic', 'Gibraltair', 'RedSea',
                       'Madagascar', 'Italy', 'Japan', 'Bering', 'Indonesia', 'Spain']:
            xfield = open_region(xfield, region)

        for region in ['Arctic', 'Caspian', 'Cuba', 'Britain', 'BlackSea',
                       'Victoria', 'GreatLakes', 'Thailand', 'Barents',
                       'Italy', 'Indonesia']:
            xfield = close_region(xfield, region)

        if self.cfg.get('orca2_file') or self.cfg.get('orca1_file'):
            self._plot(xfield, output_dir)

        xfield.to_netcdf(corrected)
        return corrected

    def _plot(self, xfield, output_dir):
        mask  = xr.where(xfield['bathy_metry'] > 0, 1, 0)

        orca1_mask = None
        orca2_mask = None

        if self.cfg.get('orca1_file'):
            with xr.open_dataset(self.cfg['orca1_file']) as orca1:
                orca1_mask = xr.where(orca1['bathy_metry'] > 0, 1, 0).load()

        if self.cfg.get('orca2_file'):
            with xr.open_dataset(self.cfg['orca2_file']) as orca2:
                orca2_mask = xr.where(orca2['bathy_metry'] > 0, 1, 0).load()

        panels = []
        labels = []
        if orca1_mask is not None:
            panels.append(orca1_mask)
            labels.append('eORCA1 (source)')
        if orca2_mask is not None:
            panels.append(orca2_mask)
            labels.append('ORCA2 (reference)')
        panels.append(mask)
        labels.append('PALEORCA2 (processed)')

        fig, axes = plt.subplots(1, len(panels), figsize=(10 * len(panels), 6))
        if len(panels) == 1:
            axes = [axes]

        for ax, data, title in zip(axes, panels, labels):
            data.plot(ax=ax, cmap='YlGnBu', add_colorbar=True,
                      cbar_kwargs={'label': 'Land-Sea Mask', 'ticks': [0, 1]})
            ax.set_title(title, fontsize=14, fontweight='bold')
            ax.set_xlabel('Longitude')
            ax.set_ylabel('Latitude')

        plt.tight_layout()

        if orca1_mask is not None and orca2_mask is not None:
            fname = 'landsea_mask_comparison_orca1_orca2_paleorca2.png'
        elif orca2_mask is not None:
            fname = 'landsea_mask_comparison_orca2_paleorca2.png'
        elif orca1_mask is not None:
            fname = 'landsea_mask_comparison_orca1_paleorca2.png'
        else:
            fname = 'landsea_mask.png'

        plot_file = os.path.join(output_dir, fname)
        plt.savefig(plot_file, dpi=150, bbox_inches='tight')
        logger.info("Plot saved: %s", plot_file)
        plt.close()


# ======================================================================
# Strait correction functions
# ======================================================================
# Grid indices are for PALEORCA2 with remapnn from eORCA1.
# Order is (y, x) — matches ncview display + 1 in the lat dimension.
# Python slicing: add 1 to the end of each range.
# ======================================================================

def set_minimum_bathymetry(xfield, min_land=30, min_depth=30):
    """Set all bathymetry values less than min_depth to min_depth."""
    xfield['bathy_metry'] = xfield['bathy_metry'].where(
        xfield['bathy_metry'] > min_land, 0)
    xfield['bathy_metry'] = xfield['bathy_metry'].where(
        ~((xfield['bathy_metry'] <= min_depth) & (xfield['bathy_metry'] > 0)), min_depth)
    return xfield


def average_depth(field, y_slice, x_slice, region_name):
    """Set a single cell to the mean depth of its 3×3 neighbourhood (non-zero only)."""
    data = field['bathy_metry'][:, (y_slice-1):(y_slice+2), (x_slice-1):(x_slice+2)].values
    value = data[data != 0].mean()
    logger.debug("Average depth for %s at (%s, %s): %.1f m", region_name, y_slice, x_slice, value)
    field['bathy_metry'][:, y_slice, x_slice] = value
    return field


_CLOSE_REGIONS = {
    'Caspian':    [(slice(131, 140), slice(156, 159))],
    'BlackSea':   [(slice(133, 138), slice(146, 153))],
    'Victoria':   [(slice(98,  101), 149)],
    'GreatLakes': [(slice(132, 141), slice(86,  94))],
    'Arctic':     [(165, slice(151, 153)), (slice(162, 174), slice(64, 78))],
    'Britain':    [(139, 131), (slice(141, 143), slice(128, 131))],
    'Cuba':       [(121, slice(92, 96))],
    'Thailand':   [(slice(104, 116), 2), (slice(104, 112), 3), (slice(88, 90), 5)],
    'Italy':      [(slice(134, 136), 139)],
    'Barents':    [(slice(153, 155), slice(145, 147))],
    'Indonesia':  [(123, 12), (94, 18), (89, 26), (86, slice(10, 13))],
}


def close_region(xfield, region):
    """Close a region by setting bathymetry to 0 (land)."""
    if region not in _CLOSE_REGIONS:
        raise ValueError(f"Region '{region}' not recognised for closing.")
    for y_idx, x_idx in _CLOSE_REGIONS[region]:
        xfield['bathy_metry'][:, y_idx, x_idx] = 0
    return xfield


_OPEN_REGIONS = {
    'Gibraltair': [(129, 132)],
    'RedSea':     [(117, 154), (117, 153)],
    'Italy':      [(133, 140), (130, 139)],
    'Bering':     [(151, 47)],
    'Arctic':     [(166, 60), (173, 143), (173, 144)],
    'Baltic':     [(143, 138), (144, 139)],
    'Japan':      [(129, 16)],
    'Indonesia':  [(115, 12), (101, 11), (102, 11), (105, 15), (106, 15),
                   (94, 16), (86, 15), (81, 41), (96, 7)],
    'Spain':      [(134, 128)],
    'Madagascar': [(81, 154)],
}


def open_region(xfield, region):
    """Open a region by setting cells to the local average depth."""
    if region not in _OPEN_REGIONS:
        raise ValueError(f"Region '{region}' not recognised for opening.")
    for y, x in _OPEN_REGIONS[region]:
        xfield = average_depth(xfield, y, x, region)
    return xfield
