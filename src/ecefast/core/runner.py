"""Run the pipeline of a time period from a configuration file: ``ecefast <period> run`` and
``ecefast <component> run --period <period>``.
"""

import logging
import os
from datetime import datetime

from .cdo import cdo_version
from .config import load_config, override_steps
from .provenance import write_provenance
from .steps import ComponentStep, PipelineError, run_pipeline
from .workspace import Context

logger = logging.getLogger(__name__)


def component_steps(
    steps: list[type[ComponentStep]], component: str, select: list[str] | None = None, period: str = "this period"
) -> list[str]:
    """Names of the steps of ``component`` in a pipeline, restricted to ``select`` if given.

    Raises
    ------
    PipelineError
        If the pipeline has no step for the component.
    """
    names = [s.name for s in steps if s.component == component and (select is None or s.name in select)]
    if not names:
        raise PipelineError(f"{period} has no '{component}' step (choose another period with --period)")
    return names


def run_period(
    steps: list[type[ComponentStep]],
    config_file: str,
    period: str,
    select: list[str] | None = None,
    component: str | None = None,
    substeps: dict[str, list[str]] | None = None,
    dry_run: bool = False,
    overwrite: bool = False,
) -> tuple[list[str], Context]:
    """Read the configuration, check the inputs of ``period`` and run its pipeline.

    Unless it is a dry run, ``provenance.yml`` is written into the period's ``output``.

    Parameters
    ----------
    steps : list of ComponentStep subclasses
        The pipeline of the period, in order.
    config_file : str
        Configuration file (schema 2) with a section for ``period``.
    period : str
        ``present`` or ``eocene``.
    select : list of str, optional
        Names of the steps to run; they run in pipeline order. ``None`` runs all of them.
    component : str, optional
        Run only the steps of this component (``ecefast <component> run``).
    substeps : dict, optional
        Per component, the steps of that component's section to run instead of its configured ``steps``
        (``--oifs a,b``, ``--nemo c,d``).
    dry_run : bool
        Only check the inputs and log the plan; write nothing.
    overwrite : bool
        Let the steps replace existing outputs.

    Returns
    -------
    list of str, Context
        Names of the steps that ran (or would run, for a dry run), and the run context.

    Raises
    ------
    ConfigError
        If the configuration is invalid, has no section for ``period``, or a read-only directory of the period is
        missing.
    PipelineError
        If the pipeline cannot start, or a step did not write a declared output.
    """
    start = datetime.now().astimezone()
    cdo = cdo_version()
    logger.info("CDO version: %s", cdo)
    config = load_config(config_file)
    section = config.period(period)
    for name, names in (substeps or {}).items():
        override_steps(config, period, name, names)
    config.check_inputs(period)
    if component is not None:
        select = component_steps(steps, component, select, period=f"Period '{period}'")
    elif select is None:
        # the whole period: the steps of the components it has a section for (e.g. no present.oifs on a laptop)
        missing = [s.name for s in steps if s.component and getattr(section, s.component, True) is None]
        if missing:
            logger.info("Skipping %s: no section for it in '%s'", ", ".join(missing), period)
        select = [s.name for s in steps if s.name not in missing]
    ctx = Context(config, period, overwrite=overwrite)
    names = run_pipeline(steps, ctx, select=select, dry_run=dry_run)
    if not dry_run:
        os.makedirs(section.output, exist_ok=True)
        path = write_provenance(section.output, names, config_file, cdo, start, datetime.now().astimezone())
        logger.info("Provenance written to %s", path)
    return names, ctx
