"""Bathymetry processors of the NEMO domain pipeline.

``PROCESSORS`` maps the ``processor`` name used in ``nemo.domain.bathymetries`` to the class, for the generic
processors. Paleo processors live under ``ecefast.paleo`` and export their own mapping (e.g.
``ecefast.paleo.eocene.bathymetry.EOCENE_PROCESSORS``); the caller merges them and passes the result to
:class:`ecefast.components.nemo.domain.pipeline.NEMOWorkflow`.
"""

from .base import BathymetryProcessor
from .present_day import PresentDayBathymetry

PROCESSORS: dict[str, type[BathymetryProcessor]] = {"PresentDayBathymetry": PresentDayBathymetry}
