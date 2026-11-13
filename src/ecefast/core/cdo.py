"""Shared access to the CDO Python bindings.

There is one ``cdo.Cdo`` instance per process, created on first use, so importing a module never needs the
CDO binary. The binary is the one python-cdo finds itself (the ``CDO`` environment variable, else the first
``cdo`` on ``PATH``).
"""

from functools import cache

from cdo import Cdo


@cache
def get_cdo() -> Cdo:
    """Return the shared ``Cdo`` instance, creating it on the first call.

    Returns
    -------
    cdo.Cdo
        The same instance on every call.
    """
    return Cdo()


def cdo_version() -> str:
    """Return the version string of the CDO binary used by :func:`get_cdo`, e.g. ``"2.6.4"``."""
    return get_cdo().version()
