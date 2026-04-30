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
import os
import subprocess

import yaml
from cdo import Cdo

from processors.base import BathymetryProcessor
from processors.present_day import PresentDayBathymetry
from processors.eocene import EoceneBathymetry

# Absolute path to the directory containing this script — used to locate
# helper scripts in utils/ and domain-tools/ regardless of the caller's cwd.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Registry: maps the processor name used in YAML to the class.
# Add a new entry here when adding a new processor.
PROCESSOR_REGISTRY = {
    'PresentDayBathymetry': PresentDayBathymetry,
    'EoceneBathymetry':     EoceneBathymetry,
}


class NEMOWorkflow:

    def __init__(self, config, only=None):
        profile_name = config.get('profile', 'default')
        profile = config['profiles'][profile_name]

        basedir = profile['basedir']
        self.paths = {
            'basedir':   basedir,
            'coordsdir': os.path.join(basedir, 'coordinates'),
            'bathydir':  os.path.join(basedir, 'bathymetry'),
            'outputdir': profile.get('outputdir', os.path.join(basedir, 'domain')),
            'domaindir': profile.get('domaindir', ''),
            'herolddir': profile.get('herolddir', ''),
            'ecedir':    profile.get('ecedir', ''),
        }

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

        self.cdo = Cdo()
        self._validate_paths()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_paths(self, cfg):
        """Substitute {coordsdir}, {domaindir} etc. in bathymetry config strings/lists."""
        def resolve(v):
            if isinstance(v, str):
                return v.format_map(self.paths)
            if isinstance(v, list):
                return [resolve(item) for item in v]
            return v
        return {k: resolve(v) for k, v in cfg.items()}

    def _validate_paths(self):
        for key, path in self.paths.items():
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
        tgt       = self.grids['target']
        src       = self.grids['source']
        coordsdir = self.paths['coordsdir']

        # Target grid: remove halo (NEMO 3.6 → 4.2 transition)
        coords_ori  = os.path.join(coordsdir, tgt, 'coords_ori.nc')
        coords_halo = os.path.join(coordsdir, tgt, 'coords_halo.nc')
        print(f"Removing halo from {coords_ori}")
        self.cdo.sethalo('-1,-1', input=coords_ori, output=coords_halo, options='-O')

        for stagg in ['T', 'F']:
            outfile = os.path.join(coordsdir, tgt, f'coords_bounds_{stagg}.nc')
            print(f"Generating bounds for {tgt} staggering {stagg}")
            subprocess.run(
                ['python3', os.path.join(_SCRIPT_DIR, 'utils', 'generate-orca-bounds.py'),
                 '--stagg', stagg, '--no-level', coords_halo, outfile],
                check=True
            )

        # Source grid: NEMO 4.2 mesh_mask (no halo removal needed)
        mesh_mask = os.path.join(coordsdir, src, 'mesh_mask.nc')
        for stagg in ['T', 'F']:
            outfile = os.path.join(coordsdir, src, f'coords_bounds_{stagg}.nc')
            print(f"Generating bounds for {src} staggering {stagg}")
            subprocess.run(
                ['python3', os.path.join(_SCRIPT_DIR, 'utils', 'generate-orca-bounds.py'),
                 '--stagg', stagg, '--no-level', mesh_mask, outfile],
                check=True
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
        ecedir    = self.paths['ecedir']
        outputdir = self.paths['outputdir']
        coords    = self._target_bounds()

        # Write namelists into ecedir/DOMAINcfg if available (HPC), else outputdir
        namelist_dir = os.path.join(ecedir, 'DOMAINcfg') if ecedir else outputdir
        os.makedirs(namelist_dir, exist_ok=True)

        for cfg in self.bathymetries:
            name        = cfg['name']
            # Use pre-computed path if available, otherwise derive it via the processor
            output_file = cfg.get('output_file') or self._make_processor(cfg).expected_output()
            if not os.path.isfile(output_file):
                raise FileNotFoundError(
                    f"Bathymetry file not found for '{name}': {output_file}\n"
                    "Run the bathymetry step first."
                )
            namelist_out = os.path.join(namelist_dir, f'namelist_cfg_{name}')
            print(f"Generating namelist for {name}: {namelist_out}")
            subprocess.run(
                ['python3', os.path.join(_SCRIPT_DIR, 'domain-tools', 'config-namelist-domain.py'),
                 '--bathymetry',  output_file,
                 '--coordinates', coords,
                 '--output',      namelist_out],
                check=True
            )

    # ------------------------------------------------------------------
    # Step 4: Run domain configuration tool (HPC)
    # ------------------------------------------------------------------

    def run_domain_cfg(self):
        """Delegate HPC module loading + compilation + execution to run_domain_cfg.sh."""
        ecedir    = self.paths['ecedir']
        outputdir = self.paths['outputdir']
        tgt       = self.grids['target']
        names     = [cfg['name'] for cfg in self.bathymetries]

        print("Running domain configuration (HPC step)...")
        subprocess.run(
            ['bash', os.path.join(_SCRIPT_DIR, 'domain-tools', 'run_domain_cfg.sh'),
             ecedir, outputdir, tgt] + names,
            check=True
        )

    # ------------------------------------------------------------------
    # Orchestrator
    # ------------------------------------------------------------------

    def run(self):
        if self.steps.get('coordinates'):
            print("=== Step: Generate Coordinates ===")
            self.generate_coordinates()

        if self.steps.get('bathymetry'):
            print("=== Step: Process Bathymetry ===")
            for cfg in self.bathymetries:
                self.process_bathymetry(cfg)

        if self.steps.get('configure_domain'):
            print("=== Step: Configure Domain Namelists ===")
            self.configure_domain_namelists()

        if self.steps.get('domain_cfg'):
            print("=== Step: Run Domain Configuration Tool ===")
            self.run_domain_cfg()

        print("\nWorkflow complete.")


def main():
    parser = argparse.ArgumentParser(description='NEMO bathymetry workflow')
    parser.add_argument('--config', default='nemo_workflow.yaml')
    parser.add_argument(
        '--only', nargs='+', metavar='NAME',
        help='Run only the specified bathymetry name(s) (e.g. --only present_day eocene)'
    )
    args = parser.parse_args()

    with open(args.config) as f:
        config = yaml.safe_load(f)

    NEMOWorkflow(config, only=args.only).run()


if __name__ == '__main__':
    main()
