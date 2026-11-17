"""Configuration management for NEMO workflow."""

from .loader import (
    load_bathymetry_corrections,
    get_corrections_for_grid,
)

__all__ = [
    "load_bathymetry_corrections",
    "get_corrections_for_grid",
]
