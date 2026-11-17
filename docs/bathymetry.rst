Bathymetries
============

A NEMO domain starts from a bathymetry on the model grid. The ``bathymetry`` step of the NEMO
domain pipeline makes it from a source dataset, then DOMAINcfg builds the domain from it
(:doc:`configuration`, *Steps of the NEMO domain pipeline*). Each period has its own bathymetry:

.. list-table::
   :header-rows: 1
   :widths: 22 39 39

   * -
     - ``PresentDayBathymetry`` (``periods/present/bathymetry.py``)
     - ``EoceneBathymetry`` (``periods/eocene/bathymetry.py``)
   * - Source
     - ``bathy_metry`` of ``{input}/nemo/domain/eORCA1/domain_cfg.nc``
       (``present.nemo.source_grid``)
     - ``paleotopo`` of ``{herold}/herold_etal_stddev_subgrid_etopo1_to_eocene_1x1.nc``
   * - Convention
     - depth, positive in the ocean (``positive_depth``)
     - elevation, negative in the ocean (``negative_elevation``)
   * - Remapping
     - nearest neighbour (``remapnn``)
     - bilinear (``remapbil``)
   * - Corrections
     - strait corrections, then a land-sea mask plot
     - none
   * - Basin masks, sections
     - Atlantic, Pacific, Indian, Indo-Pacific, global; ``diadct`` sections
     - global only; no sections

How a bathymetry is made
------------------------

Both are subclasses of
:class:`~ecefast.components.nemo.bathymetry.base.BathymetryProcessor`, which runs the same CDO
chain for every source, in ``<machine.tmpdir>/<period>/nemo/bathymetry/PALEORCA2/``:

1. **Select** the variable of the source, renamed to ``bathy_metry`` if needed, on its own grid
   (or on the grid of ``setgrid``, for a NEMO source grid).
2. **Land-sea mask.** The source is turned into an ocean indicator (1 ocean, 0 land), remapped
   conservatively (``remapcon``) to the cell bounds of PALEORCA2, and thresholded at 0.5: a cell
   is ocean when at least half of it is ocean in the source. This is the step where the CDO version
   matters (see :ref:`data-version`).
3. **Depth.** The source is remapped with the method of the processor, the sign flipped for an
   elevation, and multiplied by the mask. Depths between 0 and ``minimum_depth`` are raised to it.
4. **Post-process**, if the processor defines it: for the present day, the strait corrections.

The result is ``<prefix>_bathy_metry_<remap>_to_PALEORCA2_T.nc`` (``_corrected.nc`` after a
post-process), which ``configure_domain`` writes into the DOMAINcfg namelist.

Strait corrections
~~~~~~~~~~~~~~~~~~

On a 2° grid many straits and enclosed seas come out wrong. The present-day corrections live in
``src/ecefast/components/nemo/config/bathymetry_corrections.yaml``, under a key
``<source grid>_to_<target grid>_<remap>``:

.. code-block:: yaml

   eORCA1_to_PALEORCA2_remapnn:
     open_regions:                 # [y, x]: the cell gets the mean depth of its ocean neighbours
       - region: Gibraltair
         cells: [[129, 132]]
     close_regions:                # [y0, y1, x0, x1], inclusive: the cells become land
       - region: Caspian
         cells: [[131, 140, 156, 159]]

Indices are 0-based on PALEORCA2 without halo (``y`` from south to north). A cell to open that is
ocean already is left as it is, with a warning. The corrections of
``eORCA1_to_PALEORCA2_remapnn`` reproduce the present-day domain of the existing experiments
(``data_version: v1``): do not change them without an agreed issue. The plot
``landsea_mask_comparison.png``, next to the corrected file, shows the result next to every
domain of the input tree.

Adding a bathymetry
-------------------

Bathymetries are not chosen in the configuration: each period passes its processor class to the
NEMO domain pipeline in code (``PresentNEMO.from_context`` in ``periods/present/pipeline.py``,
``EoceneDomain.from_context`` in ``periods/eocene/nemo/domain.py``). Three cases:

**The present day from another source grid** (e.g. a new eORCA domain). If the source has the
same variable and convention, no code is needed: set ``present.nemo.source_grid`` and add the
corrections of the new combination to ``bathymetry_corrections.yaml`` (without them the step
stops). Find the cells with ``--nemo coordinates,bathymetry`` and the land-sea mask plot, edit,
repeat.

**Another bathymetry for an existing period** (e.g. a different Eocene reconstruction, or the
Herold one with a gateway opened). Write a new class next to the current one, and pass it instead
of the current one in the period's step:

.. code-block:: python

   # src/ecefast/periods/eocene/bathymetry.py
   class MyEoceneBathymetry(BathymetryProcessor):
       """My Eocene reconstruction (Author et al., year)."""

       name = "my_eocene"                     # suffix of the DOMAINcfg namelist and raw files
       source_file = "{herold}/my_topography_1x1.nc"   # path template, expanded in the period
       variable = "topo"                      # variable in the source file
       rename_to = "bathy_metry"
       mask_type = "negative_elevation"       # or positive_depth; new conventions go in MASK_PRESETS
       remap_method = "remapbil"
       output_prefix = "MY_EOCENE"
       regional_subbasins = False             # the present-day basin polygons do not fit
       transport_sections = False             # the present-day sections do not fit

       def postprocess(self, remap_file, output_dir):
           """Optional: corrections after remapping; return the path of the final file."""
           return remap_file

.. code-block:: python

   # src/ecefast/periods/eocene/nemo/domain.py, EoceneDomain.from_context
   workflow = NEMOWorkflow.from_context(ctx, MyEoceneBathymetry, domain_dir, get_backend(ctx.config))

The source file must be one that CDO can remap (a regular lon/lat grid, or a grid given with
``setgrid``), and it must be a declared input: a file of ``eocene.herold`` or of the input tree, or a
new configuration key. The open and close helpers of the present day are in
``periods/present/bathymetry.py``; periods do not import each other, so to use them for another
period first move them to ``components/nemo/bathymetry/``.

**A new period** (e.g. the Pliocene): a new ``periods/<period>/`` package with its bathymetry,
steps and configuration section, following ``periods/eocene/``. See ``AGENTS.md``.

Before using it
~~~~~~~~~~~~~~~

- **Vertical grid.** The domain must keep the vertical grid of the present-day one; the ``domain``
  step checks it. The bathymetry changes only the horizontal mask and the depths.
- **Look at it.** Build the domain (``ecefast eocene run -c configs/atos.yml --steps stage,domain``)
  and check the remapped bathymetry in ``<machine.tmpdir>/eocene/nemo/bathymetry/PALEORCA2/`` and
  the domain in ``<machine.tmpdir>/eocene/nemo/domain/PALEORCA2/``, e.g. against the current one
  with ``scripts/compare_trees.py`` (ocean cells that change, ``bottom_level``). Closed seas and
  one-cell straits are what usually needs corrections.
- **Output changes.** Replacing the bathymetry of a period changes its output: the pull request
  says so, the changelog gets an *Output* entry, and the data no longer is ``v1``. Agree on it in
  an issue first.
- **Tests.** A unit test of the new processor on a small synthetic source file, and a run of the
  domain pipeline with it and the ``fake`` backend, as in ``tests/integration/test_nemo_domain.py``.
