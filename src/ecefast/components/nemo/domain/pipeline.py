#!/usr/bin/env python3
"""
NEMO bathymetry workflow: generates domain configuration files for PALEORCA2.

Each bathymetry source is handled by a BathymetryProcessor subclass that lives
in bathymetry/.  The YAML entry names the class; all algorithm choices are
encapsulated in the class.

Usage:
    ecefast nemo-domain --config configs/laptop.yml [--only NAME [NAME ...]]
    python -m ecefast.components.nemo.domain.pipeline --config configs/laptop.yml [--only NAME [NAME ...]]

The pipeline reads the ``nemo_domain`` section of the configuration file (template: ``configs/laptop.tmpl``).
"""

import argparse
import logging
import dataclasses
import os

from ecefast.core.cdo import cdo_version, get_cdo
from ecefast.core.config import ConfigError, NemoDomain, Paths, load_config
from ecefast.core.logger import setup_logger
from ecefast.components.nemo.common.executor import SubprocessExecutor
from ecefast.components.nemo.common.util import process_domain_cfg, extract_maskutil, check_files_exist
from ecefast.components.nemo.bathymetry.present_day import PresentDayBathymetry

# temporary until task 5.2: components must not import paleo
from ecefast.paleo.eocene.bathymetry import EoceneBathymetry

# explicit name: this module also runs with `python -m`, where __name__ is "__main__"
logger = logging.getLogger("ecefast.components.nemo.domain.pipeline")


# Registry: maps the processor name used in YAML to the class.
# Add a new entry here when adding a new processor.
PROCESSOR_REGISTRY = {
    "PresentDayBathymetry": PresentDayBathymetry,
    "EoceneBathymetry": EoceneBathymetry,
}

STAGGERING_OPTIONS = ["T", "F"]


class NEMOWorkflow:
    def __init__(self, config: NemoDomain, paths: Paths, only=None, log_level="INFO"):
        output_dir = config.output_dir
        coordsdir = os.path.join(output_dir, "coordinates")
        self.paths = {
            "output_dir": output_dir,
            "coordsdir": coordsdir,
            "bathydir": os.path.join(output_dir, "bathymetry"),
            "outputdir": os.path.join(output_dir, "domain"),
            "domaincfg_dir": config.domaincfg_dir or "",
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
                raise ValueError(f"Unknown bathymetry name(s): {', '.join(sorted(unknown))}")
            self.bathymetries = [cfg for cfg in self.bathymetries if cfg["name"] in only]

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
        name = cfg["processor"]
        cls = PROCESSOR_REGISTRY.get(name)
        if cls is None:
            raise ValueError(
                f"Processor '{name}' not found in PROCESSOR_REGISTRY. "
                "Add an import and a registry entry in ecefast/components/nemo/domain/pipeline.py."
            )
        return cls(cfg, self.paths, self.grids, self.params, self.cdo)

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
        domaincfg_dir = self.paths["domaincfg_dir"]
        outputdir = self.paths["outputdir"]
        coords = self._target_halo()

        # Write namelists into domaincfg_dir/DOMAINcfg if available (HPC), else outputdir
        namelist_dir = os.path.join(domaincfg_dir, "DOMAINcfg") if domaincfg_dir else outputdir
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
    # Step 4: Run domain configuration tool (HPC)
    # ------------------------------------------------------------------

    def run_domain_cfg(self):
        """Delegate HPC module loading + compilation + execution to run_domain_cfg.sh."""
        domaincfg_dir = self.paths["domaincfg_dir"]
        names = [cfg["name"] for cfg in self.bathymetries]

        logger.info("Running domain configuration (HPC step)...")
        self.executor.run_bash_script("domain/run_domain_cfg.sh", [domaincfg_dir] + names)

    # ------------------------------------------------------------------
    # Step 5: Post-process domain_cfg + extract maskutil
    # ------------------------------------------------------------------

    def generate_mask_util(self):
        """Post-process domain_cfg.nc and extract maskutil.nc for each bathymetry."""
        domaincfg_dir = self.paths["domaincfg_dir"]
        outputdir = self.paths["outputdir"]
        tgt = self.grids["target"]
        src_dir = os.path.join(domaincfg_dir, "DOMAINcfg")

        for cfg in self.bathymetries:
            name = cfg["name"]
            tgt_dir = os.path.join(outputdir, tgt, name)
            logger.info("Processing domain_cfg and mask util for %s -> %s", name, tgt_dir)

            # Process domain_cfg: rename vertical dimension
            process_domain_cfg(src_dir, tgt_dir, name)

            # Extract maskutil from mesh_mask
            extract_maskutil(src_dir, tgt_dir, name)

    # ------------------------------------------------------------------
    # Step 6: Generate subbasin masks (present-day only)
    # ------------------------------------------------------------------

    def generate_subbasins(self):
        """Generate ocean subbasin masks for present-day bathymetry only.

        Calls the domain/subbasins.py script for each bathymetry.
        Only applicable to PresentDayBathymetry processor.
        """
        domaincfg_dir = self.paths["domaincfg_dir"]
        outputdir = self.paths["outputdir"]
        tgt = self.grids["target"]
        src_dir = os.path.join(domaincfg_dir, "DOMAINcfg")

        for cfg in self.bathymetries:
            name = cfg["name"]
            processor_name = cfg["processor"]

            # Only generate subbasins for present-day bathymetry
            if processor_name != "PresentDayBathymetry":
                logger.info("Skipping subbasins for %s (only applicable to present-day)", name)
                continue

            tgt_dir = os.path.join(outputdir, tgt, name)
            logger.info("Generating subbasin masks for %s -> %s", name, tgt_dir)

            self.executor.run_python_script(
                "domain/subbasins.py", ["--src_dir", src_dir, "--tgt_dir", tgt_dir, "--name", name]
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
            src_dir = os.path.join(self.paths["domaincfg_dir"], "DOMAINcfg")
            check_files_exist(
                src_dir, self.bathymetries, ["domain_cfg_{name}.nc", "mesh_mask_{name}.nc"], "generate_mask"
            )
            self.generate_mask_util()

        if self.steps.get("generate_subbasins"):
            logger.info("=== Step: Generate Subbasin Masks ===")
            # Check that mesh_mask files exist
            src_dir = os.path.join(self.paths["domaincfg_dir"], "DOMAINcfg")
            check_files_exist(src_dir, self.bathymetries, ["mesh_mask_{name}.nc"], "generate_subbasins")
            self.generate_subbasins()

        logger.info("Workflow complete.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="NEMO bathymetry workflow")
    parser.add_argument("-c", "--config", required=True, help="configuration file with a 'nemo_domain' section")
    parser.add_argument(
        "--only",
        nargs="+",
        metavar="NAME",
        help="Run only the specified bathymetry name(s) (e.g. --only present_day eocene)",
    )
    parser.add_argument(
        "-l", "--log-level", default="INFO", metavar="LEVEL", help="Logging level: DEBUG, INFO, WARNING (default: INFO)"
    )
    args = parser.parse_args(argv)

    setup_logger(args.log_level)
    logger.info("CDO version: %s", cdo_version())

    config = load_config(args.config)
    if config.nemo_domain is None:
        raise ConfigError(f"{args.config}: the NEMO domain pipeline needs a 'nemo_domain' section")

    NEMOWorkflow(config.nemo_domain, config.paths, only=args.only, log_level=args.log_level).run()


if __name__ == "__main__":
    main()
