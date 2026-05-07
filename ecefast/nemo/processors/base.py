"""
BathymetryProcessor: abstract base class for NEMO bathymetry processing.

Subclasses declare *what* to do by setting class-level attributes and optionally
overriding `postprocess()`.  The generic CDO pipeline (preprocess → land-sea
mask → remap) is inherited unchanged.

Minimal subclass example
------------------------
    class MyBathymetry(BathymetryProcessor):
        variable     = 'depth'
        mask_type    = 'positive_depth'
        remap_method = 'remapbil'
        output_prefix = 'MY_GRID'
"""

import logging
import os
import tempfile

logger = logging.getLogger("nemo.processors")


# CDO operator chains and sign-flip flag per mask type.
# Add new entries here if a new input convention is needed.
MASK_PRESETS = {
    'positive_depth': {
        'lsm_preprocess': '-setrtoc,0.0001,10000,1',
        'sign_flip': False,
    },
    'negative_elevation': {
        'lsm_preprocess': '-setrtoc,-10000,-0.0001,1 -setrtoc,0,10000,0',
        'sign_flip': True,
    },
}


class BathymetryProcessor:
    """
    Base class for a bathymetry source.

    Instance is created once per YAML entry.  The workflow calls
    `processor.process()` and reads `processor.output_file` for the result.

    Class-level attributes (override in subclasses)
    -----------------------------------------------
    variable      : str   — variable name in the source NetCDF
    rename_to     : str | None — rename variable to this before processing
    setgrid       : str | None — CDO grid description file for source
    mask_type     : str   — key in MASK_PRESETS
    remap_method  : str   — CDO remap operator (e.g. remapnn, remapbil)
    output_prefix : str | None — prefix for output filename; defaults to cfg['name']
    """

    variable      = None
    rename_to     = None
    setgrid       = None
    mask_type     = None
    remap_method  = None
    output_prefix = None

    def __init__(self, cfg, paths, grids, params, cdo):
        """
        Parameters
        ----------
        cfg    : dict   — YAML entry for this bathymetry (name, source_file, etc.)
        paths  : dict   — resolved workflow paths (bathydir, coordsdir, …)
        grids  : dict   — target/source grid names and staggering
        params : dict   — workflow parameters (minimum_depth, …)
        cdo    : Cdo    — CDO Python binding instance
        """
        self.cfg    = cfg
        self.paths  = paths
        self.grids  = grids
        self.params = params
        self.cdo    = cdo

        self.output_file = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(self):
        """Run the full pipeline.  Sets self.output_file on success."""
        name       = self.cfg['name']
        output_dir = self._output_dir()
        os.makedirs(output_dir, exist_ok=True)

        remap_file = self._remap_path()

        logger.info("Processing bathymetry: %s", name)
        preprocessed = lsm = None
        try:
            logger.debug("Preprocessing...")
            preprocessed = self._preprocess()

            logger.debug("Building land-sea mask...")
            lsm = self._build_lsm(preprocessed)

            logger.debug("Remapping...")
            self._remap(preprocessed, lsm, remap_file)

        finally:
            for tmp in [preprocessed, lsm]:
                if tmp and os.path.exists(tmp):
                    os.remove(tmp)

        self.output_file = self.postprocess(remap_file, output_dir)
        logger.info("Done: %s", self.output_file)

    def postprocess(self, remap_file, output_dir):
        """
        Optional ad-hoc corrections after remapping.

        Default implementation is a no-op.  Override in subclasses to apply
        corrections, write plots, etc.

        Parameters
        ----------
        remap_file : str  — path to the remapped NetCDF file
        output_dir : str  — directory to write derived outputs into

        Returns
        -------
        str — path to the final output file (may be remap_file itself)
        """
        return remap_file

    def corrected_output(self, remap_file, output_dir):
        """Return the standard _corrected.nc path for a given remap file."""
        stem = os.path.splitext(os.path.basename(remap_file))[0]
        return os.path.join(output_dir, f'{stem}_corrected.nc')

    def expected_output(self):
        """
        Return the deterministic final output path without running the pipeline.

        Used by configure_domain_namelists() to locate outputs from a previous run.
        """
        remap_file = self._remap_path()
        if self._has_postprocess():
            return self.corrected_output(remap_file, self._output_dir())
        return remap_file

    # ------------------------------------------------------------------
    # Private pipeline steps
    # ------------------------------------------------------------------

    def _preprocess(self):
        """Rename variable and/or assign source grid.  Returns tempfile path."""
        tmp      = self._tmp()
        variable = self.variable
        rename   = self.rename_to
        setgrid  = self.setgrid
        src      = self.cfg['source_file']

        base_input = f'-setgrid,{setgrid} {src}' if setgrid else src

        if rename:
            self.cdo.chname(
                f'{variable},{rename}',
                input=f'-selname,{variable} {base_input}',
                output=tmp, options='-O'
            )
        else:
            self.cdo.selname(variable, input=base_input, output=tmp, options='-O')

        return tmp

    def _build_lsm(self, preprocessed):
        """Conservative remapping + thresholding → binary land-sea mask."""
        preset        = MASK_PRESETS[self.mask_type]
        target_bounds = self._target_bounds()
        tmp           = self._tmp()

        self.cdo.setrtoc(
            '0,0.5,0',
            input=f'-setrtoc,0.5,1,1 -remapcon,{target_bounds} '
                  f'{preset["lsm_preprocess"]} {preprocessed}',
            output=tmp, options='-O'
        )
        return tmp

    def _remap(self, preprocessed, lsm, output_file):
        """Remap to target grid, apply land-sea mask and minimum depth."""
        preset        = MASK_PRESETS[self.mask_type]
        target_bounds = self._target_bounds()
        min_depth     = self.params['minimum_depth']

        if preset['sign_flip']:
            remap_chain = (
                f'-mul {lsm} -mulc,-1 -setrtoc,0,10000,0 '
                f'-{self.remap_method},{target_bounds} {preprocessed}'
            )
        else:
            remap_chain = (
                f'-mul {lsm} -{self.remap_method},{target_bounds} {preprocessed}'
            )

        self.cdo.setrtoc(
            f'0.00001,{min_depth},{min_depth}',
            input=remap_chain,
            output=output_file, options='-O'
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _has_postprocess(self):
        """True if the subclass overrides postprocess()."""
        return type(self).postprocess is not BathymetryProcessor.postprocess

    def _output_dir(self):
        tgt = self.grids['target']
        return os.path.join(self.paths['bathydir'], tgt)

    def _remap_path(self):
        tgt    = self.grids['target']
        stagg  = self.grids['staggering_target']
        prefix = self.output_prefix or self.cfg['name']
        return os.path.join(
            self._output_dir(),
            f'{prefix}_bathy_metry_{self.remap_method}_to_{tgt}_{stagg}.nc'
        )

    def _target_bounds(self, staggering=None):
        s   = staggering or self.grids['staggering_target']
        tgt = self.grids['target']
        return os.path.join(self.paths['coordsdir'], tgt, f'coords_bounds_{s}.nc')

    def _tmp(self):
        f = tempfile.NamedTemporaryFile(suffix='.nc', delete=False)
        f.close()
        return f.name
