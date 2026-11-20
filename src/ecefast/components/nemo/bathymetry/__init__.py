"""Bathymetry processors of the NEMO domain pipeline: the base class.

Each time period has its own subclass (``ecefast.periods.present.bathymetry.PresentDayBathymetry``,
``ecefast.periods.eocene.bathymetry.EoceneBathymetry``, and their v2 versions for ``data_version: v2``) and passes
it to :class:`ecefast.components.nemo.domain.pipeline.NEMOWorkflow`. The geography rules of data version v2 are in
:mod:`.geography`.
"""

from .base import BathymetryProcessor

__all__ = ["BathymetryProcessor"]
