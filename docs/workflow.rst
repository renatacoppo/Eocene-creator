Workflow
========

The Eocene workflow is a *pipeline*: an ordered list of *steps*, run by one runner.

.. code-block:: python

   # src/ecefast/paleo/eocene/pipeline.py
   PIPELINE = [Stage, EoceneDomain, EoceneOASIS, EoceneOIFS, EoceneNEMO, EoceneRNFM]

Running it
----------

.. code-block:: bash

   ecefast eocene run -c configs/laptop.yml                  # every step, into an empty output directory
   ecefast eocene run -c configs/laptop.yml --overwrite      # every step, replacing an existing output directory
   ecefast eocene run -c configs/laptop.yml --steps nemo     # rerun one step on an existing output directory
   ecefast eocene run -c configs/laptop.yml --dry-run        # check all inputs and show the plan; write nothing
   ecefast eocene steps                                      # list the steps: what each needs, reads and writes

Options of ``ecefast eocene run``:

.. code-block:: text

   -c, --config      Configuration file (schema 2, section 'eocene', see the configuration page). Required.
   --steps a,b       Comma-separated step names; they run in pipeline order. Default: all steps.
   --dry-run         Check all inputs and show the plan; write nothing.
   --overwrite       Let 'stage' replace an output directory that is not empty.
   -l, --loglevel    Log level (DEBUG, INFO, WARNING, ...). Default: INFO.

``stage`` copies the base files into ``eocene.output_dir``. If that directory exists and is not
empty, ``stage`` stops with an error unless ``--overwrite`` is given, which removes and
recreates it. ``--steps`` without ``stage`` runs on an existing output directory: a needed step
that is not selected (here ``stage``) must have run before, i.e. all its ``writes`` exist.

The run logs the CDO version first. On a usage error (bad configuration, missing input, unknown
step, non-empty output) the command logs one error and exits with code 1.

A dry run checks everything and logs the plan, one line per step with what it writes
(paths shortened here):

.. code-block:: text

   $ ecefast eocene run -c configs/laptop.yml --dry-run
   INFO -> CDO version: 2.6.4
   INFO -> Dry run: nothing is written. Plan:
   INFO ->   stage   Copy base files from the input tree to the output tree.  → OUTPUT/eocene/oifs, OUTPUT/eocene/nemo, OUTPUT/eocene/oasis/PALEORCA2
   INFO ->   domain  Install the Eocene NEMO domain (from eocene.domain.from, built first if asked) and check its vertical grid.  → OUTPUT/eocene/nemo/domain/PALEORCA2/domain_cfg.nc, ...
   INFO ->   oasis   Write the OASIS restart rstos.nc: no sea ice, constant SST.  → OUTPUT/eocene/oasis/PALEORCA2/rstos.nc
   INFO ->   oifs    Modify the OIFS initial and climate files for the Eocene (Herold et al. 2014).  → OUTPUT/eocene/oifs/TL63L31/19900101/ICMGGECE4INIT, ...
   INFO ->   nemo    Modify NEMO input files for the Eocene: tidal mixing, geothermal flux, ocean initial state, runoff.  → OUTPUT/eocene/nemo/initial/zdfiwm_forcing_r720x360.nc, ...
   INFO ->   rnfm    Write the runoff-mapper basins from the Herold et al. (2014) river flow direction.  → OUTPUT/eocene/runoff-mapper/runoff_maps.nc

Provenance
~~~~~~~~~~

At the end of a successful run (not a dry run) the runner writes ``provenance.yml`` into the
output directory, atomically. It replaces the one of an earlier run.

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

After ``provenance.yml``, the run checks the outputs of the steps that ran
(``ecefast.paleo.eocene.verify``) and fails, listing every problem, if:

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

``stage`` (``Stage``)
   Copies the base files from the input tree to the output tree; see :ref:`stage-step`.

``domain`` (``EoceneDomain``)
   Needs ``stage``. Installs ``domain_cfg.nc`` and ``maskutil.nc`` in ``{eocene.output_dir}/nemo/domain/{nemo.grid}/``,
   copied from ``eocene.domain.from``: the domain built on Atos (laptop) or the output of an earlier
   ``ecefast nemo domain``, ``{nemo.domain.output_dir}/nemo/domain/{nemo.grid}/eocene/``. With
   ``eocene.domain.build: true`` the step first runs the NEMO domain pipeline (below) for the ``eocene`` bathymetry,
   with the steps of ``nemo.domain.steps``, on ``machine.name`` (:doc:`external_tools`); ``from`` must then be that
   output path. Then it checks the vertical grid rule: the installed Eocene domain must have the
   same number of levels as the present-day one, and ``nav_lev`` and ``e3t_1d`` within 1e-6 m (rounding) of the
   present-day
   ``{inputs.ece4_data}/nemo/domain/{nemo.grid}/domain_cfg.nc``. On a mismatch the pipeline stops with an error naming both
   files and their number of levels. Why: ``nemo`` builds the ocean initial state on the present-day levels.
   ``reads`` lists only the present-day domain: what else the step reads depends on ``eocene.domain.build``, which a
   class-level list cannot express, so the files in ``eocene.domain.from`` (``build: false``) and the inputs of the
   ``nemo.domain`` pipeline (``build: true``) are checked when the step starts, not in the preflight.

``oasis`` (``EoceneOASIS``)
   Needs ``stage``. Reads ``{inputs.ece4_data}/oasis/{nemo.grid}/rstos.nc``, writes ``{eocene.output_dir}/oasis/{nemo.grid}/rstos.nc``:
   the present-day OASIS restart with sea ice removed (``OIceFrc``, ``OIceTck``, ``OSnwTck``, ``O_AlbIce``,
   ``O_TepIce`` set to 0) and a constant SST (``eocene.oasis.constant_sst``, default 290 K) in ``O_SSTSST``.

``oifs`` (``EoceneOIFS``)
   Needs ``stage``. Reads the OIFS initial and climate GRIB files of the input tree
   (``oifs/{oifs.grid}/19900101/ICMGGECE4INIT``, ``ICMGGECE4INIUA``, ``ICMSHECE4INIT``;
   ``oifs/{oifs.grid}/climate.v020/ICMCLECE4``, ``bare_soil_albedos.grb``) and the Herold et al. (2014)
   topography, subgrid orography and biomes. Remaps the Herold fields to the model grid (intermediate files in
   ``{tmpdir}/oifs``), then writes Eocene versions of the same five files in the output tree: land-sea mask,
   orography, subgrid orography and slope, vegetation, soil type, albedos and LAI, dry atmosphere (humidity and
   clouds set to zero), spectral fields truncated to the mean. With ``eocene.oifs.aerosols: true`` it also
   writes ``oifs/ifsdata/IFS_aerosol_climatology_PI.nc`` from the Herold aerosols.

``nemo`` (``EoceneNEMO``)
   Needs ``stage`` (not ``domain``: it reads only present-day domains, on purpose).
   Reads the present-day tidal mixing, geothermal flux, WOA13 and runoff files from ``{inputs.ece4_data}/nemo``, the
   PALEORCA2 and ORCA2 present-day domains, and the Herold tidal dissipation, topography and ocean-age files.
   Writes ``nemo/initial/zdfiwm_forcing_r720x360.nc`` (Eocene M2 tidal dissipation and bathymetry),
   ``nemo/initial/Goutorbe_ghflux.nc`` (geothermal flux from Eocene ocean-floor age),
   ``nemo/initial/woa13-levitus-L31_deepmip-30.nc`` and ``_woa-pi.nc`` (two ocean initial states) and
   ``nemo/climatology/runoff_DaiTrenberth_PALEORCA2.nc`` (runoff set to zero; the runoff mapper handles rivers).

``rnfm`` (``EoceneRNFM``)
   Needs ``stage``. Reads ``{inputs.herold}/herold_etal_eocene_runoff_1x1.nc`` and ``{inputs.ece4_data}/runoff-mapper/runoff_maps.nc``,
   writes ``{eocene.output_dir}/runoff-mapper/runoff_maps.nc``. Tracks river basins on the Herold et al. (2014) 1x1 river
   flow direction, merges small basins, and regrids ``drainage_basin_id``, ``arrival_point_id`` and
   ``calving_point_id`` (nearest neighbour, xESMF) to the runoff-mapper grid. ``calving_point_id`` equals
   ``arrival_point_id`` (no ice sheets in the Eocene).

``ecefast eocene steps`` prints the exact ``needs``, ``reads`` and ``writes`` of each step.

NEMO domain pipeline
--------------------

``ecefast nemo domain`` builds NEMO domains from bathymetries, following the ``nemo.domain``
section of the configuration (:doc:`configuration`):

.. code-block:: bash

   ecefast nemo domain -c configs/laptop.yml                        # every enabled bathymetry
   ecefast nemo domain -c configs/laptop.yml --bathymetry eocene    # only some of them
   ecefast nemo domain -c configs/laptop.yml -l DEBUG               # more logging
   ecefast nemo domain -c configs/laptop.yml --dry-run              # check all inputs and show the plan; write nothing

Its steps, each switched on or off in ``nemo.domain.steps``: ``coordinates`` (PALEORCA2 without
halo, cell bounds), ``bathymetry`` (one processor per bathymetry, named by ``processor``),
``configure_domain`` (one DOMAINcfg namelist per bathymetry), ``domain_cfg`` (DOMAINcfg, through
the backend of ``machine.name``, see :doc:`external_tools`), ``generate_mask``
(``domain_cfg.nc`` and ``maskutil.nc`` per bathymetry) and ``generate_subbasins``
(``subbasins.nc`` per bathymetry: Atlantic, Pacific, Indian, Indo-Pacific and global masks). On a
laptop the last three are off.

Everything goes to ``nemo.domain.output_dir``: the final files of each bathymetry to
``nemo/domain/<nemo.grid>/<name>/``, laid out as in an EC-Earth input tree so ``eocene.domain.from``
can point there, and the intermediate files to ``work/`` (``coordinates/``, ``bathymetry/``, and
``domaincfg/`` with the namelists and raw DOMAINcfg output when ``nemo.domain.tools_dir`` is not set).

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

Bathymetry processors are found by name in a plain mapping: the generic ones in
``ecefast.components.nemo.bathymetry.PROCESSORS`` (``PresentDayBathymetry``), the Eocene ones in
``ecefast.paleo.eocene.bathymetry.EOCENE_PROCESSORS`` (``EoceneBathymetry``). The command passes
both to :class:`~ecefast.components.nemo.domain.pipeline.NEMOWorkflow`; the NEMO component never
imports ``paleo``. A ``processor`` name that is in neither is an error listing the known ones. To
add a paleo bathymetry, subclass ``BathymetryProcessor`` under ``ecefast/paleo/<period>/``, export
it in a mapping like ``EOCENE_PROCESSORS`` and merge that mapping where the pipeline is built.

OIFS generator
--------------

``ecefast oifs data`` makes the present-day OIFS base data of ``oifs.grid`` from the one of
``oifs.data.source_grid`` in the input tree, following the ``oifs.data`` section of the configuration
(:doc:`configuration`). Its inputs (TL255L91, the ECMWF climate fields, the grids with cell corners) exist on
ECMWF Atos only:

.. code-block:: bash

   ecefast oifs data -c configs/atos.yml --dry-run    # check all inputs and show the plan; write nothing
   ecefast oifs data -c configs/atos.yml              # run the enabled steps

Its steps, switched on or off in ``oifs.data.steps``:

``spectral`` (on)
   Truncates ``ICMSHECE4INIT`` to the target spectral resolution (``cdo sp2sp``).
``gridpoint`` (on)
   Remaps ``ICMGGECE4INIT`` and ``ICMGGECE4INIUA`` to the target reduced Gaussian grid by nearest neighbour
   (``cdo remapnn``), GRIB1 and GRIB2 messages separately, then joins them (all GRIB1, then all GRIB2).
``boundary`` (off)
   The climate file: copies ``<precomputed_climate_dir>/<grid>/<climate_version>/ICMCLECE4`` if it exists,
   else merges the monthly albedo and leaf area index fields of ``climate_dir`` into ``ICMCLECE4-1990``.

When ``spectral`` or ``boundary`` is on, the three initial-state files go to
``<output_dir>/oifs/<grid>/<startdate>/``: moved from ``work/`` when the source and target have the same number of
levels, else interpolated vertically first (``cdo remapeta`` with the hybrid coefficients of
``grids/L<levels>.txt``; temperature, divergence and vorticity through the Gaussian grid and back to spectral,
moisture and cloud fields on the reduced Gaussian grid, orography and surface pressure unchanged). The climate
file goes to ``<output_dir>/oifs/<grid>/<climate_version>/``. Intermediate files stay in ``<output_dir>/work/``, so
a step can be rerun alone on the work of an earlier run. Nothing is written into the input tree.

Before the first step the command checks that every file an enabled step reads exists (or is written by an
earlier step), and lists all missing ones at once; ``--dry-run`` does only this and logs the plan.

The reduced Gaussian grid descriptions (``grids/T<kind><N>.txt``) and hybrid coefficients ship with the package
in ``ecefast/components/oifs/grids/``. The scripts that made them, and the grids of
``oifs.data.vertical_grids_dir``, stay scripts: ``create_corners.py`` (grids with cell corners),
``descriptor_generator.py`` (reduced Gaussian descriptions) and ``convert_aka_bika.py`` (hybrid coefficients
from the ECMWF tables).

Writing a step
--------------

A step is a class that subclasses :class:`ecefast.core.steps.ComponentStep`. It declares:

``name``
   Short name, used to select it and in ``needs`` (``stage``, ``oifs``, ``nemo``, ...).
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
       needs = ["stage"]  # run after the base files are copied
       reads = ["{inputs.ece4_data}/nemo/initial/woa13-levitus-L31.nc"]
       writes = ["{eocene.output_dir}/nemo/initial/woa13-levitus-L31_woa-pi.nc"]

       # __init__ and the create_* methods are unchanged

       @classmethod
       def from_context(cls, ctx):
           config = ctx.config
           return cls(
               herold_folder=config.inputs.herold,
               input_folder=config.inputs.ece4_data,
               output_folder=config.eocene.output_dir,
           )

       def run(self):
           self.create_tidal_mixing()
           self.create_geothermal_flux()
           self.create_ocean_init()
           self.create_runoff()

Path templates use the ``{section.key}`` placeholders of the configuration (:doc:`configuration`), the
same ones a config file may use. The Eocene steps use:

========================  ==============================================
Placeholder               Value
========================  ==============================================
``{inputs.ece4_data}``    ECE4-DATA-V3, read-only
``{inputs.herold}``       Herold et al. (2014), read-only
``{eocene.output_dir}``   the Eocene output tree
``{tmpdir}``              scratch directory (error if not set)
``{oifs.grid}``           e.g. ``TL63L31``
``{nemo.grid}``           e.g. ``PALEORCA2``
========================  ==============================================

An unknown key, or one that is not set, is an error naming it.

Running a pipeline from Python
------------------------------

.. code-block:: python

   from ecefast.core import load_config
   from ecefast.core.steps import run_pipeline
   from ecefast.core.workspace import Context, Stage

   ctx = Context(load_config("configs/laptop.yml"))
   run_pipeline([Stage, EoceneNEMO], ctx)                    # all steps
   run_pipeline([Stage, EoceneNEMO], ctx, select=["nemo"])  # only some
   run_pipeline([Stage, EoceneNEMO], ctx, dry_run=True)      # check and show the plan

Before anything runs, :func:`~ecefast.core.steps.run_pipeline` checks (*preflight*):

- every step comes after the steps it ``needs``;
- a needed step that is not selected has run before: all its ``writes`` exist;
- no ``writes`` path lies inside ``inputs.ece4_data`` or ``inputs.herold``;
- every ``reads`` path exists, or is written by an earlier selected step.

All missing inputs are reported in one error, and nothing is written:

.. code-block:: text

   Cannot start: 2 input files are missing. Nothing was written.
     nemo   needs  /path/to/ECE4-DATA-V3/nemo/initial/woa13-levitus-L31.nc
     oasis  needs  /path/to/ECE4-DATA-V3/oasis/PALEORCA2/rstos.nc

Then the runner builds every selected step with ``from_context``, before the first one runs. This
is where a step checks inputs that a class-level ``reads`` list cannot hold because they depend on
the configuration: the ``domain`` step checks the files in ``eocene.domain.from`` or, with
``eocene.domain.build: true``, every input of the NEMO domain pipeline it runs (e.g.
``nemo.domain.coords_ori``). ``from_context`` must not write anything.

A **dry run** does the same checks, logs each selected step with its description and what it
writes, and touches nothing. Otherwise the steps run in order, and after each one the runner
checks that all its ``writes`` exist.

.. _stage-step:

The ``stage`` step
------------------

:class:`ecefast.core.workspace.Stage` copies the base files from the input tree to the output
tree, so the later steps modify copies, never the input. It refuses an output directory that
is not empty, unless ``--overwrite`` is given: then it removes it first. It copies ``oifs/``
(``composition``, ``ifsdata``, ``vtables``, ``rtables`` and the OIFS grid), ``nemo/`` (``cfc``, ``climatology``, ``initial``, ``weights``) and
``oasis/<nemo grid>``, and symlinks ``cmip6-data``. It refuses an output directory that is or
contains the input directory.

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
