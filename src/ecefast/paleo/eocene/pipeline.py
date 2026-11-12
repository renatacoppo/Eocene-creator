"""The Eocene pipeline: the ordered list of steps, and :func:`run`, used by ``ecefast eocene run``."""

import logging
from datetime import datetime

from ecefast.core.cdo import cdo_version
from ecefast.core.config import load_config
from ecefast.core.provenance import write_provenance
from ecefast.core.steps import ComponentStep, run_pipeline
from ecefast.core.workspace import Context, Stage
from ecefast.paleo.eocene.nemo.domain import EoceneDomain
from ecefast.paleo.eocene.nemo.eoceneNEMO import EoceneNEMO
from ecefast.paleo.eocene.oasis.eoceneOASIS import EoceneOASIS
from ecefast.paleo.eocene.oifs.eoceneOIFS import EoceneOIFS
from ecefast.paleo.eocene.rnfm.eoceneRNFM import EoceneRNFM

logger = logging.getLogger(__name__)

PIPELINE: list[type[ComponentStep]] = [Stage, EoceneDomain, EoceneOASIS, EoceneOIFS, EoceneNEMO, EoceneRNFM]


def run(
    config_file: str,
    select: list[str] | None = None,
    dry_run: bool = False,
    overwrite: bool = False,
) -> list[str]:
    """Run the Eocene pipeline from a configuration file.

    Checks all inputs first (see :func:`ecefast.core.steps.run_pipeline`), runs the selected steps and, unless it
    is a dry run, writes ``provenance.yml`` into the output directory.

    Parameters
    ----------
    config_file : str
        Configuration file (schema 1).
    select : list of str, optional
        Names of the steps to run, in any order; they run in pipeline order. ``None`` runs all of them.
    dry_run : bool
        Only check the inputs and log the plan; write nothing.
    overwrite : bool
        Allow ``stage`` to replace an output directory that is not empty.

    Returns
    -------
    list of str
        Names of the steps that ran (or would run, for a dry run).
    """
    start = datetime.now().astimezone()
    cdo = cdo_version()
    logger.info("CDO version: %s", cdo)
    config = load_config(config_file)
    names = run_pipeline(PIPELINE, Context(config, overwrite=overwrite), select=select, dry_run=dry_run)
    if not dry_run:
        path = write_provenance(config.paths.output, names, config_file, cdo, start, datetime.now().astimezone())
        logger.info("Provenance written to %s", path)
    return names
