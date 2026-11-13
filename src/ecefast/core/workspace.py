"""The run context, the overwrite pause and the ``stage`` step.

:class:`Context` gives steps the configuration and the running period, and expands path templates; it refuses
write paths inside the read-only directories (every period's ``input``, ``eocene.herold``). :class:`Stage` copies
the base files from the input tree to the output tree, so the later steps can modify them.
"""

import logging
import os
import shutil
import time
from dataclasses import dataclass

from .config import PLACEHOLDER, Config, ConfigError, Eocene, Present
from .steps import ComponentStep, PipelineError

logger = logging.getLogger(__name__)

# Seconds a run waits after announcing what --overwrite replaces, so the user can stop it (Ctrl-C).
OVERWRITE_PAUSE = 5


def pause_before_overwrite(paths: list[str], step: str) -> None:
    """Log what ``step`` is about to replace, then wait :data:`OVERWRITE_PAUSE` seconds (Ctrl-C to stop).

    Parameters
    ----------
    paths : list of str
        Files or directories that will be replaced or removed.
    step : str
        Step name, for the message.
    """
    shown = ", ".join(paths[:5]) + (f" and {len(paths) - 5} more" if len(paths) > 5 else "")
    logger.warning(
        "Step '%s' (--overwrite) replaces %s. Starting in %d s, Ctrl-C to stop.", step, shown, OVERWRITE_PAUSE
    )
    time.sleep(OVERWRITE_PAUSE)


@dataclass
class Context:
    """What a step gets from the run: the configuration, the running period and path expansion.

    Parameters
    ----------
    config : Config
        The validated configuration.
    period : str
        The running period (``present`` or ``eocene``).
    overwrite : bool
        Allow the steps to replace existing outputs (``--overwrite``).
    """

    config: Config
    period: str
    overwrite: bool = False

    @property
    def section(self) -> Present | Eocene:
        """The configuration section of the running period."""
        return self.config.period(self.period)

    def tmpdir(self, component: str) -> str:
        """Directory of the intermediate files of ``component`` in this period: ``<machine.tmpdir>/<period>/<component>``."""
        return os.path.join(self.config.machine.tmpdir, self.period, component)

    def expand(self, template: str) -> str:
        """Expand a path template.

        A placeholder is first looked up in the running period (``{input}``, ``{output}``, ``{herold}``,
        ``{nemo.source_grid}``), then in the whole file (``{grids.nemo.name}``, ``{present.input}``).

        Parameters
        ----------
        template : str
            Path with placeholders, e.g. ``"{input}/oasis/{grids.nemo.name}/rstos.nc"``.

        Returns
        -------
        str
            The path.

        Raises
        ------
        ConfigError
            If a placeholder names a key that does not exist in the period or the file, or is not set.
        """

        def value(name: str) -> str:
            try:
                return str(self.config.lookup(f"{self.period}.{name}"))
            except ConfigError:
                return str(self.config.lookup(name))

        return PLACEHOLDER.sub(lambda m: value(m.group(1)), template)

    def check_writable(self, path: str, step: str = "") -> None:
        """Refuse a write path inside a read-only directory (every period's ``input``, ``eocene.herold``).

        Parameters
        ----------
        path : str
            Path a step will write.
        step : str
            Step name, for the error message.

        Raises
        ------
        PipelineError
            If ``path`` is a read-only directory or lies inside one.
        """
        real = os.path.realpath(path)
        for key, root in self.config.read_only_roots().items():
            root = os.path.realpath(root)
            if real == root or real.startswith(root + os.sep):
                who = f"Step '{step}'" if step else "A step"
                raise PipelineError(f"{who} would write {path}, inside the read-only '{key}' tree {root}")

    def check_overwrite(self, paths: list[str], step: str) -> list[str]:
        """The outputs of ``step`` that exist already; refused unless ``--overwrite``.

        Parameters
        ----------
        paths : list of str
            Final files the step writes.
        step : str
            Step name, for the error message.

        Returns
        -------
        list of str
            The paths that exist (to pass to :func:`pause_before_overwrite` when the step runs).

        Raises
        ------
        PipelineError
            If some exist and ``overwrite`` is off.
        """
        existing = [p for p in paths if os.path.exists(p)]
        if existing and not self.overwrite:
            raise PipelineError(
                f"Step '{step}': {len(existing)} output file(s) exist already, e.g. {existing[0]}. Nothing was "
                "written. Use --overwrite to replace them."
            )
        return existing


class Stage(ComponentStep):
    """Copy base files from the input tree to the output tree."""

    name = "stage"
    needs = []
    reads = ["{input}/oifs", "{input}/nemo", "{input}/oasis/{grids.nemo.name}"]
    writes = ["{output}/oifs", "{output}/nemo", "{output}/oasis/{grids.nemo.name}"]

    # subdirectories copied from each component of the input tree
    OIFS_SUBDIRS = ["composition", "ifsdata", "vtables", "rtables"]
    NEMO_SUBDIRS = ["cfc", "climatology", "initial", "weights"]

    def __init__(self, input_dir: str, output_dir: str, oifs_reso: str, nemo_reso: str, overwrite: bool = False):
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.oifs_reso = oifs_reso
        self.nemo_reso = nemo_reso
        self.overwrite = overwrite

    @classmethod
    def from_context(cls, ctx: Context) -> "Stage":
        grids = ctx.config.grids
        return cls(ctx.section.input, ctx.section.output, grids.oifs.name, grids.nemo.name, overwrite=ctx.overwrite)

    def run(self) -> None:
        """Copy the input folder to the output folder to preserve original data.

        An output folder that holds files is refused, unless ``overwrite`` is set: then it is removed first, after
        a warning and a pause (:func:`pause_before_overwrite`).
        ``cmip6-data`` is symlinked, not copied.
        """
        input_dir, output_dir = self.input_dir, self.output_dir
        logger.info(f"Copying input data from {input_dir} to {output_dir}")
        # refuse to delete the input directory or one of its parents
        input_real = os.path.realpath(input_dir)
        output_real = os.path.realpath(output_dir)
        if input_real == output_real or input_real.startswith(output_real + os.sep):
            raise ValueError(
                f"Output directory {output_dir} is or contains the input directory {input_dir}. "
                "Refusing to overwrite it."
            )
        # files only: the preflight of later steps may have created empty folders in it already
        has_files = os.path.isdir(output_dir) and any(files for _, _, files in os.walk(output_dir))
        if has_files and not self.overwrite:
            raise PipelineError(
                f"Step 'stage': output directory {output_dir} is not empty. Nothing was written. "
                "Use --overwrite to replace it, or select steps without 'stage' to rerun them on it."
            )
        if has_files:
            pause_before_overwrite([output_dir], self.name)
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)
        os.makedirs(output_dir)

        # loop through input directory and copy relevant subdirectories
        for item in os.listdir(input_dir):
            if item in ["oifs", "nemo", "oasis"]:
                for subitem in os.listdir(os.path.join(input_dir, item)):
                    if item == "oasis" and subitem not in [self.nemo_reso]:
                        continue
                    if item == "oifs" and subitem not in self.OIFS_SUBDIRS + [self.oifs_reso]:
                        continue
                    if item == "nemo" and subitem not in self.NEMO_SUBDIRS:
                        continue
                    src = os.path.join(input_dir, item, subitem)
                    dst = os.path.join(output_dir, item, subitem)
                    logger.debug(f"Copying {src} to {dst}")
                    shutil.copytree(src, dst, symlinks=True)
            elif item in ["cmip6-data"]:
                src = os.path.join(input_dir, item)
                dst = os.path.join(output_dir, item)
                logger.debug(f"Copying {src} to {dst}")
                os.symlink(src, dst)  # use symlink for large CMIP6 data
            else:
                logger.debug(f"Skipping {item}!")
