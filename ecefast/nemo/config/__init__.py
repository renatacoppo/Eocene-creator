"""Configuration management for NEMO workflow."""

from .loader import (
    load_hpc_modules,
    get_hpc_modules,
    load_bathymetry_corrections,
    get_corrections_for_grid,
)

__all__ = [
    'load_hpc_modules',
    'get_hpc_modules',
    'load_bathymetry_corrections',
    'get_corrections_for_grid',
]
