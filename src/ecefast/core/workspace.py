"""The run context and the ``stage`` step.

:class:`Context` gives steps the configuration and expands path templates; it refuses write paths inside the
read-only roots (``input``, ``herold``). :class:`Stage` copies the base files from the input tree to the output
tree, so the later steps can modify them.
"""

import logging
import os
import shutil
import string
from dataclasses import dataclass

from .config import Config, Grids, Paths
from .steps import ComponentStep, PipelineError

logger = logging.getLogger(__name__)


@dataclass
class Context:
    """What a step gets from the run: the configuration and path expansion.

    Parameters
    ----------
    config : Config
        The validated configuration.
    overwrite : bool
        Allow ``stage`` to replace an output directory that is not empty.
    """

    config: Config
    overwrite: bool = False

    @property
    def paths(self) -> Paths:
        """Root directories: ``input`` and ``herold`` (read-only), ``output``, ``tmpdir``."""
        return self.config.paths

    @property
    def grids(self) -> Grids:
        """Model resolutions (``oifs``, ``nemo``)."""
        return self.config.grids

    def placeholders(self) -> dict[str, str]:
        """Values of the placeholders allowed in path templates."""
        values = {
            "input": self.paths.input,
            "output": self.paths.output,
            "herold": self.paths.herold,
            "oifs_grid": self.grids.oifs,
            "nemo_grid": self.grids.nemo,
        }
        if self.paths.tmpdir is not None:
            values["tmpdir"] = self.paths.tmpdir
        return values

    def expand(self, template: str) -> str:
        """Expand a path template.

        Parameters
        ----------
        template : str
            Path with placeholders ``{input}``, ``{output}``, ``{herold}``, ``{tmpdir}``, ``{oifs_grid}``,
            ``{nemo_grid}``, e.g. ``"{input}/oasis/{nemo_grid}/rstos.nc"``.

        Returns
        -------
        str
            The path.

        Raises
        ------
        ValueError
            If the template has an unknown placeholder, or uses ``{tmpdir}`` and ``paths.tmpdir`` is not set.
        """
        values = self.placeholders()
        for _, field, _, _ in string.Formatter().parse(template):
            if field is None:
                continue
            if field == "tmpdir" and field not in values:
                raise ValueError(f"Path template {template!r} uses {{tmpdir}}, but 'paths.tmpdir' is not set")
            if field not in values:
                raise ValueError(
                    f"Unknown placeholder {{{field}}} in path template {template!r} "
                    f"(known: {', '.join('{' + k + '}' for k in values)})"
                )
        return template.format(**values)

    def check_writable(self, path: str, step: str = "") -> None:
        """Refuse a write path inside a read-only root (``input`` or ``herold``).

        Parameters
        ----------
        path : str
            Path a step will write.
        step : str
            Step name, for the error message.

        Raises
        ------
        PipelineError
            If ``path`` is ``input``, ``herold`` or lies inside one of them.
        """
        real = os.path.realpath(path)
        for root_name in ("input", "herold"):
            root = os.path.realpath(getattr(self.paths, root_name))
            if real == root or real.startswith(root + os.sep):
                who = f"Step '{step}'" if step else "A step"
                raise PipelineError(f"{who} would write {path}, inside the read-only '{root_name}' tree {root}")


class Stage(ComponentStep):
    """Copy base files from the input tree to the output tree."""

    name = "stage"
    needs = []
    reads = ["{input}/oifs", "{input}/nemo", "{input}/oasis/{nemo_grid}"]
    writes = ["{output}/oifs", "{output}/nemo", "{output}/oasis/{nemo_grid}"]

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
        return cls(ctx.paths.input, ctx.paths.output, ctx.grids.oifs, ctx.grids.nemo, overwrite=ctx.overwrite)

    def run(self) -> None:
        """Copy the input folder to the output folder to preserve original data.

        An output folder that is not empty is refused, unless ``overwrite`` is set: then it is removed first.
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
        if os.path.isdir(output_dir) and os.listdir(output_dir) and not self.overwrite:
            raise PipelineError(
                f"Step 'stage': output directory {output_dir} is not empty. Nothing was written. "
                "Use --overwrite to replace it, or select steps without 'stage' to rerun them on it."
            )
        if os.path.exists(output_dir):
            logger.info(f"Output directory {output_dir} already exists. It will be overwritten.")
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
                    logger.info(f"Copying {src} to {dst}")
                    shutil.copytree(src, dst, symlinks=True)
            elif item in ["cmip6-data"]:
                src = os.path.join(input_dir, item)
                dst = os.path.join(output_dir, item)
                logger.info(f"Copying {src} to {dst}")
                os.symlink(src, dst)  # use symlink for large CMIP6 data
            else:
                logger.info(f"Skipping {item}!")
