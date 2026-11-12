"""
NEMO bathymetry workflow: generates domain configuration files for PALEORCA2.

Each bathymetry source is handled by a BathymetryProcessor subclass. The YAML entry names the class; all
algorithm choices are encapsulated in the class. The caller passes the mapping from names to classes (generic
ones in ``ecefast.components.nemo.bathymetry.PROCESSORS``, paleo ones under ``ecefast.paleo``) and the backend
that runs DOMAINcfg (``ecefast.tools.ecearth``).

Usage:
    ecefast nemo domain -c configs/laptop.yml [--bathymetry NAME [NAME ...]]

The pipeline reads the ``nemo_domain`` section of the configuration file (template: ``configs/laptop.tmpl``).
"""

import logging
import dataclasses
import os

from ecefast.core.cdo import cdo_version, get_cdo
from ecefast.core.config import ConfigError, NemoDomain, Paths, load_config
from ecefast.tools.ecearth import EcEarthTools, get_backend
from ecefast.components.nemo.common.executor import SubprocessExecutor
from ecefast.components.nemo.common.util import process_domain_cfg, extract_maskutil, check_files_exist
from ecefast.components.nemo.bathymetry.base import BathymetryProcessor

logger = logging.getLogger(__name__)

STAGGERING_OPTIONS = ["T", "F"]


class NEMOWorkflow:
    """The NEMO domain pipeline: coordinates, bathymetries, DOMAINcfg namelists, DOMAINcfg, masks.

    Parameters
    ----------
    config : NemoDomain
        The ``nemo_domain`` section of the configuration.
    paths : Paths
        The ``paths`` section: its values are placeholders in ``source_file``.
    processors : dict
        Bathymetry processor classes by the ``processor`` name used in ``config.bathymetries``.
    backend : EcEarthTools
        Runs DOMAINcfg (step ``domain_cfg``).
    only : list of str, optional
        Names of the bathymetries to run (default: all enabled ones).
    log_level : str
        Log level of the helper scripts.

    Raises
    ------
    ConfigError
        If ``only`` names an unknown or disabled bathymetry, a selected bathymetry uses an unknown processor, or
        the ``domain_cfg`` step is on and the backend is not available.
    """

    def __init__(
        self,
        config: NemoDomain,
        paths: Paths,
        processors: dict[str, type[BathymetryProcessor]],
        backend: EcEarthTools,
        only: list[str] | None = None,
        log_level: str = "INFO",
    ):
        output_dir = config.output_dir
        coordsdir = os.path.join(output_dir, "coordinates")
        outputdir = os.path.join(output_dir, "domain")
        self.paths = {
            "output_dir": output_dir,
            "coordsdir": coordsdir,
            "bathydir": os.path.join(output_dir, "bathymetry"),
            "outputdir": outputdir,
            "domaincfg_dir": config.domaincfg_dir or "",
            # DOMAINcfg namelists, and the raw DOMAINcfg output next to them: domaincfg_dir/DOMAINcfg if set
            # (HPC), else outputdir
            "namelist_dir": os.path.join(config.domaincfg_dir, "DOMAINcfg") if config.domaincfg_dir else outputdir,
            # Explicit entry points: pre-existing files consumed by this workflow
            "coords_ori": config.coords_ori,
            "mesh_mask": config.mesh_mask,
        }
        # Placeholders for source_file: the config's paths ({input}, {herold}, ...) and the optional aliases
        self.aliases = {**{k: v for k, v in dataclasses.asdict(paths).items() if v is not None}, **config.aliases}

        self.grids = config.grids
        self.params = config.parameters
        self.steps = config.steps

        # Resolve path placeholders, filter disabled entries, then apply --only
        self.bathymetries = [self._resolve_paths(cfg) for cfg in config.bathymetries if cfg.get("enabled", True)]
        if only:
            unknown = set(only) - {cfg["name"] for cfg in self.bathymetries}
            if unknown:
                raise ConfigError(
                    f"Unknown or disabled bathymetry name(s): {', '.join(sorted(unknown))} "
                    f"(enabled: {', '.join(cfg['name'] for cfg in self.bathymetries)})"
                )
            self.bathymetries = [cfg for cfg in self.bathymetries if cfg["name"] in only]

        self.processors = processors
        for cfg in self.bathymetries:
            if cfg["processor"] not in processors:
                raise ConfigError(
                    f"Unknown processor '{cfg['processor']}' for bathymetry '{cfg['name']}' "
                    f"(known: {', '.join(processors)})"
                )

        # fail before the first step, not after the bathymetries
        if self.steps.get("domain_cfg") and not backend.available():
            raise ConfigError(
                f"nemo_domain.steps.domain_cfg is on, but DOMAINcfg cannot run with the '{backend.name}' backend on "
                "this machine. Turn the step off (as on a laptop), or run on Atos with tools.backend: atos."
            )
        self.backend = backend
        self.log_level = log_level
        self.cdo = get_cdo()
        self.executor = SubprocessExecutor()
        self._validate_paths()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_paths(self, cfg):
        """Substitute {coordsdir}, {domaindir} etc. in bathymetry config strings/lists."""
        lookup = {**self.paths, **self.aliases}

        def resolve(v):
            if isinstance(v, str):
                return v.format_map(lookup)
            if isinstance(v, list):
                return [resolve(item) for item in v]
            return v

        return {k: resolve(v) for k, v in cfg.items()}

    def _validate_paths(self):
        for key, path in {**self.paths, **self.aliases}.items():
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

    def _make_processor(self, cfg):
        """Instantiate the processor declared in cfg['processor']."""
        return self.processors[cfg["processor"]](cfg, self.paths, self.grids, self.params, self.cdo)

    def domain_dir(self, name: str) -> str:
        """Directory of the post-processed ``domain_cfg.nc`` and ``maskutil.nc`` of bathymetry ``name``."""
        return os.path.join(self.paths["outputdir"], self.grids["target"], name)

    # ------------------------------------------------------------------
    # Step 1: Coordinates
    # ------------------------------------------------------------------

    def generate_coordinates(self):
        """Remove halo from target grid, then generate T/F bounds for target and source."""
        tgt = self.grids["target"]
        src = self.grids["source"]
        coordsdir = self.paths["coordsdir"]
        coords_ori = self.paths["coords_ori"]
        mesh_mask = self.paths["mesh_mask"]

        # Target grid: remove halo (NEMO 3.6 → 4.2 transition)
        coords_halo = os.path.join(coordsdir, tgt, "coords_halo.nc")
        logger.info("Removing halo from %s", coords_ori)
        os.makedirs(os.path.dirname(coords_halo), exist_ok=True)
        self.cdo.sethalo("-1,-1", input=coords_ori, output=coords_halo, options="-O")

        for stagg in STAGGERING_OPTIONS:
            outfile = os.path.join(coordsdir, tgt, f"coords_bounds_{stagg}.nc")
            logger.debug("Generating bounds for %s staggering %s", tgt, stagg)
            self.executor.run_python_script("orca_bounds.py", ["--stagg", stagg, "--no-level", coords_halo, outfile])

        # Source grid: NEMO 4.2 mesh_mask (no halo removal needed)
        for stagg in STAGGERING_OPTIONS:
            os.makedirs(os.path.join(coordsdir, src), exist_ok=True)
            outfile = os.path.join(coordsdir, src, f"coords_bounds_{stagg}.nc")
            logger.debug("Generating bounds for %s staggering %s", src, stagg)
            self.executor.run_python_script("orca_bounds.py", ["--stagg", stagg, "--no-level", mesh_mask, outfile])

    # ------------------------------------------------------------------
    # Step 2: Bathymetry pipeline (delegated to processor subclasses)
    # ------------------------------------------------------------------

    def process_bathymetry(self, cfg):
        """Instantiate the declared processor and run it."""
        processor = self._make_processor(cfg)
        processor.process()
        cfg["output_file"] = processor.output_file

    # ------------------------------------------------------------------
    # Step 3: Configure domain namelists
    # ------------------------------------------------------------------

    def configure_domain_namelists(self):
        """Generate NEMO DOMAINcfg namelist for each enabled bathymetry."""
        coords = self._target_halo()
        namelist_dir = self.paths["namelist_dir"]
        os.makedirs(namelist_dir, exist_ok=True)

        for cfg in self.bathymetries:
            name = cfg["name"]
            # Use pre-computed path if available, otherwise derive it via the processor
            output_file = cfg.get("output_file") or self._make_processor(cfg).expected_output()
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
        """Run DOMAINcfg on the namelists with the backend; the raw output lands next to the namelists."""
        names = [cfg["name"] for cfg in self.bathymetries]
        logger.info("Running DOMAINcfg with the '%s' backend...", self.backend.name)
        self.backend.domaincfg(self.paths["namelist_dir"], names)

    # ------------------------------------------------------------------
    # Step 5: Post-process domain_cfg + extract maskutil
    # ------------------------------------------------------------------

    def generate_mask_util(self):
        """Post-process domain_cfg.nc and extract maskutil.nc for each bathymetry."""
        src_dir = self.paths["namelist_dir"]

        for cfg in self.bathymetries:
            name = cfg["name"]
            tgt_dir = self.domain_dir(name)
            logger.info("Processing domain_cfg and mask util for %s -> %s", name, tgt_dir)

            # Process domain_cfg: rename vertical dimension
            process_domain_cfg(src_dir, tgt_dir, name)

            # Extract maskutil from mesh_mask
            extract_maskutil(src_dir, tgt_dir, name)

    # ------------------------------------------------------------------
    # Step 6: Generate subbasin masks
    # ------------------------------------------------------------------

    def generate_subbasins(self):
        """Generate ocean subbasin masks (``subbasins.nc``) for each bathymetry, with domain/subbasins.py.

        The basins are fixed lon/lat polygons drawn on present-day geography: for paleo bathymetries check the
        result by eye (``notebooks/analysis/eocene-subbasins.ipynb``).
        """
        src_dir = self.paths["namelist_dir"]

        for cfg in self.bathymetries:
            name = cfg["name"]
            tgt_dir = self.domain_dir(name)
            logger.info("Generating subbasin masks for %s -> %s", name, tgt_dir)

            self.executor.run_python_script(
                "domain/subbasins.py",
                ["--src_dir", src_dir, "--tgt_dir", tgt_dir, "--name", name, "--log-level", self.log_level],
            )

    # ------------------------------------------------------------------
    # Orchestrator
    # ------------------------------------------------------------------

    def run(self):
        if self.steps.get("coordinates"):
            logger.info("=== Step: Generate Coordinates ===")
            self.generate_coordinates()

        if self.steps.get("bathymetry"):
            logger.info("=== Step: Process Bathymetry ===")
            for cfg in self.bathymetries:
                self.process_bathymetry(cfg)

        if self.steps.get("configure_domain"):
            logger.info("=== Step: Configure Domain Namelists ===")
            self.configure_domain_namelists()

        if self.steps.get("domain_cfg"):
            logger.info("=== Step: Run Domain Configuration Tool ===")
            self.run_domain_cfg()

        if self.steps.get("generate_mask"):
            logger.info("=== Step: Generate Mask Util ===")
            # Check that domain_cfg files exist
            src_dir = self.paths["namelist_dir"]
            check_files_exist(
                src_dir, self.bathymetries, ["domain_cfg_{name}.nc", "mesh_mask_{name}.nc"], "generate_mask"
            )
            self.generate_mask_util()

        if self.steps.get("generate_subbasins"):
            logger.info("=== Step: Generate Subbasin Masks ===")
            # Check that mesh_mask files exist
            src_dir = self.paths["namelist_dir"]
            check_files_exist(src_dir, self.bathymetries, ["mesh_mask_{name}.nc"], "generate_subbasins")
            self.generate_subbasins()

        logger.info("Workflow complete.")


def run(
    config_file: str,
    processors: dict[str, type[BathymetryProcessor]],
    only: list[str] | None = None,
    log_level: str = "INFO",
) -> None:
    """Run the NEMO domain pipeline of a configuration file, with the backend of ``tools.backend``.

    Parameters
    ----------
    config_file : str
        Configuration file with a ``nemo_domain`` section.
    processors : dict
        Bathymetry processor classes by name (see :class:`NEMOWorkflow`).
    only : list of str, optional
        Names of the bathymetries to run (default: all enabled ones).
    log_level : str
        Log level of the helper scripts.

    Raises
    ------
    ConfigError
        If the configuration has no ``nemo_domain`` section, or see :class:`NEMOWorkflow`.
    """
    logger.info("CDO version: %s", cdo_version())
    config = load_config(config_file)
    if config.nemo_domain is None:
        raise ConfigError(f"{config_file}: the NEMO domain pipeline needs a 'nemo_domain' section")
    backend = get_backend(config)
    NEMOWorkflow(config.nemo_domain, config.paths, processors, backend, only=only, log_level=log_level).run()
