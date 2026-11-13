Workflow
========

Each time period is a *pipeline*: an ordered list of *steps*, run by one runner
(:mod:`ecefast.core.runner`). Each step belongs to one component (``oifs``, ``nemo``, ``oasis``,
``rnfm``; ``stage`` to none).

.. code-block:: python

   # src/ecefast/periods/present/pipeline.py
   PIPELINE = [PresentOIFS, PresentNEMO]                                        # steps oifs, nemo

   # src/ecefast/periods/eocene/pipeline.py
   PIPELINE = [Stage, EoceneDomain, EoceneOASIS, EoceneOIFS, EoceneNEMO, EoceneRNFM]

Running it
----------

.. code-block:: bash

   ecefast eocene run -c configs/laptop.yml                  # every step, into an empty output directory
   ecefast eocene run -c configs/laptop.yml --overwrite      # every step, replacing an existing output directory
   ecefast eocene run -c configs/laptop.yml --steps nemo     # rerun one step on an existing output directory
   ecefast eocene run -c configs/laptop.yml --dry-run        # check all inputs and show the plan; write nothing
   ecefast eocene steps                                      # list the steps: what each needs, reads and writes
   ecefast present run -c configs/atos.yml                   # the present-day period (OIFS inputs on Atos only)
   ecefast nemo run -c configs/laptop.yml                    # the nemo step of the present day
   ecefast nemo run -c configs/laptop.yml --period eocene    # the nemo steps of the Eocene: domain, nemo

Options of ``ecefast <period> run`` (``present``, ``eocene``):

.. code-block:: text

   -c, --config      Configuration file (schema 2) with a section for the period. Required.
   --steps a,b       Comma-separated step names; they run in pipeline order. Default: all steps.
   --oifs a,b        Run only these steps of <period>.oifs.steps (spectral, gridpoint, boundary).
   --nemo a,b        Run only these steps of <period>.nemo.steps (coordinates, bathymetry,
                     configure_domain, domain_cfg, generate_mask, generate_subbasins).
   --dry-run         Check all inputs and show the plan; write nothing.
   --overwrite       Replace existing outputs, after a warning and a 5 s pause (Ctrl-C to stop).
   -l, --loglevel    Log level (DEBUG, INFO, WARNING, ...). Default: INFO.

``ecefast <component> run`` (``oifs``, ``nemo``, ``oasis``, ``rnfm``) has the same options except
``--steps``, plus ``--period present|eocene`` (default ``present``); of ``--oifs`` and ``--nemo``
it has only its own. It runs the steps of that component in that period; a period without one
(``ecefast oasis run`` in the present day) is an error.

``--oifs`` and ``--nemo`` replace the configured ``steps`` of that component's section for one
run; every step not listed is off. Only ``present.oifs``, ``present.nemo`` and ``eocene.nemo``
have steps (``eocene.nemo.steps`` are used with ``eocene.nemo.domain: build``):

.. code-block:: bash

   ecefast nemo run -c configs/laptop.yml --nemo coordinates,bathymetry
   ecefast eocene run -c configs/atos.yml --steps stage,domain --nemo configure_domain,domain_cfg,generate_mask

Both periods start with ``stage``, which copies the base files into the period's ``output``. A run
with ``stage`` makes a new output tree atomically: every step writes into ``<output>.partial``,
next to the output, which replaces ``output`` only when all the steps have succeeded. A failed run
leaves ``output`` as it was and keeps the partial tree for inspection; the next run removes it. If
``output`` holds files, the run stops with an error unless ``--overwrite`` is given: then it logs a
warning, waits 5 s (Ctrl-C to stop), and the old tree is replaced at the end.

``--steps`` without ``stage`` (and ``ecefast <component> run``) runs on an existing output
directory, writing each file atomically in place: a needed step that is not selected (here
``stage``) must have run before, i.e. all its ``writes`` exist. The present-day steps then refuse
final files that exist already unless ``--overwrite`` is given, with the same warning and pause.

.. code-block:: bash

   ecefast present run -c configs/atos.yml --steps stage,nemo     # first time: a new present-day tree
   ecefast nemo run -c configs/atos.yml --overwrite                # later: rerun nemo on that tree

The run logs the CDO version first. On a usage error (bad configuration, missing input, unknown
step, existing output) the command logs one error and exits with code 1.

A dry run checks everything and logs the plan, one line per step. A run and a dry run both end
with a recap of the files written (or that would be written), grouped by the period's ``output``,
``machine.tmpdir`` and other places such as the DOMAINcfg directory. A dry run marks files that
exist already with ``(exists)``; a run marks a file that is not there with ``(not found)``. The
steps log at INFO; the files of each step, and each file copied or written, at DEBUG
(``-l DEBUG``). Paths shortened here:

.. code-block:: text

   $ ecefast eocene run -c configs/laptop.yml --dry-run
   INFO -> CDO version: 2.6.4
   INFO -> Dry run: nothing is written. Plan:
   INFO ->   stage   Copy base files from the input tree to the output tree.
   INFO ->   domain  Install the Eocene NEMO domain (eocene.nemo.domain: a directory, or build) and check its vertical grid.
   INFO ->   oasis   Write the OASIS restart rstos.nc: no sea ice, constant SST.
   INFO ->   oifs    Modify the OIFS initial and climate files for the Eocene (Herold et al. 2014).
   INFO ->   nemo    Modify NEMO input files for the Eocene: tidal mixing, geothermal flux, ocean initial state, runoff.
   INFO ->   rnfm    Write the runoff-mapper basins from the Herold et al. (2014) river flow direction.
   INFO -> Files that would be written (17):
     in eocene.output (OUTPUT/eocene):
       oifs
       nemo
       oasis/PALEORCA2
       nemo/domain/PALEORCA2/domain_cfg.nc
       ...
       runoff-mapper/runoff_maps.nc

Provenance
~~~~~~~~~~

At the end of a successful run (not a dry run) the runner writes ``provenance.yml`` into the
``output`` of the period, atomically. It replaces the one of an earlier run.

.. code-block:: yaml

   steps: [stage, domain, oasis, oifs, nemo, rnfm]
   config:
     file: /path/to/configs/laptop.yml
     sha256: 3f1c...                 # of the configuration file
   ecefast:
     version: 0.0.2
     git_commit: 821b4e4...          # "unknown" if the package is not in a git checkout
   versions:
     python: 3.14.10
     cdo: 2.6.4                      # the CDO binary used by the run
     eccodes: 2.47.0                 # 'codes_info -v' of the ecCodes tools on PATH
   start: '2026-11-12T12:20:01+01:00'
   end: '2026-11-12T12:20:49+01:00'

``scripts/compare_outputs.py`` ignores ``provenance.yml``.

Checks after the run
~~~~~~~~~~~~~~~~~~~~

After ``provenance.yml``, an Eocene run checks the outputs of the steps that ran
(``ecefast.periods.eocene.verify``) and fails, listing every problem, if:

- a path declared in ``writes`` is missing;
- a NetCDF file declared in ``writes`` has NaN in a data variable. Values are read raw: a masked
  point stored as a ``_FillValue`` such as ``-999`` is fine, a NaN is not (EC-Earth reads the raw
  values), even when ``_FillValue`` is NaN;
- ``domain`` ran and the installed Eocene ``domain_cfg.nc`` does not have the vertical grid of the
  present-day one (the same check as the ``domain`` step).

.. code-block:: text

   ERROR -> Verify: the run finished but its output is wrong:
     NaN in sorunoff of OUTPUT/eocene/nemo/climatology/runoff_DaiTrenberth_PALEORCA2.nc

The Eocene steps
----------------

In the paths below ``{input}``, ``{output}`` and ``{herold}`` are ``eocene.input``,
``eocene.output`` and ``eocene.herold``.

``stage`` (``Stage``)
   Copies the base files from the input tree to the output tree; see :ref:`stage-step`.

``domain`` (``EoceneDomain``, component ``nemo``)
   Needs ``stage``. Installs ``domain_cfg.nc`` and ``maskutil.nc`` in
   ``{output}/nemo/domain/{grids.nemo.name}/``. ``eocene.nemo.domain`` says where they come from:

   - a directory holding ``domain_cfg.nc`` and ``maskutil.nc``, e.g. the domain built on Atos and
     copied to a laptop: the step copies them;
   - ``build``: the step first runs the NEMO domain pipeline (below) with ``EoceneBathymetry``, the
     steps of ``eocene.nemo.steps`` and ``eocene.nemo.minimum_depth``, on ``machine.name``
     (:doc:`external_tools`). Intermediate and final files go to ``<machine.tmpdir>/eocene/nemo/``
     (final files in ``domain/{grids.nemo.name}/``); then the step installs the two files.
     ``build`` with ``machine.name: local`` is a configuration error.

   Then it checks the vertical grid rule: the installed Eocene domain must have the same number of
   levels as the present-day ``{input}/nemo/domain/{grids.nemo.name}/domain_cfg.nc``, and
   ``nav_lev`` and ``e3t_1d`` within 1e-6 m (rounding). On a mismatch the pipeline stops with an
   error naming both files and their number of levels. Why: ``nemo`` builds the ocean initial state
   on the present-day levels. ``reads`` lists only the present-day domain: what else the step reads
   depends on ``eocene.nemo.domain``, which a class-level list cannot express, so the files in the
   directory, or the inputs of the domain pipeline (``build``), are checked when the step is built,
   not in the preflight.

``oasis`` (``EoceneOASIS``)
   Needs ``stage``. Reads ``{input}/initial_state/oasis/{grids.nemo.name}/default/rstos.nc``, writes
   ``{output}/initial_state/oasis/{grids.nemo.name}/default/rstos.nc``: the present-day OASIS restart with sea ice
   removed (``OIceFrc``, ``OIceTck``, ``OSnwTck``, ``O_AlbIce``, ``O_TepIce`` set to 0) and a
   constant SST (``eocene.oasis.constant_sst``, default 290 K) in ``O_SSTSST``.

``oifs`` (``EoceneOIFS``)
   Needs ``stage``. Reads the OIFS initial and climate GRIB files of the input tree
   (``initial_state/oifs/{grids.oifs.name}/{grids.oifs.startdate}/ICMGGECE4INIT``, ``ICMGGECE4INIUA``,
   ``ICMSHECE4INIT``; ``oifs/{grids.oifs.name}/{grids.oifs.climate_version}/ICMCLECE4``,
   ``bare_soil_albedos.grb``) and the Herold et al. (2014) topography, subgrid orography and
   biomes. Remaps the Herold fields to the model grid (intermediate files in
   ``<machine.tmpdir>/eocene/oifs``), then writes Eocene versions of the same five files in the
   output tree: land-sea mask, orography, subgrid orography and slope, vegetation, soil type,
   albedos and LAI, dry atmosphere (humidity and clouds set to zero), spectral fields truncated to
   the mean. With ``eocene.oifs.aerosols: true`` it also writes
   ``oifs/ifsdata/IFS_aerosol_climatology_PI.nc`` from the Herold aerosols.

``nemo`` (``EoceneNEMO``)
   Needs ``stage`` (not ``domain``: it reads only present-day domains, on purpose).
   Reads the present-day tidal mixing, geothermal flux and runoff files from ``{input}/nemo``, WOA13
   from ``{input}/initial_state/nemo/ts_state``, the ``{grids.nemo.name}`` and ORCA2 present-day domains (ORCA2 is always the
   reference mask of the ``woa-pi`` profile), and the Herold tidal dissipation, topography and
   ocean-age files. Writes ``nemo/initial/zdfiwm_forcing_r720x360.nc`` (Eocene M2 tidal dissipation
   and bathymetry), ``nemo/initial/Goutorbe_ghflux.nc`` (geothermal flux from Eocene ocean-floor
   age), the three ocean initial states in ``initial_state/nemo/ts_state/``: ``deepmip-L31_cold-30.nc`` and
   ``deepmip-L31_warm-34.nc`` (idealised DeepMIP profiles, 30 and 34 °C at the equator surface, 10 and 15 °C at
   depth) and ``woa13-levitus-L31_woa-pi.nc`` (zonal mean of WOA13), and ``nemo/climatology/runoff_DaiTrenberth_{grids.nemo.name}.nc`` (runoff set to zero;
   the runoff mapper handles rivers).

``rnfm`` (``EoceneRNFM``)
   Needs ``stage``. Reads ``{herold}/herold_etal_eocene_runoff_1x1.nc`` and
   ``{input}/runoff-mapper/runoff_maps.nc``, writes ``{output}/runoff-mapper/runoff_maps.nc``.
   Tracks river basins on the Herold et al. (2014) 1x1 river flow direction, merges small basins,
   and regrids ``drainage_basin_id``, ``arrival_point_id`` and ``calving_point_id`` (nearest
   neighbour, xESMF) to the runoff-mapper grid. ``calving_point_id`` equals ``arrival_point_id``
   (no ice sheets in the Eocene).

``ecefast eocene steps`` prints the exact ``component``, ``needs``, ``reads`` and ``writes`` of
each step.

The present-day steps
---------------------

``ecefast present run`` has three steps. ``stage`` copies the base files of ``present.input`` into
``present.output`` (:ref:`stage-step`), so the output is a complete EC-Earth tree the Eocene can
start from (``eocene.input: "{present.output}"``). ``oifs`` and ``nemo`` need ``stage``; they read
``present.input`` and write their final files into ``present.output``, laid out as in ECE4-DATA,
replacing the copied ones; intermediate files go to ``<machine.tmpdir>/present/<component>/``.
They do not declare ``reads`` and ``writes`` (they depend on the configured steps): each checks its
inputs, and on an existing tree refuses existing final files without ``--overwrite``, when it is
built, before the first step runs.

``nemo`` (``PresentNEMO``)
   The NEMO domain pipeline (below) with ``PresentDayBathymetry``, the steps of
   ``present.nemo.steps`` and ``present.nemo.minimum_depth``. Final files:
   ``{output}/nemo/domain/{grids.nemo.name}/domain_cfg.nc``, ``maskutil.nc``, ``subbasins.nc``.
``oifs`` (``PresentOIFS``)
   The OIFS generator (below). Final files: ``{output}/initial_state/oifs/{grids.oifs.name}/{grids.oifs.startdate}/``
   and ``{output}/oifs/{grids.oifs.name}/{grids.oifs.climate_version}/``.

``ecefast present run`` skips a step whose component has no section in ``present``: on a laptop,
where the template has no ``present.oifs`` (its inputs exist on Atos only), it runs ``stage`` and
``nemo``. Selecting ``oifs`` explicitly (``--steps oifs`` or
``ecefast oifs run``) without the section is an error.

NEMO domain pipeline
--------------------

:class:`~ecefast.components.nemo.domain.pipeline.NEMOWorkflow` builds the NEMO domain of one
bathymetry on the grid of ``grids.nemo`` (:doc:`configuration`). It runs as the ``nemo`` step of
the present day and inside the Eocene ``domain`` step with ``eocene.nemo.domain: build``:

.. code-block:: bash

   ecefast nemo run -c configs/laptop.yml                        # present day, the configured steps
   ecefast nemo run -c configs/laptop.yml -l DEBUG               # more logging
   ecefast nemo run -c configs/laptop.yml --dry-run              # check all inputs and show the plan; write nothing
   ecefast nemo run -c configs/atos.yml --period eocene          # Eocene: domain (with build) and nemo

Its steps, each switched on or off in ``<period>.nemo.steps`` (or ``--nemo a,b``):
``coordinates`` (PALEORCA2 without halo, cell bounds), ``bathymetry`` (the processor of the
period), ``configure_domain`` (the DOMAINcfg namelist), ``domain_cfg`` (DOMAINcfg, through the
backend of ``machine.name``, see :doc:`external_tools`), ``generate_mask`` (``domain_cfg.nc`` and
``maskutil.nc``) and ``generate_subbasins`` (``subbasins.nc``: Atlantic, Pacific, Indian,
Indo-Pacific and global masks). On a laptop the last three are off.

The intermediate files go to ``<machine.tmpdir>/<period>/nemo/``: ``coordinates/``,
``bathymetry/``, and ``domaincfg/`` with the namelist and raw DOMAINcfg output. On Atos the
namelist and raw output go to ``<machine.atos.ecearth4_sources>/nemo-4.2/tools/DOMAINcfg/``,
where DOMAINcfg runs. The final files go to the folder the period gives: the present-day
``{output}/nemo/domain/{grids.nemo.name}/``, or ``<machine.tmpdir>/eocene/nemo/domain/{grids.nemo.name}/``
for the Eocene build.

The present-day bathymetry is the one of ``{input}/nemo/domain/<present.nemo.source_grid>/domain_cfg.nc``
(``eORCA1`` by default), remapped by nearest neighbour; then strait corrections are applied. The
corrections are looked up in ``bathymetry_corrections.yaml`` by source grid, target grid and remap
method (e.g. ``eORCA1_to_PALEORCA2_remapnn``); a source grid without corrections is a
configuration error. The step also plots the land-sea mask of the result next to the one of every
``{input}/nemo/domain/*/domain_cfg.nc``, one panel each, in
``<machine.tmpdir>/present/nemo/bathymetry/{grids.nemo.name}/landsea_mask_comparison.png``.

Before the first step, the pipeline checks that every file an enabled step reads exists or is
written by an earlier enabled step, and lists all missing ones at once. ``--dry-run`` does only
this check and logs the enabled steps with the files each writes.

The regional subbasins are fixed lon/lat polygons drawn on present-day geography. On the Eocene
domain they leave some ocean unassigned and cut some basins in the wrong place
(``notebooks/analysis/eocene-subbasins.ipynb`` plots them and lists the problems and the options).
So a bathymetry processor decides with the class attribute ``regional_subbasins``: ``True`` for
``PresentDayBathymetry`` (all five masks), ``False`` for ``EoceneBathymetry``, whose
``subbasins.nc`` has the global mask ``glomsk`` only, until Eocene basins are defined in a separate
task. Details of each step are in
``src/ecefast/components/nemo/domain/NEMO_WORKFLOW_STEPS.md``.

Bathymetries are not configured: each period passes its own processor class to
:class:`~ecefast.components.nemo.domain.pipeline.NEMOWorkflow`,
``ecefast.periods.present.bathymetry.PresentDayBathymetry`` or
``ecefast.periods.eocene.bathymetry.EoceneBathymetry``. A processor declares its source file as a
path template (``source_file``) and holds every algorithm choice (variable, mask, remapping,
corrections). The NEMO component never imports ``periods``. To add a paleo bathymetry, subclass
``BathymetryProcessor`` under ``ecefast/periods/<period>/`` and pass it where that period builds
the pipeline.

OIFS generator
--------------

The ``oifs`` step of the present day (``ecefast oifs run``) makes the OIFS base data of
``grids.oifs`` from the one of ``present.oifs.source_grid`` in the input tree, following the
``present.oifs`` section of the configuration (:doc:`configuration`). Its inputs (TL255L91, the
ECMWF climate fields, the grids with cell corners) exist on ECMWF Atos only:

.. code-block:: bash

   ecefast oifs run -c configs/atos.yml --dry-run    # check all inputs and show the plan; write nothing
   ecefast oifs run -c configs/atos.yml              # run the enabled steps

Its steps, switched on or off in ``present.oifs.steps`` (or ``--oifs a,b``):

``spectral`` (on)
   Truncates ``ICMSHECE4INIT`` to the target spectral resolution (``cdo sp2sp``).
``gridpoint`` (on)
   Remaps ``ICMGGECE4INIT`` and ``ICMGGECE4INIUA`` to the target reduced Gaussian grid by nearest neighbour
   (``cdo remapnn``), GRIB1 and GRIB2 messages separately, then joins them (all GRIB1, then all GRIB2).
``boundary`` (off)
   The climate file: copies ``<precomputed_climate_dir>/<grid>/<climate_version>/ICMCLECE4`` if it exists,
   else merges the monthly albedo and leaf area index fields of ``climate_dir`` into ``ICMCLECE4-1990``.

When ``spectral`` or ``boundary`` is on, the three initial-state files go to
``<present.output>/initial_state/oifs/<grid>/<startdate>/``: moved from the intermediate folder when the source and
target have the same number of levels, else interpolated vertically first (``cdo remapeta`` with the hybrid
coefficients of ``grids/L<levels>.txt``; the conservative remapping to the reduced Gaussian grid needs the cell
corners of the target grid, so ``corners`` first writes ``<machine.tmpdir>/present/oifs/T<kind><N>_grid.nc`` from
the ``ICMGGECE4INIT`` of ``gridpoint``; temperature, divergence and vorticity through the Gaussian grid and
back to spectral, moisture and cloud fields on the reduced Gaussian grid, orography and surface pressure
unchanged). The climate file goes to ``<present.output>/oifs/<grid>/<climate_version>/``. ``<grid>``,
``<startdate>`` and ``<climate_version>`` come from ``grids.oifs``. Intermediate files stay in
``<machine.tmpdir>/present/oifs/``, so a step can be rerun alone on the intermediate files of an earlier run.
Nothing is written into the input tree.

Before the first step the command checks that every file an enabled step reads exists (or is written by an
earlier step), and lists all missing ones at once; ``--dry-run`` does only this and logs the plan.

The code of the component follows these processes: ``generator`` plans, checks and runs them; ``initial_state``
holds ``spectral``, ``gridpoint``, the install and the vertical interpolation; ``climate`` holds ``boundary``;
``corners`` builds the grid with cell corners.

The reduced Gaussian grid descriptions (``grids/T<kind><N>.txt``) and hybrid coefficients (``grids/L<levels>.txt``)
ship with the package in ``ecefast/components/oifs/grids/``; a run only reads them. ``grid_files`` holds the
functions that made them, to run by hand when a grid or a vertical resolution is added:

.. code-block:: python

   from ecefast.components.oifs.grid_files import GRIDS_DIR, write_grid_descriptions, write_hybrid_coefficients

   write_grid_descriptions("/path/to/climate.v015", GRIDS_DIR)  # cdo griddes of each grid
   write_hybrid_coefficients(GRIDS_DIR, levels=[31, 91])         # from the ECMWF tables grids/L<levels>.csv

``corners.create_corner_grid`` writes the grid with cell corners of any ``ICMGGECE4INIT`` outside a run, with its
masked variant (``masked_outfile``).

Writing a step
--------------

A step is a class that subclasses :class:`ecefast.core.steps.ComponentStep`. It declares:

``name``
   Short name, used to select it and in ``needs`` (``stage``, ``oifs``, ``nemo``, ...).
``component``
   The component it makes files for (``oifs``, ``nemo``, ``oasis``, ``rnfm``), used by
   ``ecefast <component> run``; ``None`` for a step of the whole tree (``stage``).
``needs``
   Names of the steps that must run before it.
``reads``
   Paths it reads (files or directories).
``writes``
   Paths it writes.

and implements ``from_context(ctx)``, which builds the step from the run context, and
``run()``, which does the work by calling the ``create_*`` methods. ``reads`` and ``writes``
are the truth: a step touches no other file. The first line of the class docstring describes
the step in the dry run.

.. code-block:: python

   from ecefast.core.steps import ComponentStep


   class EoceneNEMO(ComponentStep):
       """Tides, geothermal flux, ocean initial state, runoff."""

       name = "nemo"
       component = "nemo"
       needs = ["stage"]  # run after the base files are copied
       reads = ["{input}/nemo/initial/zdfiwm_forcing_r720x360.nc"]
       writes = ["{output}/nemo/initial/zdfiwm_forcing_r720x360.nc"]

       # __init__ and the create_* methods are unchanged

       @classmethod
       def from_context(cls, ctx):
           return cls(
               herold_folder=ctx.section.herold,
               input_folder=ctx.section.input,
               output_folder=ctx.section.output,
               nemo_grid=ctx.config.grids.nemo.name,
           )

       def run(self):
           self.create_tidal_mixing()
           self.create_geothermal_flux()
           self.create_ocean_init()
           self.create_runoff()

``ctx.section`` is the configuration section of the running period, and ``ctx.tmpdir(component)``
the folder of its intermediate files, ``<machine.tmpdir>/<period>/<component>``. Path templates use
``{...}`` placeholders (:meth:`ecefast.core.workspace.Context.expand`): a name is first looked up in
the running period, then in the whole file.

==============================  ==============================================================
Placeholder                     Value
==============================  ==============================================================
``{input}``                     ``<period>.input``: the EC-Earth tree it starts from, read-only
``{output}``                    ``<period>.output``: the tree it makes
``{herold}``                    ``eocene.herold``: Herold et al. (2014), read-only
``{nemo.source_grid}``          any key of the running period, e.g. ``present.nemo.source_grid``
``{grids.oifs.name}``           e.g. ``TL63L31``; also ``startdate``, ``climate_version``
``{grids.nemo.name}``           e.g. ``PALEORCA2``
``{present.input}``             any key of the file, by its full dotted name
==============================  ==============================================================

An unknown key, or one that is not set, is an error naming it.

Running a pipeline from Python
------------------------------

.. code-block:: python

   from ecefast.periods.eocene import pipeline

   pipeline.run("configs/laptop.yml")                       # all steps
   pipeline.run("configs/laptop.yml", select=["nemo"])      # only some
   pipeline.run("configs/laptop.yml", component="nemo")     # the steps of one component: domain, nemo
   pipeline.run("configs/laptop.yml", dry_run=True)         # check and show the plan

``pipeline.run`` reads the configuration, checks the read-only directories of the period and calls
:func:`~ecefast.core.steps.run_pipeline` with a :class:`~ecefast.core.workspace.Context`, which
can also be built by hand:

.. code-block:: python

   from ecefast.core import load_config
   from ecefast.core.steps import run_pipeline
   from ecefast.core.workspace import Context, Stage

   ctx = Context(load_config("configs/laptop.yml"), "eocene")
   run_pipeline([Stage, EoceneNEMO], ctx, select=["nemo"])

Before anything runs, :func:`~ecefast.core.steps.run_pipeline` checks (*preflight*):

- every step comes after the steps it ``needs``;
- a needed step that is not selected has run before: all its ``writes`` exist;
- no ``writes`` path lies inside a read-only directory (every period's ``input``,
  ``eocene.herold``);
- every ``reads`` path exists, or is written by an earlier selected step.

All missing inputs are reported in one error, and nothing is written:

.. code-block:: text

   Cannot start: 2 input files are missing. Nothing was written.
     nemo   needs  /path/to/ECE4-DATA-V3/initial_state/nemo/ts_state/woa13-levitus-L31.nc
     oasis  needs  /path/to/ECE4-DATA-V3/initial_state/oasis/PALEORCA2/default/rstos.nc

Then the runner builds every selected step with ``from_context``, before the first one runs. This
is where a step checks inputs that a class-level ``reads`` list cannot hold because they depend on
the configuration: the ``domain`` step checks the files in the directory of
``eocene.nemo.domain`` or, with ``build``, every input of the NEMO domain pipeline it runs (e.g.
``grids.nemo.coords_ori``); the present-day steps check the inputs of their enabled steps and
refuse existing final files without ``--overwrite``. ``from_context`` must not write anything.

A **dry run** does the same checks, logs each selected step with its description and what it
writes, and touches nothing. Otherwise the steps run in order, and after each one the runner
checks that all its ``writes`` exist.

.. _stage-step:

The ``stage`` step
------------------

:class:`ecefast.core.workspace.Stage` copies the base files from the period's ``input`` to its
``output``, so the later steps modify copies, never the input. It is the first step of both
periods. It copies ``oifs/`` (``composition``, ``ifsdata``, ``vtables``, ``rtables`` and
``{grids.oifs.name}``), ``nemo/`` (``cfc``, ``climatology``, ``initial``, ``weights``),
``oasis/{grids.nemo.name}`` and ``runoff-mapper/``, and symlinks ``cmip6-data``. The present-day ``stage`` (``PresentStage``) also copies
``nemo/domain/ORCA2``, which ``EoceneNEMO`` reads when the Eocene starts from the present-day tree.

Since ECE4-DATA 4.1.10 the initial state lives in ``initial_state/``; ``stage`` copies it first. It copies
the folders of the grids in use (:func:`ecefast.core.layout.initial_state_copies`):
``initial_state/oifs/{grids.oifs.name}``, ``initial_state/oasis/{grids.nemo.name}`` and
``initial_state/nemo/ts_state``; other grids of those components are left out. The other components
(``lpjg``, ``pism``, ``aime``, ...) are symlinks to the real folders of the input tree. In ECE4-DATA the old
paths are relative links into ``initial_state/`` (``oifs/<grid>/<startdate>``, ``oasis/<grid>/rstos.nc``,
``nemo/initial/woa13-levitus-L*.nc``): ``stage`` keeps them as relative links to the copy, so EC-Earth finds the
files at both paths. Any other link (absolute, or to a file the output does not hold) is replaced by a copy of
its target. The steps read and write only the ``initial_state/`` paths (:mod:`ecefast.core.layout`), never the
old ones. It refuses an output
directory that is or contains the input directory. The runner makes the run atomic: ``stage`` and
the steps after it write into ``<output>.partial``, moved to ``output`` at the end
(:func:`ecefast.core.io.replace_directory`).

Atomic writes
-------------

Every output file is written through :func:`ecefast.core.io.atomic_write`: the writer gets a
temporary file in the same directory (same suffix, so ``.nc`` and GRIB writers work), which
replaces the final file only when the write completes. A failed step leaves no half-written
file.

.. code-block:: python

   from ecefast.core.io import atomic_write

   with atomic_write(path) as tmp:
       ds.to_netcdf(tmp)
