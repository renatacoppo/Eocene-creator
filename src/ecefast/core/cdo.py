"""Shared access to the CDO Python bindings.

There is one ``cdo.Cdo`` instance per process, created on first use, so importing a module never needs the
CDO binary. The binary is the one python-cdo finds itself (the ``CDO`` environment variable, else the first
``cdo`` on ``PATH``).
"""

import os
import shutil
from functools import cache

from cdo import Cdo

from .config import DATA_VERSIONS
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


def check_cdo_version(found: str, data_version: str) -> None:
    """Stop if the CDO version ``found`` is not the series that ``data_version`` needs.

    Parameters
    ----------
    found : str
        Version of the CDO binary, e.g. ``"2.5.3"`` (from :func:`cdo_version`).
    data_version : str
        Version of the generated data, a key of ``DATA_VERSIONS`` (the ``data_version`` of the configuration).

    Raises
    ------
    PipelineError
        If the major and minor version of ``found`` differ from the series of ``data_version``, with the reason
        and how to load the right CDO.
    """
    series = DATA_VERSIONS[data_version]
    if found.split(".")[:2] == series.split("."):
        return
    raise PipelineError(
        f"data_version {data_version} needs CDO {series}.x, found CDO {found}. "
        f"The {data_version} data were made with CDO {series}, and another CDO can change them (the land-sea mask "
        "of the NEMO bathymetries depends on how CDO rounds cells with an ocean fraction of exactly 0.5). "
        f"Load CDO {series}.x: its module on an HPC system (see 'module avail cdo'), "
        f"'conda install -c conda-forge \"cdo={series}\"' elsewhere, "
        f"or point the CDO environment variable to a CDO {series} binary. See docs/configuration.rst (data_version)."
    )
