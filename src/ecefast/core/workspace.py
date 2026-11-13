"""The run context and the ``stage`` step.

:class:`Context` gives steps the configuration and expands path templates; it refuses write paths inside the
read-only roots (``inputs.ece4_data``, ``inputs.herold``). :class:`Stage` copies the base files from the input tree to the output
tree, so the later steps can modify them.
"""

import logging
import os
import shutil
from dataclasses import dataclass

from .config import Config
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

    def expand(self, template: str) -> str:
        """Expand a path template.

        Parameters
        ----------
        template : str
            Path with ``{section.key}`` placeholders of the configuration, e.g.
            ``"{inputs.ece4_data}/oasis/{nemo.grid}/rstos.nc"`` (see :meth:`ecefast.core.config.Config.expand`).

        Returns
        -------
        str
            The path.

        Raises
        ------
        ConfigError
            If the template names a key that does not exist or is not set (e.g. ``{tmpdir}`` with ``tmpdir: null``).
        """
        return self.config.expand(template)

    def check_writable(self, path: str, step: str = "") -> None:
        """Refuse a write path inside a read-only root (``inputs.ece4_data`` or ``inputs.herold``).

        Parameters
        ----------
        path : str
            Path a step will write.
        step : str
            Step name, for the error message.

        Raises
        ------
        PipelineError
            If ``path`` is ``inputs.ece4_data``, ``inputs.herold`` or lies inside one of them.
        """
        real = os.path.realpath(path)
        for name in ("ece4_data", "herold"):
            root_name = f"inputs.{name}"
            root = os.path.realpath(getattr(self.config.inputs, name))
            if real == root or real.startswith(root + os.sep):
                who = f"Step '{step}'" if step else "A step"
                raise PipelineError(f"{who} would write {path}, inside the read-only '{root_name}' tree {root}")


class Stage(ComponentStep):
    """Copy base files from the input tree to the output tree."""

    name = "stage"
    needs = []
    reads = ["{inputs.ece4_data}/oifs", "{inputs.ece4_data}/nemo", "{inputs.ece4_data}/oasis/{nemo.grid}"]
    writes = ["{eocene.output_dir}/oifs", "{eocene.output_dir}/nemo", "{eocene.output_dir}/oasis/{nemo.grid}"]

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
        config = ctx.config
        return cls(
            config.inputs.ece4_data,
            config.eocene.output_dir,
            config.oifs.grid,
            config.nemo.grid,
            overwrite=ctx.overwrite,
        )

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
