"""
BathymetryProcessor: abstract base class for NEMO bathymetry processing.

Subclasses declare *what* to do by setting class-level attributes and optionally
overriding `postprocess()`.  The generic CDO pipeline (preprocess → land-sea
mask → remap) is inherited unchanged.

Two pipelines:

- data version v1 (``rule_based_geography = False``): conservative land-sea mask, depth remapped with
  ``remap_method``, then the subclass's ``postprocess()`` (manual corrections);
- data version v2 (``rule_based_geography = True``): conservative land-sea mask and conservative ocean-mean depth
  from the same remap, then the geography rules of :mod:`.geography` and the fixed sills of ``sills``.

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
from typing import ClassVar

import numpy as np
import xarray as xr

from ecefast.core.io import atomic_write

from .geography import T_PIVOT, apply_rules

logger = logging.getLogger(__name__)


# CDO operator chains and sign-flip flag per mask type.
# Add new entries here if a new input convention is needed.
# "depth" (v2 only): the positive depth of the source, 0 on land, before the conservative remap.
MASK_PRESETS = {
    "positive_depth": {
        "lsm_preprocess": "-setrtoc,0.0001,10000,1",
        "sign_flip": False,
        "depth": "-setrtoc,-100000,0,0",
    },
    "negative_elevation": {
        "lsm_preprocess": "-setrtoc,-10000,-0.0001,1 -setrtoc,0,10000,0",
        "sign_flip": True,
        "depth": "-mulc,-1 -setrtoc,0,100000,0",
    },
}

# North fold of the target grid: the DOMAINcfg namelist (domain/namelist_cfg.j2) sets jperio = 4, T-point pivot
NORTH_FOLD = T_PIVOT
# v2: the ocean fraction is rounded to this before the 0.5 threshold, so a cell at exactly 0.5 is ocean whatever
# the floating-point rounding of CDO (the 0.5 ties of data version v1, see DATA_VERSIONS in core/config.py)
FRACTION_DECIMALS = 6
OCEAN_THRESHOLD = 0.5
# v2 remaps: double precision, and -L (serialized I/O): a remapcon that reads from a chain of operators crashed in
# about 1 run in 4 with CDO 2.6.4 (Homebrew build, macOS) without it
REMAP_OPTIONS = "-O -L -b F64"


class BathymetryProcessor:
    """
    Base class for a bathymetry source.

    The domain pipeline creates one instance, calls ``process()`` and reads ``output_file`` for the
    result. Subclasses override the class attributes below.

    Attributes
    ----------
    name : str
        Suffix of the DOMAINcfg namelist and raw output files (``namelist_cfg_<name>``).
    source_file : str
        Path template of the source file, expanded in the running period (e.g. ``{herold}/file.nc``,
        ``{input}/nemo/domain/{nemo.source_grid}/domain_cfg.nc``).
    has_source_grid : bool
        The source is on a NEMO grid of the input tree (``<period>.nemo.source_grid``), whose cell bounds the
        coordinates step makes: they are the CDO grid description of the source (``setgrid``), and the output file
        name starts with ``<source grid>_T``.
    variable : str
        Variable name in the source NetCDF.
    rename_to : str or None
        Rename the variable to this before processing.
    setgrid : str or None
        CDO grid description file of the source.
    mask_type : str
        Key in ``MASK_PRESETS``.
    remap_method : str
        CDO remap operator (e.g. ``remapnn``, ``remapbil``).
    output_prefix : str or None
        Prefix of the output file name; defaults to ``cfg['name']``.
    regional_subbasins : bool
        ``subbasins.nc`` gets the Atlantic, Pacific, Indian and Indo-Pacific masks (present-day polygons);
        ``False``: the global mask only.
    transport_sections : bool
        The transport sections of NEMO diadct (present-day straits and passages, step ``sections``) fit this
        bathymetry; ``False``: the step is a configuration error.
    rule_based_geography : bool
        Data version v2: conservative land-sea mask and ocean-mean depth, then the geography rules
        (:func:`.geography.apply_rules`); ``remap_method`` must be ``remapcon``, and there is no ``postprocess()``.
    sills : dict
        v2: straits with a fixed sill depth, name -> ``(lon, lat, depth in m)``; the cell nearest to ``(lon, lat)``
        gets the depth and must be the only link between two basins (:func:`.geography.check_sills`).
    """

    name: str = ""
    source_file: str = ""
    has_source_grid: bool = False
    variable = None
    rename_to = None
    setgrid = None
    mask_type = None
    remap_method = None
    output_prefix = None
    regional_subbasins: bool = True
    transport_sections: bool = True
    rule_based_geography: bool = False
    sills: ClassVar[dict[str, tuple[float, float, float]]] = {}

    def __init__(self, cfg, paths, grids, params, cdo):
        """
        Parameters
        ----------
        cfg    : dict   — this bathymetry: name, source_file (expanded)
        paths  : dict   — resolved workflow paths (bathydir, coordsdir, …)
        grids  : dict   — target/source grid names and staggering
        params : dict   — workflow parameters (minimum_depth, …)
        cdo    : Cdo    — CDO Python binding instance
        """
        self.cfg = cfg
        self.paths = paths
        self.grids = grids
        self.params = params
        self.cdo = cdo
        if self.has_source_grid:
            # the cell bounds of the source grid (coordinates step), in the source staggering of the config
            src = grids["source"]
            stagg = grids.get("staggering_source", "T")
            self.setgrid = os.path.join(paths["coordsdir"], src, f"coords_bounds_{stagg}.nc")
            self.output_prefix = f"{src}_T"  # e.g. eORCA1_T_bathy_metry_remapnn_to_PALEORCA2_T.nc

        self.output_file = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(self):
        """Run the full pipeline.  Sets self.output_file on success."""
        name = self.cfg["name"]
        output_dir = self._output_dir()
        os.makedirs(output_dir, exist_ok=True)

        remap_file = self._remap_path()

        logger.info("Processing bathymetry: %s", name)
        preprocessed = lsm = None
        try:
            logger.debug("Preprocessing...")
            preprocessed = self._preprocess()

            if self.rule_based_geography:
                logger.debug("Conservative mask and depth, then the geography rules...")
                self._remap_rule_based(preprocessed, remap_file)
            else:
                logger.debug("Building land-sea mask...")
                lsm = self._build_lsm(preprocessed)

                logger.debug("Remapping...")
                self._remap(preprocessed, lsm, remap_file)

        finally:
            for tmp in [preprocessed, lsm]:
                if tmp and os.path.exists(tmp):
                    os.remove(tmp)

        self.output_file = self.postprocess(remap_file, output_dir)
        logger.debug("Done: %s", self.output_file)

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
        return os.path.join(output_dir, f"{stem}_corrected.nc")

    def reads(self) -> list[str]:
        """Files the pipeline reads: the source file, the target bounds and the source grid description (if any).

        Used by the input checks of the domain pipeline. Subclasses that read more files extend the list.
        """
        files = [self.cfg["source_file"], self._target_bounds()]
        if self.setgrid:
            files.append(self.setgrid)
        return files

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
        tmp = self._tmp()
        variable = self.variable
        rename = self.rename_to
        setgrid = self.setgrid
        src = self.cfg["source_file"]

        base_input = f"-setgrid,{setgrid} {src}" if setgrid else src

        if rename:
            self.cdo.chname(f"{variable},{rename}", input=f"-selname,{variable} {base_input}", output=tmp, options="-O")
        else:
            self.cdo.selname(variable, input=base_input, output=tmp, options="-O")

        return tmp

    def _build_lsm(self, preprocessed):
        """Conservative remapping + thresholding → binary land-sea mask."""
        preset = MASK_PRESETS[self.mask_type]
        target_bounds = self._target_bounds()
        tmp = self._tmp()

        self.cdo.setrtoc(
            "0,0.5,0",
            input=f"-setrtoc,0.5,1,1 -remapcon,{target_bounds} {preset['lsm_preprocess']} {preprocessed}",
            output=tmp,
            options="-O",
        )
        return tmp

    def _remap(self, preprocessed, lsm, output_file):
        """Remap to target grid, apply land-sea mask and minimum depth."""
        preset = MASK_PRESETS[self.mask_type]
        target_bounds = self._target_bounds()
        min_depth = self.params["minimum_depth"]

        if preset["sign_flip"]:
            remap_chain = f"-mul {lsm} -mulc,-1 -setrtoc,0,10000,0 -{self.remap_method},{target_bounds} {preprocessed}"
        else:
            remap_chain = f"-mul {lsm} -{self.remap_method},{target_bounds} {preprocessed}"

        self.cdo.setrtoc(f"0.00001,{min_depth},{min_depth}", input=remap_chain, output=output_file, options="-O")

    def _remap_rule_based(self, preprocessed, output_file):
        """Data version v2: conservative mask and ocean-mean depth, the sills, then the geography rules.

        Both come from one conservative remap: the ocean fraction of each target cell, and the area-weighted sum of
        the source depth (0 on land). A cell is ocean if its fraction, rounded to ``FRACTION_DECIMALS``, is at least
        ``OCEAN_THRESHOLD``; its depth is the sum divided by the fraction (the mean depth of its ocean part), at
        least ``minimum_depth``. The output keeps the grid and variable of the CDO remap.
        """
        if self.remap_method != "remapcon":
            raise ValueError(f"{type(self).__name__}: rule_based_geography needs remap_method remapcon")
        preset = MASK_PRESETS[self.mask_type]
        target_bounds = self._target_bounds()
        min_depth = self.params["minimum_depth"]
        fraction_file, depth_file = self._tmp(), self._tmp()
        try:
            self.cdo.remapcon(
                target_bounds,
                input=f"{preset['lsm_preprocess']} {preprocessed}",
                output=fraction_file,
                options=REMAP_OPTIONS,
            )
            self.cdo.remapcon(
                target_bounds, input=f"{preset['depth']} {preprocessed}", output=depth_file, options=REMAP_OPTIONS
            )
            with xr.open_dataset(fraction_file) as ds:
                fraction = ds[self.variable_name()].squeeze().values
            with xr.open_dataset(depth_file) as ds:
                result = ds.load()
        finally:
            for tmp in (fraction_file, depth_file):
                if os.path.exists(tmp):
                    os.remove(tmp)

        var = result[self.variable_name()]
        ocean = np.round(fraction, FRACTION_DECIMALS) >= OCEAN_THRESHOLD
        mean_depth = var.squeeze().values / np.where(ocean, fraction, 1.0)
        depth = np.where(ocean, np.maximum(mean_depth, min_depth), 0.0)

        report = apply_rules(
            ocean,
            depth,
            fraction,
            min_depth,
            NORTH_FOLD,
            lon=result["lon"].values,
            lat=result["lat"].values,
            sills=self.sills,
        )
        logger.info(
            "Geography rules: opened %d corner contacts, removed %d closed seas (%d cells), %d inlet cells, "
            "%d isolated islands; sills: %s",
            len(report.opened_corners),
            len(report.closed_seas),
            sum(report.closed_seas),
            report.removed_inlets,
            len(report.removed_islands),
            ", ".join(f"{name} {depth_m:.0f} m" for name, (_, _, depth_m) in self.sills.items()) or "none",
        )

        result[var.name] = var.copy(data=depth.reshape(var.shape).astype(var.dtype))
        result.attrs["history"] = (
            f"{result.attrs.get('history', '')}\necefast: ocean-mean depth of the conservative remap, "
            "geography rules and sills (data version v2)"
        ).strip()
        with atomic_write(output_file) as tmp:
            result.to_netcdf(tmp)

    def variable_name(self) -> str:
        """Name of the bathymetry variable after preprocessing."""
        return self.rename_to or self.variable

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _has_postprocess(self):
        """True if the subclass overrides postprocess()."""
        return type(self).postprocess is not BathymetryProcessor.postprocess

    def _output_dir(self):
        tgt = self.grids["target"]
        return os.path.join(self.paths["bathydir"], tgt)

    def _remap_path(self):
        tgt = self.grids["target"]
        stagg = self.grids["staggering_target"]
        prefix = self.output_prefix or self.cfg["name"]
        return os.path.join(self._output_dir(), f"{prefix}_bathy_metry_{self.remap_method}_to_{tgt}_{stagg}.nc")

    def _target_bounds(self, staggering=None):
        s = staggering or self.grids["staggering_target"]
        tgt = self.grids["target"]
        return os.path.join(self.paths["coordsdir"], tgt, f"coords_bounds_{s}.nc")

    def _tmp(self):
        f = tempfile.NamedTemporaryFile(suffix=".nc", delete=False)
        f.close()
        return f.name
