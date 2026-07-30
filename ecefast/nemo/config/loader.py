"""Configuration management for NEMO workflow."""

import logging
import os
import yaml

logger = logging.getLogger("nemo.config")

# Absolute path to config directory
_CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))


def load_hpc_modules():
    """Load HPC module configuration from YAML.
    
    Returns:
        dict: HPC environment configs organized by environment name
    """
    modules_file = os.path.join(_CONFIG_DIR, 'hpc_modules.yaml')
    with open(modules_file, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def get_hpc_modules(environment='default'):
    """Get HPC modules for a specific environment.
    
    Args:
        environment (str): HPC environment name (e.g. 'atos', 'default')
    
    Returns:
        list: Module names to load
    
    Raises:
        ValueError: If environment not defined in config
    """
    modules_cfg = load_hpc_modules()
    
    if environment not in modules_cfg:
        available = ', '.join(modules_cfg.keys())
        raise ValueError(
            f"HPC environment '{environment}' not found. "
            f"Available: {available}. "
            f"Define it in {os.path.basename(_CONFIG_DIR)}/hpc_modules.yaml"
        )
    
    env_cfg = modules_cfg[environment]
    modules = env_cfg.get('modules', []) if isinstance(env_cfg, dict) else env_cfg
    
    logger.debug("Loaded HPC modules for environment '%s': %d modules", 
                 environment, len(modules))
    
    return modules


def load_bathymetry_corrections():
    """Load bathymetry corrections configuration from YAML.
    
    Returns:
        dict: Corrections config organized by grid_remap_key (e.g. 'PALEORCA2_remapnn')
    """
    corrections_file = os.path.join(_CONFIG_DIR, 'bathymetry_corrections.yaml')
    with open(corrections_file, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def _convert_cell_indices(y_start, y_end, x_start, x_end):
    """Convert [y_start, y_end, x_start, x_end] YAML format to Python index/slice.
    
    Returns a tuple (y_idx, x_idx) where each is either an int or slice object.
    Handles both single points and ranges.
    """
    # If y_start == y_end, it's a single point; otherwise it's a range (slice)
    y_idx = y_start if (y_start == y_end) else slice(y_start, y_end + 1)
    x_idx = x_start if (x_start == x_end) else slice(x_start, x_end + 1)
    
    return (y_idx, x_idx)


def get_corrections_for_grid(target_grid, remap_method):
    """Get strait corrections for a specific grid+remap combination.
    
    Returns the corrections in the native Python format (dictionaries of region names
    to lists of (y_idx, x_idx) tuples where idx can be int or slice).
    
    Args:
        target_grid (str): Target grid name (e.g. 'PALEORCA2')
        remap_method (str): Remap method (e.g. 'remapnn')
    
    Returns:
        tuple: (open_regions_dict, close_regions_dict)
    
    Raises:
        ValueError: If corrections not defined for this grid+remap combination
    """
    corrections = load_bathymetry_corrections()
    key = f"{target_grid}_{remap_method}"
    
    if key not in corrections:
        available = ', '.join(corrections.keys())
        raise ValueError(
            f"No strait corrections defined for '{key}' "
            f"(grid='{target_grid}', remap='{remap_method}'). "
            f"Available: {available}. "
            f"Define corrections in {os.path.basename(_CONFIG_DIR)}/bathymetry_corrections.yaml"
        )
    
    config = corrections[key]
    
    # Convert open_regions from YAML format to native Python dicts
    open_regions = {}
    for entry in config.get('open_regions', []):
        region_name = entry['region']
        cells = entry['cells']
        open_regions[region_name] = [tuple(cell) for cell in cells]
    
    # Convert close_regions from YAML format to native Python dicts
    close_regions = {}
    for entry in config.get('close_regions', []):
        region_name = entry['region']
        cells = entry['cells']
        # Convert [y_start, y_end, x_start, x_end] to (y_idx, x_idx) tuples
        converted_cells = []
        for cell in cells:
            y_idx, x_idx = _convert_cell_indices(cell[0], cell[1], cell[2], cell[3])
            converted_cells.append((y_idx, x_idx))
        close_regions[region_name] = converted_cells
    
    logger.debug("Loaded strait corrections for %s (open=%d regions, close=%d regions)", 
                 key, len(open_regions), len(close_regions))
    
    return open_regions, close_regions

