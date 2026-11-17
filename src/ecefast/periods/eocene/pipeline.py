"""The Eocene pipeline: the ordered list of steps, and :func:`run`, used by ``ecefast eocene run`` and by
``ecefast <component> run --period eocene``."""

import logging
import os

from ecefast.core.config import load_config
from ecefast.core.runner import run_period
from ecefast.core.steps import ComponentStep
from ecefast.core.workspace import Context, Stage
from ecefast.periods.eocene.bathymetry import EoceneBathymetry
from ecefast.periods.eocene.nemo.domain import EoceneDomain
from ecefast.periods.eocene.nemo.eoceneNEMO import EoceneNEMO
from ecefast.periods.eocene.oasis.eoceneOASIS import EoceneOASIS
from ecefast.periods.eocene.oifs.eoceneOIFS import EoceneOIFS
from ecefast.periods.eocene.rnfm.eoceneRNFM import EoceneRNFM
from ecefast.periods.eocene.verify import verify
from ecefast.periods.plots import domain_file, plot_period

logger = logging.getLogger(__name__)

PERIOD = "eocene"
PIPELINE: list[type[ComponentStep]] = [Stage, EoceneDomain, EoceneOASIS, EoceneOIFS, EoceneNEMO, EoceneRNFM]


def run(
    config_file: str,
    select: list[str] | None = None,
    component: str | None = None,
    substeps: dict[str, list[str]] | None = None,
    dry_run: bool = False,
    overwrite: bool = False,
) -> list[str]:
    """Run the Eocene pipeline from a configuration file.

    Checks all inputs first (see :func:`ecefast.core.steps.run_pipeline`), runs the selected steps and, unless it
    is a dry run, writes ``provenance.yml`` into ``eocene.output`` and checks the outputs of the steps that ran
    (:func:`ecefast.periods.eocene.verify.verify`).

    Parameters
    ----------
    config_file : str
        Configuration file (schema 2) with an ``eocene`` section.
    select : list of str, optional
        Names of the steps to run, in any order; they run in pipeline order. ``None`` runs all of them.
    component : str, optional
        Run only the steps of this component (``ecefast <component> run --period eocene``).
    substeps : dict, optional
        Per component, the steps to run instead of the configured ones (``{"nemo": [...]}``).
    dry_run : bool
        Only check the inputs and log the plan; write nothing.
    overwrite : bool
        Allow ``stage`` to replace an output directory that is not empty.

    Returns
    -------
    list of str
        Names of the steps that ran (or would run, for a dry run).

    Raises
    ------
    ConfigError
        If the configuration is invalid or has no ``eocene`` section.
    PipelineError
        If the pipeline cannot start, a step did not write a declared output, or the outputs fail the checks.
    """
    names, ctx = run_period(PIPELINE, config_file, PERIOD, select, component, substeps, dry_run, overwrite)
    if not dry_run:
        verify([s for s in PIPELINE if s.name in names], ctx)
    return names


def plot(config_file: str, out_dir: str, reference: str | None = None, groups: list[str] | None = None) -> dict:
    """Draw the plots of the Eocene output (``ecefast eocene plot``), see :mod:`ecefast.periods.plots`.

    The Eocene NEMO domain is compared with the domain of the same grid in the reference tree (by default the
    present-day ``eocene.input``) and with the Herold et al. (2014) bathymetry it is made from
    (``EoceneBathymetry.source_file``).

    Parameters
    ----------
    config_file : str
        Configuration file (schema 2) with an ``eocene`` section.
    out_dir : str
        Plot directory, outside the EC-Earth trees.
    reference : str, optional
        Root of the reference tree; default ``eocene.input``.
    groups : list of str, optional
        Groups to draw (``nemo``, ``oifs``, ``coupling``); default all.

    Returns
    -------
    dict
        The content of ``summary.yml``.

    Raises
    ------
    ConfigError
        If the configuration is invalid or has no ``eocene`` section.
    PipelineError
        If the plot directory is inside an EC-Earth tree or an input file is missing.
    """
    ctx = Context(load_config(config_file), PERIOD)
    reference = reference or ctx.section.input
    domains = [domain_file(reference, ctx.config.grids.nemo.name)]
    source = (EoceneBathymetry, ctx.expand(EoceneBathymetry.source_file))
    return plot_period(ctx, os.path.abspath(out_dir), os.path.abspath(reference), domains, source, groups)
