Configuration
=============

Every ``ecefast`` command reads one YAML file, one per machine. Start from a template and set
the paths:

.. code-block:: bash

   cp configs/laptop.tmpl configs/laptop.yml   # laptop or workstation
   cp configs/atos.tmpl configs/atos.yml       # ECMWF Atos (runs DOMAINcfg too)

``configs/*.yml`` is ignored by git. The file is checked when it is read: an unknown or missing
key, a value of the wrong type, a bad placeholder or a missing input directory stops the run with
an error naming the key and the file.

Layout
------

The sections follow the components, and one rule ties commands to sections:
``ecefast <component> <command>`` reads section ``<component>.<command>``
(``ecefast nemo domain`` reads ``nemo.domain``); ``ecefast eocene run`` reads ``eocene``.

- ``inputs`` and ``tmpdir`` are shared by every command; ``inputs`` are read-only.
- ``machine`` says where the EC-Earth tools (DOMAINcfg) run.
- ``oifs`` and ``nemo`` hold what is specific to a component: its grid and its commands.
- ``eocene`` holds the Eocene (DeepMIP) run.
- **Every command writes only to its own** ``output_dir`` (the same key name everywhere). Final
  products are laid out as in ECE4-DATA inside it (``nemo/domain/<grid>/<name>/...``), so a later
  run finds them where an EC-Earth tree has them; intermediate files go to ``<output_dir>/work/``.
- A run uses the output of an earlier one by referring to it with a placeholder (below).

.. code-block:: yaml

   schema: 2
   inputs:
     ece4_data: /path/to/ECE4-DATA-V3
     herold: /path/to/herold-et-al-2014/Supp
   eocene:
     output_dir: /path/to/OUTPUT/eocene
     domain:
       from: /path/to/data/domain/PALEORCA2/eocene

This is enough for ``ecefast eocene run -c configs/laptop.yml``. Only ``schema`` and ``inputs``
are always required; a command stops with an error if its own section is missing.

Placeholders
------------

Any string value may contain ``{section.key}`` placeholders that refer to another value of the
same file, defaults included: ``{inputs.herold}``, ``{nemo.grid}``, ``{tmpdir}``,
``{nemo.domain.output_dir}``. They are replaced when the file is read; a value may refer to a value
that has placeholders itself.

.. code-block:: yaml

   eocene:
     domain:
       from: "{nemo.domain.output_dir}/nemo/domain/{nemo.grid}/eocene"   # output of `ecefast nemo domain`

A placeholder that names an unknown key, a key set to ``null`` or a section, or placeholders that
refer to each other in a cycle, stop the run with an error naming the key. Quote values that start
with ``{`` (YAML would read them as a mapping). The steps' ``reads`` and ``writes`` use the same
placeholders (see :doc:`workflow`).

``schema``, ``inputs``, ``tmpdir``
----------------------------------

.. list-table::
   :header-rows: 1
   :widths: 22 10 10 58

   * - Key
     - Type
     - Default
     - Meaning
   * - ``schema``
     - int
     - required
     - Version of the configuration format. Must be ``2``.
   * - ``inputs.ece4_data``
     - str
     - required
     - EC-Earth4 input tree (ECE4-DATA-V3). Must exist. Read-only: nothing is ever written here.
   * - ``inputs.herold``
     - str
     - required
     - Herold et al. (2014) supplementary data. Must exist. Read-only.
   * - ``tmpdir``
     - str
     - ``null``
     - Scratch directory of every command. ``ecefast eocene run`` keeps the OIFS intermediate
       files in ``<tmpdir>/oifs`` (with ``null``: a temporary directory, deleted afterwards).

``machine``: where the EC-Earth tools run
-----------------------------------------

.. list-table::
   :header-rows: 1
   :widths: 22 10 10 58

   * - Key
     - Type
     - Default
     - Meaning
   * - ``machine.name``
     - str
     - ``local``
     - How the NEMO DOMAINcfg tool is run (see :doc:`external_tools`): ``atos`` (compile and run it
       on ECMWF Atos), ``local`` (not available: use a domain built on Atos) or ``fake`` (tests:
       small files with the structure of the DOMAINcfg output).
   * - ``machine.atos.profile``
     - str
     - ``atos``
     - ``atos``: the HPC profile of ``ecefast/tools/hpc_profiles.yaml`` whose modules are loaded
       before DOMAINcfg is compiled and run.
   * - ``machine.atos.oasis_lib_dir``
     - str
     - ``null``
     - ``atos``: directory added to ``LD_LIBRARY_PATH`` when DOMAINcfg runs, for the OASIS
       libraries of the EC-Earth build (e.g. ``<ecearth4>/sources/oasis3-mct-5.2/arch_ecearth/lib``).
       Not added when ``null``.

Example for Atos:

.. code-block:: yaml

   machine:
     name: atos
     atos:
       oasis_lib_dir: /path/to/ecearth4/sources/oasis3-mct-5.2/arch_ecearth/lib

``oifs``
--------

.. list-table::
   :header-rows: 1
   :widths: 22 10 10 58

   * - Key
     - Type
     - Default
     - Meaning
   * - ``oifs.grid``
     - str
     - ``TL63L31``
     - OIFS resolution, as the directory name under ``oifs/`` in the input tree.

``oifs.data`` (``ecefast oifs data``, the OIFS generator) is reserved for task 8.2 and not read yet.

``nemo`` and ``nemo.domain``: the NEMO domain pipeline
------------------------------------------------------

``nemo.domain`` is read by ``ecefast nemo domain``, and by the Eocene ``domain`` step when
``eocene.domain.build`` is ``true``; leave it out if you use neither.

.. list-table::
   :header-rows: 1
   :widths: 22 10 10 58

   * - Key
     - Type
     - Default
     - Meaning
   * - ``nemo.grid``
     - str
     - ``PALEORCA2``
     - NEMO grid, as the directory name under ``oasis/`` and ``nemo/domain/``; also the grid the
       domain pipeline builds.
   * - ``nemo.domain.output_dir``
     - str
     - required
     - The only output of the pipeline: the final ``domain_cfg.nc``, ``maskutil.nc`` and
       ``subbasins.nc`` of each bathymetry in ``nemo/domain/<nemo.grid>/<name>/``; the intermediate
       files in ``work/`` (``coordinates/``, ``bathymetry/``, and ``domaincfg/`` with the DOMAINcfg
       namelists and raw output when ``tools_dir`` is ``null``).
   * - ``nemo.domain.tools_dir``
     - str
     - ``null``
     - NEMO tools directory holding ``DOMAINcfg/`` (Atos). When set, the namelists are written to
       its ``DOMAINcfg/``, where DOMAINcfg runs; with ``null`` (laptop) to ``output_dir/work/domaincfg``.
   * - ``nemo.domain.coords_ori``
     - str
     - required
     - PALEORCA2 coordinates with halo (NEMO 3.6); the pipeline removes the halo.
   * - ``nemo.domain.source_grid``
     - str
     - required
     - Grid of the present-day bathymetry (``eORCA1``). Its horizontal grid is read from
       ``{inputs.ece4_data}/nemo/domain/<source_grid>/domain_cfg.nc``.
   * - ``nemo.domain.staggering.source``, ``.target``
     - str
     - ``T``
     - Staggering (``T`` or ``F``) of the coordinate bounds of the source grid (used in ``setgrid``)
       and of the target grid (used in remapping).
   * - ``nemo.domain.minimum_depth``
     - float
     - required
     - Minimum ocean depth (m): depths ``0 < d < minimum_depth`` are raised to it (``30``).
   * - ``nemo.domain.steps``
     - mapping
     - required
     - ``true``/``false`` per step: ``coordinates``, ``bathymetry``, ``configure_domain``,
       ``domain_cfg``, ``generate_mask``, ``generate_subbasins``. A missing step is off. The last
       three need DOMAINcfg output: ``domain_cfg`` runs it on ``machine.name`` (``atos`` on Atos,
       ``fake`` in tests) and stops before the first step with ``local``.
   * - ``nemo.domain.bathymetries``
     - list
     - required
     - One entry per bathymetry: ``name``, ``enabled``, ``processor`` (a ``BathymetryProcessor``
       class name: ``PresentDayBathymetry`` or ``EoceneBathymetry``; an unknown name is an error
       that lists the known ones) and ``source_file``. ``PresentDayBathymetry`` also takes
       ``orca2_file`` for a comparison plot.

Example (laptop part of the pipeline):

.. code-block:: yaml

   nemo:
     domain:
       output_dir: /path/to/OUTPUT/nemo-domain
       coords_ori: /path/to/data/PALEORCA2/coords_ori.nc
       source_grid: eORCA1
       minimum_depth: 30
       steps: {coordinates: true, bathymetry: true, configure_domain: true}
       bathymetries:
         - name: eocene
           enabled: true
           processor: EoceneBathymetry
           source_file: "{inputs.herold}/herold_etal_stddev_subgrid_etopo1_to_eocene_1x1.nc"

``eocene``: the Eocene (DeepMIP) run
------------------------------------

Read by ``ecefast eocene run``.

.. list-table::
   :header-rows: 1
   :widths: 22 10 10 58

   * - Key
     - Type
     - Default
     - Meaning
   * - ``eocene.output_dir``
     - str
     - required
     - The Eocene EC-Earth input tree. The ``stage`` step refuses it if it is not empty, unless
       ``--overwrite`` is given: then it deletes and recreates it.
   * - ``eocene.domain.from``
     - str
     - required
     - Directory with the Eocene ``domain_cfg.nc`` and ``maskutil.nc`` that the ``domain`` step
       installs: on a laptop the domain built on Atos; on Atos the output of
       ``ecefast nemo domain``, ``"{nemo.domain.output_dir}/nemo/domain/{nemo.grid}/eocene"``.
   * - ``eocene.domain.build``
     - bool
     - ``false``
     - ``true``: the ``domain`` step first builds the Eocene domain with the NEMO domain pipeline
       (``nemo.domain``, bathymetry ``eocene`` only, its steps). ``from`` must then be the path above.
       Needs DOMAINcfg: ``true`` with ``machine.name: local`` is an error.
   * - ``eocene.oifs.aerosols``
     - bool
     - ``false``
     - Build the Herold Eocene aerosol climatology (``EoceneOIFS.aerosols``). Off: the
       present-day files are kept.
   * - ``eocene.oasis.constant_sst``
     - float
     - ``290.0``
     - SST (K) written everywhere in the OASIS ``rstos.nc`` restart. The value used so far, a
       placeholder for the first coupled step.

Example (Atos, building the Eocene domain inside the run):

.. code-block:: yaml

   eocene:
     output_dir: /path/to/OUTPUT/eocene
     domain:
       from: "{nemo.domain.output_dir}/nemo/domain/{nemo.grid}/eocene"
       build: true
     oifs:
       aerosols: false
     oasis:
       constant_sst: 290.0

Local folders
-------------

The templates and the docs use one naming scheme for the local outputs: ``OUTPUT/<command>`` for
runs and ``BASELINE/<command>`` for the frozen reference, with ``<command>`` = ``eocene``,
``nemo-domain`` (and ``oifs-data`` from task 8.2).

Migrating from schema 1
-----------------------

A schema 1 file is no longer read: loading one stops with an error that lists each old key found
in it and its new name. Move the keys by hand, starting from a template:

.. list-table::
   :header-rows: 1
   :widths: 45 55

   * - Schema 1
     - Schema 2
   * - ``paths.input``, ``paths.herold``
     - ``inputs.ece4_data``, ``inputs.herold``
   * - ``paths.output``
     - ``eocene.output_dir``
   * - ``paths.tmpdir``
     - ``tmpdir``
   * - ``tools.backend``
     - ``machine.name``
   * - ``tools.atos.*``
     - ``machine.atos.*``
   * - ``tools.precomputed.domain``
     - ``eocene.domain.from`` (``build: false``). The backend no longer decides: with
       ``tools.backend: atos`` or ``fake`` the step used to build the domain, now set
       ``eocene.domain.build: true`` and ``from: "{nemo.domain.output_dir}/nemo/domain/{nemo.grid}/eocene"``
   * - ``grids.oifs``
     - ``oifs.grid``
   * - ``grids.nemo``, ``nemo_domain.grids.target``
     - ``nemo.grid`` (one key for both)
   * - ``nemo_domain``
     - ``nemo.domain``
   * - ``nemo_domain.output_dir``
     - ``nemo.domain.output_dir``; the layout inside changes: ``domain/<grid>/<name>/`` →
       ``nemo/domain/<grid>/<name>/``, ``coordinates/``, ``bathymetry/`` → ``work/...``, the
       laptop namelists ``domain/namelist_cfg_*`` → ``work/domaincfg/``
   * - ``nemo_domain.domaincfg_dir``
     - ``nemo.domain.tools_dir``
   * - ``nemo_domain.grids.source``
     - ``nemo.domain.source_grid``
   * - ``nemo_domain.grids.staggering_source``, ``staggering_target``
     - ``nemo.domain.staggering.source``, ``.target``
   * - ``nemo_domain.parameters.minimum_depth``
     - ``nemo.domain.minimum_depth``
   * - ``nemo_domain.aliases``
     - removed: use ``{section.key}`` placeholders
   * - placeholders ``{input}``, ``{herold}``, ``{output}``, ``{tmpdir}``
     - ``{inputs.ece4_data}``, ``{inputs.herold}``, ``{eocene.output_dir}``, ``{tmpdir}``

The older ``dirs:`` (``eocene`` command) and ``profiles:`` (domain pipeline) files are not read
either.
