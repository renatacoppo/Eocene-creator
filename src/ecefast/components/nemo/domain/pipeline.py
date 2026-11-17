"""
NEMO domain pipeline: builds the NEMO domain (``domain_cfg.nc``, ``maskutil.nc``, ``subbasins.nc``, and on request
the ``diadct`` transport sections ``section_ijglobal.diadct``) of one bathymetry on the grid of ``grids.nemo``.

The bathymetry is a :class:`~ecefast.components.nemo.bathymetry.base.BathymetryProcessor` subclass, which holds
every algorithm choice (variable, mask, remapping, corrections) and declares its source file. Each time period
passes its own (``PresentDayBathymetry`` for ``present``, ``EoceneBathymetry`` for ``eocene``), with the backend
that runs DOMAINcfg (``ecefast.tools.ecearth``). It runs as the ``nemo`` step of ``ecefast present run``
(``ecefast nemo run``) and inside the ``domain`` step of ``ecefast eocene run`` (unless ``eocene.nemo.domain_dir`` is set).
"""

import logging
import os
import shutil

import xarray as xr

from ecefast.core.cdo import get_cdo
from ecefast.core.config import ConfigError
from ecefast.core.io import atomic_write
from ecefast.core.steps import PipelineError, missing_inputs_message
from ecefast.core.workspace import Context
from ecefast.tools.ecearth import SECTIONS_COORDINATES, SECTIONS_FILE, EcEarthTools, output_files
from ecefast.components.nemo.common.executor import SubprocessExecutor
from ecefast.components.nemo.common.util import process_domain_cfg, extract_maskutil
from ecefast.components.nemo.bathymetry.base import BathymetryProcessor
from ecefast.components.nemo.sections import read_sections, write_sections_coordinates

logger = logging.getLogger(__name__)

STAGGERING_OPTIONS = ["T", "F"]

# One line per step of <period>.nemo.steps (ecefast.core.config.DomainSteps), in run order; shown by
# `ecefast nemo run -h`
STEP_DESCRIPTIONS = {
    "coordinates": "target grid without halo, cell bounds of the target (and source) grid",
    "bathymetry": "remap the bathymetry of the period to the target grid, with its processor",
    "configure_domain": "write the DOMAINcfg namelist",
    "domain_cfg": "run DOMAINcfg on the machine of machine.name (Atos only)",
    "generate_mask": "post-process domain_cfg.nc and extract maskutil.nc",
    "generate_subbasins": "write the ocean subbasin masks subbasins.nc",
    "sections": "write the diadct transport sections section_ijglobal.diadct (SECTIONS_DIADCT, Atos only)",
}
# final files of a domain, in the domain directory
FINAL_FILES = {
    "generate_mask": ["domain_cfg.nc", "maskutil.nc"],
    "generate_subbasins": ["subbasins.nc"],
    "sections": [SECTIONS_FILE],
}


def check_raw_domain(domain_file: str, name: str) -> None:
    """Stop if a raw ``domain_cfg`` of DOMAINcfg is empty: no ocean cell, or coordinates that are all zero.

    DOMAINcfg can crash, or miss its input files, and still leave a readable file full of zeros.

    Parameters
    ----------
    domain_file : str
        The raw ``domain_cfg_<name>.nc``.
    name : str
        Bathymetry name, for the message.

    Raises
    ------
    PipelineError
        If the domain has no ocean cell or no coordinates.
    """
    with xr.open_dataset(domain_file) as ds:
        ocean_cells = int((ds["bottom_level"] > 0).sum())
        no_coordinates = not bool((ds["glamt"] != 0).any() or (ds["gphit"] != 0).any())
    if ocean_cells == 0 or no_coordinates:
        raise PipelineError(
            f"domain_cfg ({name}): DOMAINcfg wrote an empty domain, {domain_file}: {ocean_cells} ocean cells"
            f"{', coordinates all zero' if no_coordinates else ''}. DOMAINcfg crashed or did not read its input "
            "files: see its output above and ocean.output next to the file."
        )


class NEMOWorkflow:
    """The NEMO domain pipeline of one bathymetry: coordinates, bathymetry, DOMAINcfg namelist, DOMAINcfg, masks.

    The final files (``domain_cfg.nc``, ``maskutil.nc``, ``subbasins.nc``) go to ``domain_dir``; the intermediate
    files to ``workdir`` (``coordinates/``, ``bathymetry/``, ``domaincfg/`` with the DOMAINcfg namelist and raw
    output, unless the backend runs DOMAINcfg in its own folder: then they go there, and ``sections/`` where
    SECTIONS_DIADCT runs).

    Parameters
    ----------
    processor : type of BathymetryProcessor
        The bathymetry of the period.
    source_file : str
        Its source file.
    grids : dict
        ``target`` (grid name), ``source`` (grid of the source file, or ``None``), ``staggering_target``,
        ``staggering_source``.
    coords_ori : str
        Coordinates of the target grid with halo (NEMO 3.6).
    input_dir : str
        Input tree of the period: the source grid is ``nemo/domain/<source>/domain_cfg.nc`` in it, and the
        processor may read reference domains from it.
    workdir : str
        Directory of the intermediate files.
    domain_dir : str
        Directory of the final files.
    minimum_depth : float
        Depths 0 < d < minimum_depth are raised to it (m).
    steps : dict of str to bool
        Which steps run (:data:`STEP_DESCRIPTIONS`).
    backend : EcEarthTools
        Runs DOMAINcfg (step ``domain_cfg``) and SECTIONS_DIADCT (step ``sections``).
    log_level : str
        Log level of the helper scripts.

    Raises
    ------
    ConfigError
        If the ``domain_cfg`` or ``sections`` step is on and the backend is not available, or the ``sections`` step
        is on for a bathymetry without transport sections.
    """

    def __init__(
        self,
        processor: type[BathymetryProcessor],
        source_file: str,
        grids: dict,
        coords_ori: str,
        input_dir: str,
        workdir: str,
        domain_dir: str,
        minimum_depth: float,
        steps: dict[str, bool],
        backend: EcEarthTools,
        log_level: str = "INFO",
    ):
        namelist_dir = backend.namelist_dir() or os.path.join(workdir, "domaincfg")
        self.paths = {
            "input": input_dir,
            "workdir": workdir,
            "coordsdir": os.path.join(workdir, "coordinates"),
            "bathydir": os.path.join(workdir, "bathymetry"),
            "domaindir": domain_dir,
            "sectionsdir": os.path.join(workdir, "sections"),
            # DOMAINcfg namelist, and the raw DOMAINcfg output next to it
            "namelist_dir": namelist_dir,
            # Explicit entry points: pre-existing files consumed by this workflow
            "coords_ori": coords_ori,
            # Source grid of the bathymetry, if it has one: its domain_cfg.nc in the input tree holds the
            # horizontal grid (glam*, gphi*, e1*, e2*) that orca_bounds.py reads, identical to its mesh_mask
            "source_grid": (
                os.path.join(input_dir, "nemo", "domain", grids["source"], "domain_cfg.nc") if grids["source"] else ""
            ),
        }
        self.grids = grids
        self.params = {"minimum_depth": minimum_depth}
        self.steps = steps
        self.processor_class = processor
        self.bathymetry = {"name": processor.name, "source_file": source_file}

        # fail before the first step, not after the bathymetry
        if self.steps.get("domain_cfg") and not backend.available():
            raise ConfigError(
                f"The domain_cfg step is on, but DOMAINcfg cannot run with 'machine.name: {backend.name}' on this "
                "machine. Turn the step off (as on a laptop: --nemo coordinates,bathymetry,configure_domain), or run "
                "on Atos with machine.name: atos."
            )
        if self.steps.get("sections"):
            if not processor.transport_sections:
                raise ConfigError(
                    f"The sections step is on, but the transport sections (present-day straits and passages) do not "
                    f"fit the '{processor.name}' bathymetry ({processor.__name__}.transport_sections is False). "
                    "Turn the step off."
                )
            if not backend.available():
                raise ConfigError(
                    f"The sections step is on, but SECTIONS_DIADCT cannot run with 'machine.name: {backend.name}' on "
                    "this machine. Turn the step off, or run on Atos with machine.name: atos."
                )
        self.backend = backend
        self.log_level = log_level
        self.cdo = get_cdo()
        self.executor = SubprocessExecutor()
        self._validate_paths()

    @classmethod
    def from_context(
        cls, ctx: Context, processor: type[BathymetryProcessor], domain_dir: str, backend: EcEarthTools
    ) -> "NEMOWorkflow":
        """Build the pipeline of the running period: section ``<period>.nemo``, ``grids.nemo``, ``machine.tmpdir``.

        Parameters
        ----------
        ctx : Context
            Run context.
        processor : type of BathymetryProcessor
            The bathymetry of the period; its ``source_file`` template is expanded in the period.
        domain_dir : str
            Directory of the final files.
        backend : EcEarthTools
            Runs DOMAINcfg.

        Raises
        ------
        ConfigError
            If the period has no ``nemo`` section, ``grids.nemo.coords_ori`` is not set, or see :meth:`__init__`.
        """
        nemo = ctx.section.nemo
        if nemo is None:
            raise ConfigError(f"{ctx.config.file}: the NEMO domain pipeline needs a '{ctx.period}.nemo' section")
        grid = ctx.config.grids.nemo
        if grid.coords_ori is None:
            raise ConfigError(f"{ctx.config.file}: the NEMO domain pipeline needs 'grids.nemo.coords_ori'")
        source_grid = getattr(nemo, "source_grid", None) if processor.has_source_grid else None
        grids = {
            "target": grid.name,
            "source": source_grid,
            "staggering_source": getattr(nemo, "source_staggering", "T"),
            "staggering_target": grid.staggering,
        }
        workdir = ctx.tmpdir("nemo")
        for path in (workdir, domain_dir):
            ctx.check_writable(path, "nemo")
        return cls(
            processor,
            ctx.expand(processor.source_file),
            grids,
            grid.coords_ori,
            ctx.section.input,
            workdir,
            domain_dir,
            nemo.minimum_depth,
            vars(nemo.steps),
            backend,
            log_level=logging.getLevelName(logging.getLogger("ecefast").getEffectiveLevel()),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _validate_paths(self):
        for key, path in self.paths.items():
            if path and " " in path:
                raise ValueError(f"Path for '{key}' contains spaces: '{path}'. This breaks CDO operator chaining.")

    def _target_bounds(self, staggering=None):
        s = staggering or self.grids["staggering_target"]
        tgt = self.grids["target"]
        return os.path.join(self.paths["coordsdir"], tgt, f"coords_bounds_{s}.nc")

    def _target_halo(
        self,
    ):
        tgt = self.grids["target"]
        return os.path.join(self.paths["coordsdir"], tgt, f"coords_halo.nc")

    def _make_processor(self):
        """Instantiate the bathymetry processor."""
        return self.processor_class(self.bathymetry, self.paths, self.grids, self.params, self.cdo)

    @property
    def name(self) -> str:
        """Name of the bathymetry: suffix of the DOMAINcfg namelist and raw output files."""
        return self.bathymetry["name"]

    @property
    def domain_dir(self) -> str:
        """Directory of the final ``domain_cfg.nc``, ``maskutil.nc`` and ``subbasins.nc``."""
        return self.paths["domaindir"]

    def final_files(self) -> list[str]:
        """The final files the enabled steps write in :attr:`domain_dir`."""
        return [
            os.path.join(self.domain_dir, f)
            for step, files in FINAL_FILES.items()
            if self.steps.get(step)
            for f in files
        ]

    # ------------------------------------------------------------------
    # Step 1: Coordinates
    # ------------------------------------------------------------------

    def generate_coordinates(self):
        """Remove halo from target grid, then generate T/F bounds for target and source (if any)."""
        tgt = self.grids["target"]
        src = self.grids["source"]
        coordsdir = self.paths["coordsdir"]
        coords_ori = self.paths["coords_ori"]
        source_grid = self.paths["source_grid"]

        # Target grid: remove halo (NEMO 3.6 → 4.2 transition)
        coords_halo = os.path.join(coordsdir, tgt, "coords_halo.nc")
        logger.info("Removing halo from %s", coords_ori)
        os.makedirs(os.path.dirname(coords_halo), exist_ok=True)
        self.cdo.sethalo("-1,-1", input=coords_ori, output=coords_halo, options="-O")

        for stagg in STAGGERING_OPTIONS:
            outfile = os.path.join(coordsdir, tgt, f"coords_bounds_{stagg}.nc")
            logger.debug("Generating bounds for %s staggering %s", tgt, stagg)
            self.executor.run_python_script("orca_bounds.py", ["--stagg", stagg, "--no-level", coords_halo, outfile])

        # Source grid: NEMO 4.2 domain_cfg.nc of the input tree (no halo removal needed), if the bathymetry has one
        if not src:
            return
        for stagg in STAGGERING_OPTIONS:
            os.makedirs(os.path.join(coordsdir, src), exist_ok=True)
            outfile = os.path.join(coordsdir, src, f"coords_bounds_{stagg}.nc")
            logger.debug("Generating bounds for %s staggering %s", src, stagg)
            self.executor.run_python_script("orca_bounds.py", ["--stagg", stagg, "--no-level", source_grid, outfile])

    # ------------------------------------------------------------------
    # Step 2: Bathymetry pipeline (delegated to processor subclasses)
    # ------------------------------------------------------------------

    def process_bathymetry(self):
        """Instantiate the processor and run it."""
        processor = self._make_processor()
        processor.process()
        self.bathymetry["output_file"] = processor.output_file

    # ------------------------------------------------------------------
    # Step 3: Configure domain namelists
    # ------------------------------------------------------------------

    def configure_domain_namelists(self):
        """Generate the NEMO DOMAINcfg namelist of the bathymetry."""
        coords = self._target_halo()
        namelist_dir = self.paths["namelist_dir"]
        os.makedirs(namelist_dir, exist_ok=True)

        name = self.name
        # Use pre-computed path if available, otherwise derive it via the processor
        output_file = self.bathymetry.get("output_file") or self._make_processor().expected_output()
        if not os.path.isfile(output_file):
            raise FileNotFoundError(
                f"Bathymetry file not found for '{name}': {output_file}\nRun the bathymetry step first."
            )
        namelist_out = os.path.join(namelist_dir, f"namelist_cfg_{name}")
        logger.info("Generating namelist for %s: %s", name, namelist_out)
        self.executor.run_python_script(
            "domain/namelist.py",
            [
                "--bathymetry",
                output_file,
                "--coordinates",
                coords,
                "--output",
                namelist_out,
                "--log-level",
                self.log_level,
            ],
        )

    # ------------------------------------------------------------------
    # Step 4: Run domain configuration tool (through the backend)
    # ------------------------------------------------------------------

    def run_domain_cfg(self):
        """Run DOMAINcfg on the namelist with the backend; the raw output lands next to the namelist."""
        logger.info("Running DOMAINcfg with the '%s' backend...", self.backend.name)
        outputs = self.backend.domaincfg(self.paths["namelist_dir"], [self.name])
        check_raw_domain(str(outputs[self.name][0]), self.name)

    # ------------------------------------------------------------------
    # Step 5: Post-process domain_cfg + extract maskutil
    # ------------------------------------------------------------------

    def generate_mask_util(self):
        """Post-process domain_cfg.nc and extract maskutil.nc."""
        src_dir, tgt_dir, name = self.paths["namelist_dir"], self.domain_dir, self.name
        logger.info("Processing domain_cfg and mask util for %s -> %s", name, tgt_dir)

        # Process domain_cfg: rename vertical dimension
        process_domain_cfg(src_dir, tgt_dir, name)

        # Extract maskutil from mesh_mask
        extract_maskutil(src_dir, tgt_dir, name)

        if self.processor_class.rule_based_geography:
            self.check_domain_mask()

    def check_domain_mask(self):
        """Data version v2: the domain keeps the land-sea mask of the bathymetry, so the geography rules hold.

        The geography rules make the north-fold row symmetric, as DOMAINcfg does, so every row is compared.

        Raises
        ------
        PipelineError
            If DOMAINcfg turned ocean cells into land or the other way round.
        """
        processor = self._make_processor()
        bathymetry_file = self.bathymetry.get("output_file") or processor.expected_output()
        with xr.open_dataset(bathymetry_file) as ds:
            bathymetry_ocean = ds[processor.variable_name()].squeeze().values > 0
        with xr.open_dataset(os.path.join(self.domain_dir, "domain_cfg.nc")) as ds:
            domain_ocean = ds["top_level"].squeeze().values > 0
        differ = bathymetry_ocean != domain_ocean
        if differ.any():
            cells = ", ".join(f"({j}, {i})" for j, i in list(zip(*differ.nonzero()))[:10])
            raise PipelineError(
                f"DOMAINcfg changed the land-sea mask of the '{self.name}' bathymetry in {int(differ.sum())} cells "
                f"(j, i: {cells}). The geography rules no longer hold; check the "
                f"DOMAINcfg namelist (rn_hmin, closed seas) against {bathymetry_file}."
            )

    # ------------------------------------------------------------------
    # Step 6: Generate subbasin masks
    # ------------------------------------------------------------------

    def generate_subbasins(self):
        """Generate the ocean subbasin masks (``subbasins.nc``) with domain/subbasins.py.

        The regional basins are fixed lon/lat polygons drawn on present-day geography. A bathymetry whose processor
        sets ``regional_subbasins = False`` gets the global mask only.
        """
        src_dir, tgt_dir, name = self.paths["namelist_dir"], self.domain_dir, self.name
        logger.info("Generating subbasin masks for %s -> %s", name, tgt_dir)

        args = ["--src_dir", src_dir, "--tgt_dir", tgt_dir, "--name", name, "--log-level", self.log_level]
        if not self.processor_class.regional_subbasins:
            args.append("--global-only")
        self.executor.run_python_script("domain/subbasins.py", args)

    # ------------------------------------------------------------------
    # Step 7: Transport sections of NEMO diadct
    # ------------------------------------------------------------------

    def generate_sections(self):
        """Write ``section_ijglobal.diadct`` with SECTIONS_DIADCT, on the grid of the final ``domain_cfg.nc``.

        The coordinates file of the tool and its raw output go to ``workdir/sections``; the output is then copied
        to the domain directory. Sections that do not cross the grid have no points: they are logged.
        """
        sections_dir = self.paths["sectionsdir"]
        os.makedirs(sections_dir, exist_ok=True)
        write_sections_coordinates(
            os.path.join(self.domain_dir, "domain_cfg.nc"), os.path.join(sections_dir, SECTIONS_COORDINATES)
        )
        raw = self.backend.sections_diadct(sections_dir)

        sections = read_sections(raw)
        empty = [section["name"] for section in sections if not section["points"]]
        logger.info("%d transport sections, %d without grid points", len(sections), len(empty))
        if empty:
            logger.warning("Transport sections without grid points: %s", ", ".join(empty))

        final = os.path.join(self.domain_dir, SECTIONS_FILE)
        os.makedirs(self.domain_dir, exist_ok=True)
        with atomic_write(final) as tmp:
            shutil.copyfile(raw, tmp)

    # ------------------------------------------------------------------
    # Plan and input checks
    # ------------------------------------------------------------------

    def plan(self) -> list[tuple[str, list[str], list[str]]]:
        """The enabled steps in run order, each with the files it reads and writes.

        Returns
        -------
        list of (str, list of str, list of str)
            Step name, paths it reads, paths it writes.
        """
        coordsdir = self.paths["coordsdir"]
        namelist_dir = self.paths["namelist_dir"]
        name = self.name
        processor = self._make_processor()
        bathymetry_file = self.bathymetry.get("output_file") or processor.expected_output()
        namelist = os.path.join(namelist_dir, f"namelist_cfg_{name}")
        raw = output_files(namelist_dir, [name])[name]
        raw_files = [str(path) for path in raw]
        grids = [self.grids["target"]] + ([self.grids["source"]] if self.grids["source"] else [])
        bounds = [
            os.path.join(coordsdir, grid, f"coords_bounds_{stagg}.nc") for grid in grids for stagg in STAGGERING_OPTIONS
        ]
        source_grid = [self.paths["source_grid"]] if self.paths["source_grid"] else []

        steps = {
            "coordinates": ([self.paths["coords_ori"], *source_grid], [self._target_halo(), *bounds]),
            "bathymetry": (processor.reads(), [bathymetry_file]),
            "configure_domain": ([self._target_halo(), bathymetry_file], [namelist]),
            "domain_cfg": ([*self.backend.required_paths(), namelist], raw_files),
            "generate_mask": (
                raw_files + ([bathymetry_file] if processor.rule_based_geography else []),
                [os.path.join(self.domain_dir, f) for f in FINAL_FILES["generate_mask"]],
            ),
            "generate_subbasins": (
                [str(raw[1])],
                [os.path.join(self.domain_dir, f) for f in FINAL_FILES["generate_subbasins"]],
            ),
            "sections": (
                [os.path.join(self.domain_dir, "domain_cfg.nc"), *self.backend.sections_required_paths()],
                [
                    os.path.join(self.paths["sectionsdir"], SECTIONS_COORDINATES),
                    os.path.join(self.paths["sectionsdir"], SECTIONS_FILE),
                    os.path.join(self.domain_dir, SECTIONS_FILE),
                ],
            ),
        }
        return [(step, reads, writes) for step, (reads, writes) in steps.items() if self.steps.get(step)]

    def check(self) -> None:
        """Check that every file an enabled step reads exists, or is written by an earlier enabled step.

        Raises
        ------
        PipelineError
            Listing every missing input at once.
        """
        missing = []
        written = set()
        for name, reads, writes in self.plan():
            missing += [(name, path) for path in reads if path not in written and not os.path.exists(path)]
            written.update(writes)
        if missing:
            raise PipelineError(missing_inputs_message(missing))
        self.check_namelist_paths()

    def check_namelist_paths(self) -> None:
        """Check that the paths written to the DOMAINcfg namelist fit the tool (``backend.path_limits``).

        DOMAINcfg cuts a path longer than its character variable without a message and writes a domain of zeros.
        The paths lie in ``machine.tmpdir``, so a long ``tmpdir`` is the cause. Nothing is checked when neither
        ``configure_domain`` nor ``domain_cfg`` runs.

        Raises
        ------
        PipelineError
            Naming every path that is too long, its length and the limit.
        """
        if not (self.steps.get("configure_domain") or self.steps.get("domain_cfg")):
            return
        bathymetry_file = self.bathymetry.get("output_file") or self._make_processor().expected_output()
        paths = {"cn_fcoord": self._target_halo(), "cn_topo": bathymetry_file}
        too_long = [
            f"{key} = {paths[key]} ({len(paths[key])} characters, at most {limit})"
            for key, limit in self.backend.path_limits.items()
            if len(paths[key]) > limit
        ]
        if too_long:
            raise PipelineError(
                f"domain ({self.name}): path too long for the DOMAINcfg namelist, the tool would cut it and write an "
                f"empty domain: {'; '.join(too_long)}. Use a shorter machine.tmpdir."
            )

    # ------------------------------------------------------------------
    # Orchestrator
    # ------------------------------------------------------------------

    def run(self, dry_run: bool = False) -> None:
        """Check the inputs of the enabled steps, then run them.

        Parameters
        ----------
        dry_run : bool
            Only check the inputs and log the plan; write nothing.

        Raises
        ------
        PipelineError
            If an input is missing (see :meth:`check`).
        """
        self.check()
        if dry_run:
            logger.info("Dry run: nothing is written. Bathymetry: %s. Plan:", self.name)
            for name, _, writes in self.plan():
                logger.info("  %s", name)
                for path in writes:
                    logger.debug("      -> %s", path)
            return

        if self.steps.get("coordinates"):
            logger.info("=== Step: Generate Coordinates ===")
            self.generate_coordinates()

        if self.steps.get("bathymetry"):
            logger.info("=== Step: Process Bathymetry ===")
            self.process_bathymetry()

        if self.steps.get("configure_domain"):
            logger.info("=== Step: Configure Domain Namelists ===")
            self.configure_domain_namelists()

        if self.steps.get("domain_cfg"):
            logger.info("=== Step: Run Domain Configuration Tool ===")
            self.run_domain_cfg()

        if self.steps.get("generate_mask"):
            logger.info("=== Step: Generate Mask Util ===")
            self.generate_mask_util()

        if self.steps.get("generate_subbasins"):
            logger.info("=== Step: Generate Subbasin Masks ===")
            self.generate_subbasins()

        if self.steps.get("sections"):
            logger.info("=== Step: Generate Transport Sections ===")
            self.generate_sections()

        logger.info("Workflow complete.")
