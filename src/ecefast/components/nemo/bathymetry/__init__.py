"""Bathymetry processors of the NEMO domain pipeline: the base class.

Each time period has its own subclass (``ecefast.periods.present.bathymetry.PresentDayBathymetry``,
``ecefast.periods.eocene.bathymetry.EoceneBathymetry``) and passes it to
:class:`ecefast.components.nemo.domain.pipeline.NEMOWorkflow`.
"""

from .base import BathymetryProcessor

__all__ = ["BathymetryProcessor"]
