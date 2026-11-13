"""Configuration management for NEMO workflow."""

import logging
import os

from ecefast.core.config import ConfigError, load_yaml

logger = logging.getLogger(__name__)

# Absolute path to config directory
_CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))


def load_bathymetry_corrections():
    """Load bathymetry corrections configuration from YAML.

    Returns:
        dict: Corrections config organized by <source>_to_<target>_<remap> key (e.g. 'eORCA1_to_PALEORCA2_remapnn')
    """
    return load_yaml(os.path.join(_CONFIG_DIR, "bathymetry_corrections.yaml"))


def _convert_cell_indices(y_start, y_end, x_start, x_end):
    """Convert [y_start, y_end, x_start, x_end] YAML format to Python index/slice.

    Returns a tuple (y_idx, x_idx) where each is either an int or slice object.
    Handles both single points and ranges.
    """
    # If y_start == y_end, it's a single point; otherwise it's a range (slice)
    y_idx = y_start if (y_start == y_end) else slice(y_start, y_end + 1)
    x_idx = x_start if (x_start == x_end) else slice(x_start, x_end + 1)

    return (y_idx, x_idx)


def get_corrections_for_grid(source_grid, target_grid, remap_method):
    """Get strait corrections for a specific source grid + target grid + remap combination.

    Returns the corrections in the native Python format (dictionaries of region names
    to lists of (y_idx, x_idx) tuples where idx can be int or slice).

    Args:
        source_grid (str): Source grid of the bathymetry (e.g. 'eORCA1')
        target_grid (str): Target grid name (e.g. 'PALEORCA2')
        remap_method (str): Remap method (e.g. 'remapnn')

    Returns:
        tuple: (open_regions_dict, close_regions_dict)

    Raises:
        ConfigError: If corrections are not defined for this source+target+remap combination
    """
    corrections = load_bathymetry_corrections()
    key = f"{source_grid}_to_{target_grid}_{remap_method}"

    if key not in corrections:
        available = ", ".join(corrections.keys())
        raise ConfigError(
            f"No strait corrections defined for '{key}' "
            f"(source grid '{source_grid}', target grid '{target_grid}', remap '{remap_method}'), so the "
            f"present-day bathymetry cannot be built from this source grid. Available: {available}. "
            f"Define corrections in {os.path.basename(_CONFIG_DIR)}/bathymetry_corrections.yaml"
        )

    config = corrections[key]

    # Convert open_regions from YAML format to native Python dicts
    open_regions = {}
    for entry in config.get("open_regions", []):
        region_name = entry["region"]
        cells = entry["cells"]
        open_regions[region_name] = [tuple(cell) for cell in cells]

    # Convert close_regions from YAML format to native Python dicts
    close_regions = {}
    for entry in config.get("close_regions", []):
        region_name = entry["region"]
        cells = entry["cells"]
        # Convert [y_start, y_end, x_start, x_end] to (y_idx, x_idx) tuples
        converted_cells = []
        for cell in cells:
            y_idx, x_idx = _convert_cell_indices(cell[0], cell[1], cell[2], cell[3])
            converted_cells.append((y_idx, x_idx))
        close_regions[region_name] = converted_cells

    logger.debug(
        "Loaded strait corrections for %s (open=%d regions, close=%d regions)",
        key,
        len(open_regions),
        len(close_regions),
    )

    return open_regions, close_regions
