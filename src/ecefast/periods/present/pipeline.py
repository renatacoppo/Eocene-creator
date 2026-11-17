"""The present-day pipeline: a copy of the input tree, then the OIFS base data and the NEMO domain of the model
grids, used by ``ecefast present run`` and by ``ecefast <component> run`` (``--period present`` is the default).

``stage`` copies the base files of the present-day input tree (``present.input``) into ``present.output``, so the
output is a complete tree the Eocene can start from (``eocene.input: "{present.output}"``). The component steps
write their final files into it, laid out as in ECE4-DATA; intermediate files go to
``<machine.tmpdir>/present/<component>``.
"""

import logging
import os

from ecefast.components.nemo.domain.pipeline import NEMOWorkflow
from ecefast.components.oifs.generator import OIFSData
from ecefast.core.config import load_config
from ecefast.core.runner import run_period
from ecefast.core.steps import ComponentStep
from ecefast.core.workspace import Context, Stage, pause_before_overwrite
from ecefast.periods.plots import domain_file, plot_period
from ecefast.periods.present.bathymetry import BATHYMETRIES
from ecefast.tools.ecearth import get_backend

logger = logging.getLogger(__name__)

PERIOD = "present"
# NEMO grids of the reference tree that `ecefast present plot` compares the present-day domain with, besides the
# domain of its own grid: the standard EC-Earth4 grid of the same resolution, and the 1 degree grid
PLOT_REFERENCE_GRIDS = ("ORCA2", "eORCA1_ISO")


class PresentOIFS(ComponentStep):
    """Make the OIFS base data of grids.oifs from present.oifs.source_grid (inputs on Atos)."""

    name = "oifs"
    component = "oifs"
    needs = ["stage"]
    # reads and writes depend on present.oifs.steps: checked by OIFSData.check in from_context

    def __init__(self, generator: OIFSData, replaces: list[str]):
        self.generator = generator
        self.replaces = replaces

    @classmethod
    def from_context(cls, ctx: Context) -> "PresentOIFS":
        generator = OIFSData.from_context(ctx)
        generator.check()
        return cls(generator, ctx.check_overwrite(generator.final_files(), cls.name))

    def run(self) -> None:
        if self.replaces:
            pause_before_overwrite(self.replaces, self.name)
        self.generator.run()

    def dry_run(self) -> None:
        self.generator.run(dry_run=True)

    def planned_writes(self) -> list[str]:
        return [path for _, _, writes in self.generator.plan() for path in writes]


class PresentNEMO(ComponentStep):
    """Build the present-day NEMO domain of grids.nemo from the domain of present.nemo.source_grid."""

    name = "nemo"
    component = "nemo"
    needs = ["stage"]
    # reads and writes depend on present.nemo.steps: checked by NEMOWorkflow.check in from_context

    def __init__(self, workflow: NEMOWorkflow, replaces: list[str]):
        self.workflow = workflow
        self.replaces = replaces

    @classmethod
    def from_context(cls, ctx: Context) -> "PresentNEMO":
        domain_dir = os.path.join(ctx.section.output, "nemo", "domain", ctx.config.grids.nemo.name)
        processor = BATHYMETRIES[ctx.config.data_version]
        workflow = NEMOWorkflow.from_context(ctx, processor, domain_dir, get_backend(ctx.config))
        workflow.check()
        return cls(workflow, ctx.check_overwrite(workflow.final_files(), cls.name))

    def run(self) -> None:
        if self.replaces:
            pause_before_overwrite(self.replaces, self.name)
        self.workflow.run()

    def dry_run(self) -> None:
        self.workflow.run(dry_run=True)

    def planned_writes(self) -> list[str]:
        return [path for _, _, writes in self.workflow.plan() for path in writes]


class PresentStage(Stage):
    """Copy base files from the input tree to the output tree, with the ORCA2 domain the Eocene reads."""

    # The Eocene starts from this tree (eocene.input: "{present.output}"), and EoceneNEMO reads the ORCA2 domain
    # as the present-day ocean mask of the woa-pi profile.
    NEMO_DOMAINS = ["ORCA2"]
    reads = Stage.reads + ["{input}/nemo/domain/ORCA2"]
    writes = Stage.writes + ["{output}/nemo/domain/ORCA2"]


PIPELINE: list[type[ComponentStep]] = [PresentStage, PresentOIFS, PresentNEMO]


def run(
    config_file: str,
    select: list[str] | None = None,
    component: str | None = None,
    substeps: dict[str, list[str]] | None = None,
    dry_run: bool = False,
    overwrite: bool = False,
) -> list[str]:
    """Run the present-day pipeline from a configuration file (section ``present``).

    Parameters
    ----------
    config_file : str
        Configuration file (schema 2) with a ``present`` section.
    select : list of str, optional
        Names of the steps to run (``stage``, ``oifs``, ``nemo``). ``None`` runs all of them.
    component : str, optional
        Run only the step of this component (``ecefast <component> run``).
    substeps : dict, optional
        Per component, the steps to run instead of the configured ones (``{"nemo": [...]}``).
    dry_run : bool
        Only check the inputs and log the plan; write nothing.
    overwrite : bool
        With ``stage``: replace an output tree that holds files. Without: replace final files that exist already.
        Both after a warning and a pause.

    Returns
    -------
    list of str
        Names of the steps that ran (or would run, for a dry run).

    Raises
    ------
    ConfigError
        If the configuration is invalid, has no ``present`` section or no section of a selected component.
    PipelineError
        If an input is missing, or an output exists and ``overwrite`` is off.
    """
    names, _ = run_period(PIPELINE, config_file, PERIOD, select, component, substeps, dry_run, overwrite)
    return names


def plot(config_file: str, out_dir: str, reference: str | None = None, groups: list[str] | None = None) -> dict:
    """Draw the plots of the present-day output (``ecefast present plot``), see :mod:`ecefast.periods.plots`.

    The present-day NEMO domain of ``grids.nemo`` (built on Atos) is compared with the domains of the reference tree
    (by default ``present.input``) that it holds: the one of the same grid cell by cell, those of
    ``PLOT_REFERENCE_GRIDS`` (ORCA2, eORCA1_ISO) remapped conservatively onto its cells. Each reference domain also
    gets its own domain map.

    Parameters
    ----------
    config_file : str
        Configuration file (schema 2) with a ``present`` section.
    out_dir : str
        Plot directory, outside the EC-Earth trees.
    reference : str, optional
        Root of the reference tree; default ``present.input``.
    groups : list of str, optional
        Groups to draw (``nemo``, ``oifs``, ``coupling``); default all.

    Returns
    -------
    dict
        The content of ``summary.yml``.

    Raises
    ------
    ConfigError
        If the configuration is invalid or has no ``present`` section.
    PipelineError
        If the plot directory is inside an EC-Earth tree or an input file is missing.
    """
    ctx = Context(load_config(config_file), PERIOD)
    reference = os.path.abspath(reference or ctx.section.input)
    grids = dict.fromkeys([ctx.config.grids.nemo.name, *PLOT_REFERENCE_GRIDS])
    domains = [path for path in (domain_file(reference, grid) for grid in grids) if os.path.isfile(path)]
    return plot_period(ctx, os.path.abspath(out_dir), reference, domains, groups=groups)
