"""Checks of a finished Eocene run, called by :func:`ecefast.periods.eocene.pipeline.run` after the steps.

- every declared ``writes`` path of the steps that ran exists;
- no NaN in the data variables of the NetCDF files they declare (EC-Earth reads the raw values, so a NaN is an
  error even where ``_FillValue`` is NaN; values equal to a non-NaN ``_FillValue`` are fine);
- if ``domain`` ran: the vertical grid rule between the present-day and the installed Eocene domain
  (:func:`ecefast.periods.eocene.nemo.domain.check_vertical_grid`).
"""

import logging
import os

import numpy as np
import xarray as xr

from ecefast.core.steps import ComponentStep, PipelineError
from ecefast.core.workspace import Context
from ecefast.periods.eocene.nemo.domain import EoceneDomain, check_vertical_grid

logger = logging.getLogger(__name__)


def missing_outputs(steps: list[type[ComponentStep]], ctx: Context) -> list[str]:
    """Declared ``writes`` paths of ``steps`` that do not exist.

    Parameters
    ----------
    steps : list of ComponentStep subclasses
        The steps that ran.
    ctx : Context
        Run context, to expand the path templates.

    Returns
    -------
    list of str
        The missing paths, in step and declaration order.
    """
    return [p for step in steps for p in (ctx.expand(t) for t in step.writes) if not os.path.exists(p)]


def nan_variables(path: str) -> list[str]:
    """Data variables of a NetCDF file that hold NaN in their raw (not masked) values.

    Parameters
    ----------
    path : str
        NetCDF file.

    Returns
    -------
    list of str
        Names of the floating-point data variables with at least one NaN, in file order.
    """
    with xr.open_dataset(path, mask_and_scale=False, decode_times=False) as ds:
        return [
            name for name, var in ds.data_vars.items() if var.dtype.kind in "fc" and bool(np.isnan(var.values).any())
        ]


def verify(steps: list[type[ComponentStep]], ctx: Context) -> None:
    """Check the outputs of the steps that ran; fail once listing every problem.

    Parameters
    ----------
    steps : list of ComponentStep subclasses
        The steps that ran.
    ctx : Context
        Run context.

    Raises
    ------
    PipelineError
        If a declared output is missing, a declared NetCDF output has NaN in a data variable, or the Eocene
        domain breaks the vertical grid rule.
    """
    problems = [f"missing output {p}" for p in missing_outputs(steps, ctx)]
    for step in steps:
        for path in (ctx.expand(t) for t in step.writes):
            if path.endswith(".nc") and os.path.isfile(path):
                problems += [f"NaN in {name} of {path}" for name in nan_variables(path)]
    if EoceneDomain in steps:
        present_file, eocene_file = ctx.expand(EoceneDomain.reads[0]), ctx.expand(EoceneDomain.writes[0])
        if os.path.isfile(eocene_file):
            with xr.open_dataset(present_file) as present, xr.open_dataset(eocene_file) as eocene:
                try:
                    check_vertical_grid(present, eocene, present_file, eocene_file)
                except ValueError as e:
                    problems.append(str(e))
    if problems:
        raise PipelineError(
            "Verify: the run finished but its output is wrong:\n" + "\n".join(f"  {p}" for p in problems)
        )
    logger.info("Verify: the outputs of %s pass the checks", ", ".join(s.name for s in steps))
