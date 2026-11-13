"""Shared access to the CDO Python bindings.

There is one ``cdo.Cdo`` instance per process, created on first use, so importing a module never needs the
CDO binary. The binary is the one python-cdo finds itself (the ``CDO`` environment variable, else the first
``cdo`` on ``PATH``).
"""

import os
import shutil
from functools import cache

from cdo import Cdo

from .steps import PipelineError


def find_cdo_binary() -> str | None:
    """Return the CDO binary python-cdo will use, or ``None`` if there is none.

    Same lookup as python-cdo: the ``CDO`` environment variable if it names a file, else ``cdo`` on ``PATH``.
    """
    from_env = os.environ.get("CDO")
    if from_env and os.path.isfile(from_env):
        return from_env
    return shutil.which("cdo")


@cache
def get_cdo() -> Cdo:
    """Return the shared ``Cdo`` instance, creating it on the first call.

    Returns
    -------
    cdo.Cdo
        The same instance on every call.

    Raises
    ------
    PipelineError
        If no CDO binary is found, with a hint on how to get one.
    """
    if find_cdo_binary() is None:
        raise PipelineError(
            "CDO not found: no 'cdo' on PATH and no CDO environment variable pointing to it. "
            "Load it first: 'module load cdo' on an HPC system (e.g. ECMWF Atos), "
            "'conda install -c conda-forge cdo' or 'brew install cdo' elsewhere."
        )
    return Cdo()


def cdo_version() -> str:
    """Return the version string of the CDO binary used by :func:`get_cdo`, e.g. ``"2.6.4"``."""
    return get_cdo().version()
