#!/usr/bin/env python3
"""
NEMO bathymetry workflow: generates domain configuration files for PALEORCA2.

Each bathymetry source is handled by a BathymetryProcessor subclass that lives
in processors/.  The YAML entry names the class; all algorithm choices are
encapsulated in the class.

Usage:
    python3 cli-domain-paleorca.py --config nemo_workflow.yaml [--only NAME [NAME ...]]
"""

import argparse
import logging
import os

import yaml
from cdo import Cdo

from common.executor import SubprocessExecutor
from common.logger import setup_logging
from processors.present_day import PresentDayBathymetry
from processors.eocene import EoceneBathymetry

# Absolute path to the directory containing this script — used to locate
# helper scripts in utils/ and domain-tools/ regardless of the caller's cwd.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

logger = logging.getLogger("nemo.workflow")


# Registry: maps the processor name used in YAML to the class.
# Add a new entry here when adding a new processor.
PROCESSOR_REGISTRY = {
    'PresentDayBathymetry': PresentDayBathymetry,
    'EoceneBathymetry':     EoceneBathymetry,
}

STAGGERING_OPTIONS = ['T', 'F']


class NEMOWorkflow:

    def __init__(self, config, only=None, log_level='INFO'):
        profile_name = config.get('profile', 'default')
        profile = config['profiles'][profile_name]

        basedir = profile['basedir']
        coordsdir = os.path.join(basedir, 'coordinates')
        self.paths = {
            'basedir':   basedir,
            'coordsdir': coordsdir,
            'bathydir':  os.path.join(basedir, 'bathymetry'),
            'outputdir': os.path.join(basedir, 'domain'),
            'ecedir':    profile.get('ecedir', ''),
            # Explicit entry points: pre-existing files consumed by this workflow
            'coords_ori': profile['coords_ori'],
            'mesh_mask':  profile['mesh_mask'],
        }
        # Optional per-profile aliases (e.g. {domaindir}, {herolddir}) used in source_file
        self.aliases = profile.get('aliases', {})

        self.grids  = config['grids']
        self.params = config['parameters']
        self.steps  = config['steps']

        # Resolve path placeholders, filter disabled entries, then apply --only
        self.bathymetries = [
            self._resolve_paths(cfg) for cfg in config.get('bathymetries', [])
            if cfg.get('enabled', True)
        ]
        if only:
            unknown = set(only) - {cfg['name'] for cfg in self.bathymetries}
            if unknown:
                raise ValueError(f"Unknown bathymetry name(s): {', '.join(sorted(unknown))}")
            self.bathymetries = [cfg for cfg in self.bathymetries if cfg['name'] in only]

        self.log_level = log_level
        self.cdo = Cdo()
        self.executor = SubprocessExecutor(_SCRIPT_DIR)
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
            if path and ' ' in path:
                raise ValueError(
                    f"Path for '{key}' contains spaces: '{path}'. "
                    "This breaks CDO operator chaining."
                )

    def _target_bounds(self, staggering=None):
        s   = staggering or self.grids['staggering_target']
        tgt = self.grids['target']
        return os.path.join(self.paths['coordsdir'], tgt, f'coords_bounds_{s}.nc')

    def _make_processor(self, cfg):
        """Instantiate the processor declared in cfg['processor']."""
        name = cfg['processor']
        cls  = PROCESSOR_REGISTRY.get(name)
        if cls is None:
            raise ValueError(
                f"Processor '{name}' not found in PROCESSOR_REGISTRY. "
                "Add an import and a registry entry in cli-domain-paleorca.py."
            )
        return cls(cfg, self.paths, self.grids, self.params, self.cdo)

    # ------------------------------------------------------------------
    # Step 1: Coordinates
    # ------------------------------------------------------------------

    def generate_coordinates(self):
        """Remove halo from target grid, then generate T/F bounds for target and source."""
        tgt        = self.grids['target']
        src        = self.grids['source']
        coordsdir  = self.paths['coordsdir']
        coords_ori = self.paths['coords_ori']
        mesh_mask  = self.paths['mesh_mask']

        # Target grid: remove halo (NEMO 3.6 → 4.2 transition)
        coords_halo = os.path.join(coordsdir, tgt, 'coords_halo.nc')
        logger.info("Removing halo from %s", coords_ori)
        os.makedirs(os.path.dirname(coords_halo), exist_ok=True)
        self.cdo.sethalo('-1,-1', input=coords_ori, output=coords_halo, options='-O')

        for stagg in STAGGERING_OPTIONS:
            outfile = os.path.join(coordsdir, tgt, f'coords_bounds_{stagg}.nc')
            logger.debug("Generating bounds for %s staggering %s", tgt, stagg)
            self.executor.run_python_script(
                'utils/generate-orca-bounds.py',
                ['--stagg', stagg, '--no-level', coords_halo, outfile]
            )

        # Source grid: NEMO 4.2 mesh_mask (no halo removal needed)
        for stagg in STAGGERING_OPTIONS:
            os.makedirs(os.path.join(coordsdir, src), exist_ok=True)
            outfile = os.path.join(coordsdir, src, f'coords_bounds_{stagg}.nc')
            logger.debug("Generating bounds for %s staggering %s", src, stagg)
            self.executor.run_python_script(
                'utils/generate-orca-bounds.py',
                ['--stagg', stagg, '--no-level', mesh_mask, outfile]
            )

    # ------------------------------------------------------------------
    # Step 2: Bathymetry pipeline (delegated to processor subclasses)
    # ------------------------------------------------------------------

    def process_bathymetry(self, cfg):
        """Instantiate the declared processor and run it."""
        processor = self._make_processor(cfg)
        processor.process()
        cfg['output_file'] = processor.output_file

    # ------------------------------------------------------------------
    # Step 3: Configure domain namelists
    # ------------------------------------------------------------------

    def configure_domain_namelists(self):
        """Generate NEMO DOMAINcfg namelist for each enabled bathymetry."""
        ecedir = self.paths['ecedir']
        outputdir = self.paths['outputdir']
        coords = self._target_bounds()

        # Write namelists into ecedir/DOMAINcfg if available (HPC), else outputdir
        namelist_dir = os.path.join(ecedir, 'DOMAINcfg') if ecedir else outputdir
        os.makedirs(namelist_dir, exist_ok=True)

        for cfg in self.bathymetries:
            name = cfg['name']
            # Use pre-computed path if available, otherwise derive it via the processor
            output_file = cfg.get('output_file') or self._make_processor(cfg).expected_output()
            if not os.path.isfile(output_file):
                raise FileNotFoundError(
                    f"Bathymetry file not found for '{name}': {output_file}\n"
                    "Run the bathymetry step first."
                )
            namelist_out = os.path.join(namelist_dir, f'namelist_cfg_{name}')
            logger.info("Generating namelist for %s: %s", name, namelist_out)
            self.executor.run_python_script(
                'domain-tools/config-namelist-domain.py',
                ['--bathymetry',  output_file,
                 '--coordinates', coords,
                 '--output',      namelist_out,
                 '--log-level',   self.log_level]
            )

    # ------------------------------------------------------------------
    # Step 4: Run domain configuration tool (HPC)
    # ------------------------------------------------------------------

    def run_domain_cfg(self):
        """Delegate HPC module loading + compilation + execution to run_domain_cfg.sh."""
        ecedir = self.paths['ecedir']
        names  = [cfg['name'] for cfg in self.bathymetries]
        clean  = '1' if self.steps.get('clean_domain_cfg', False) else '0'

        logger.info("Running domain configuration (HPC step, clean=%s)...", clean)
        self.executor.run_bash_script(
            'domain-tools/run_domain_cfg.sh',
            [ecedir, clean] + names
        )

    # ------------------------------------------------------------------
    # Step 5: Post-process domain_cfg + extract maskutil
    # ------------------------------------------------------------------

    def generate_mask_util(self):
        """Run generate-mask-util.py for each bathymetry (post-processes domain_cfg.nc
        and extracts maskutil.nc into the per-name output directory)."""
        ecedir    = self.paths['ecedir']
        outputdir = self.paths['outputdir']
        tgt       = self.grids['target']
        src_dir   = os.path.join(ecedir, 'DOMAINcfg')

        for cfg in self.bathymetries:
            name    = cfg['name']
            tgt_dir = os.path.join(outputdir, tgt, name)
            logger.info("Generating mask util for %s -> %s", name, tgt_dir)
            self.executor.run_python_script(
                'domain-tools/generate-mask-util.py',
                ['--src_dir', src_dir,
                 '--tgt_dir', tgt_dir]
            )

    # ------------------------------------------------------------------
    # Orchestrator
    # ------------------------------------------------------------------

    def run(self):
        if self.steps.get('coordinates'):
            logger.info("=== Step: Generate Coordinates ===")
            self.generate_coordinates()

        if self.steps.get('bathymetry'):
            logger.info("=== Step: Process Bathymetry ===")
            for cfg in self.bathymetries:
                self.process_bathymetry(cfg)

        if self.steps.get('configure_domain'):
            logger.info("=== Step: Configure Domain Namelists ===")
            self.configure_domain_namelists()

        if self.steps.get('domain_cfg'):
            logger.info("=== Step: Run Domain Configuration Tool ===")
            self.run_domain_cfg()

        if self.steps.get('generate_mask'):
            logger.info("=== Step: Generate Mask Util ===")
            self.generate_mask_util()

        logger.info("Workflow complete.")


def main():
    parser = argparse.ArgumentParser(description='NEMO bathymetry workflow')
    parser.add_argument('--config', default='nemo_workflow.yaml')
    parser.add_argument(
        '--only', nargs='+', metavar='NAME',
        help='Run only the specified bathymetry name(s) (e.g. --only present_day eocene)'
    )
    parser.add_argument(
        '-l', '--log-level', default='INFO', metavar='LEVEL',
        help='Logging level: DEBUG, INFO, WARNING (default: INFO)'
    )
    args = parser.parse_args()

    setup_logging(args.log_level)

    with open(args.config, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    NEMOWorkflow(config, only=args.only, log_level=args.log_level).run()


if __name__ == '__main__':
    main()
