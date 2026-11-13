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
from .layout import INITIAL_STATE, initial_state_copies
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
    final_output : str, optional
        Where the output tree goes at the end of a run with ``stage``, which writes into a partial tree first
        (then ``section.output`` is the partial tree); ``None`` when the steps write in place.
    """

    config: Config
    period: str
    overwrite: bool = False
    final_output: str | None = None

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

        The running period's own ``output`` is never read-only for it, even when another period starts from it
        (``eocene.input: "{present.output}"``).

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
        own = {os.path.realpath(p) for p in (self.section.output, self.final_output) if p}
        for key, root in self.config.read_only_roots().items():
            root = os.path.realpath(root)
            if root in own:  # another period's input, but this period's output
                continue
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


def copy_tree(src: str, dst: str, root: str) -> None:
    """Copy the folder ``src`` to ``dst``, keeping the relative symlinks that resolve inside ``root``.

    A link kept this way points to the copy in ``root``, as in the input tree (e.g. ``oifs/<grid>/<startdate>`` ->
    ``../../initial_state/oifs/<grid>/<startdate>``). Any other link (absolute, or to a file outside ``root``) is
    replaced by a copy of what it points to, so the output never depends on the input tree through it.

    Parameters
    ----------
    src : str
        Folder to copy.
    dst : str
        Destination, which must not exist.
    root : str
        Root of the output tree.
    """
    logger.debug(f"Copying {src} to {dst}")
    shutil.copytree(src, dst, symlinks=True)
    root_real = os.path.realpath(root)
    links = []
    for folder, dirs, files in os.walk(dst):
        links += [os.path.join(folder, name) for name in dirs + files if os.path.islink(os.path.join(folder, name))]
    for link in links:
        inside = os.path.exists(link) and os.path.realpath(link).startswith(root_real + os.sep)
        if inside and not os.path.isabs(os.readlink(link)):
            continue
        source = os.path.join(src, os.path.relpath(link, dst))
        os.unlink(link)
        if os.path.isdir(source):
            shutil.copytree(source, link)
        else:
            shutil.copy2(source, link)


# folders of initial_state/ copied by stage (the grids in use); the other components of initial_state/ are linked
INITIAL_STATE_COPIES = initial_state_copies("{grids.oifs.name}", "{grids.nemo.name}")


class Stage(ComponentStep):
    """Copy base files from the input tree to the output tree."""

    name = "stage"
    needs = []
    reads = ["{input}/oifs", "{input}/nemo", "{input}/oasis/{grids.nemo.name}", "{input}/runoff-mapper"] + [
        f"{{input}}/{path}" for path in INITIAL_STATE_COPIES
    ]
    writes = ["{output}/oifs", "{output}/nemo", "{output}/oasis/{grids.nemo.name}", "{output}/runoff-mapper"] + [
        f"{{output}}/{path}" for path in INITIAL_STATE_COPIES
    ]

    # subdirectories copied from each component of the input tree
    OIFS_SUBDIRS = ["composition", "ifsdata", "vtables", "rtables"]
    NEMO_SUBDIRS = ["cfc", "climatology", "initial", "weights"]
    # NEMO domains of the input tree copied too (nemo/domain/<grid>); none by default
    NEMO_DOMAINS: list[str] = []

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
        ``initial_state/`` comes first (:meth:`stage_initial_state`), then the other folders, whose relative links
        into ``initial_state/`` are kept (:func:`copy_tree`). ``cmip6-data`` is symlinked, not copied.
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
        # first: the links of the other folders point into it
        self.stage_initial_state()

        # loop through input directory and copy relevant subdirectories
        for item in os.listdir(input_dir):
            if item in ["oifs", "nemo", "oasis"]:
                os.makedirs(os.path.join(output_dir, item))  # declared in writes, even if nothing in it is kept
                for subitem in os.listdir(os.path.join(input_dir, item)):
                    if item == "oasis" and subitem not in [self.nemo_reso]:
                        continue
                    if item == "oifs" and subitem not in self.OIFS_SUBDIRS + [self.oifs_reso]:
                        continue
                    if item == "nemo" and subitem == "domain":
                        for grid in self.NEMO_DOMAINS:
                            src = os.path.join(input_dir, item, subitem, grid)
                            copy_tree(src, os.path.join(output_dir, item, subitem, grid), output_dir)
                        continue
                    if item == "nemo" and subitem not in self.NEMO_SUBDIRS:
                        continue
                    src = os.path.join(input_dir, item, subitem)
                    copy_tree(src, os.path.join(output_dir, item, subitem), output_dir)
            elif item == "runoff-mapper":
                copy_tree(os.path.join(input_dir, item), os.path.join(output_dir, item), output_dir)
            elif item in ["cmip6-data"]:
                src = os.path.join(input_dir, item)
                dst = os.path.join(output_dir, item)
                logger.debug(f"Copying {src} to {dst}")
                os.symlink(src, dst)  # use symlink for large CMIP6 data
            elif item != INITIAL_STATE:
                logger.debug(f"Skipping {item}!")

    def stage_initial_state(self) -> None:
        """Copy the folders of ``initial_state/`` of the grids in use, and link the other components.

        :func:`~ecefast.core.layout.initial_state_copies` names the copied folders: the OIFS and OASIS ones of the
        grids in use and the NEMO temperature and salinity states; other grids of those components are left out.
        The other components (``lpjg``, ``pism``, ...) are links to the real folders of the input tree, so that a
        tree made from this one does not link to links.
        """
        copies = initial_state_copies(self.oifs_reso, self.nemo_reso)
        for path in copies:
            copy_tree(os.path.join(self.input_dir, path), os.path.join(self.output_dir, path), self.output_dir)
        copied_components = {path.split(os.sep)[1] for path in copies}
        source = os.path.join(self.input_dir, INITIAL_STATE)
        for item in sorted(os.listdir(source)):
            if item not in copied_components:
                target = os.path.realpath(os.path.join(source, item))
                logger.debug(f"Linking {target}")
                os.symlink(target, os.path.join(self.output_dir, INITIAL_STATE, item))
