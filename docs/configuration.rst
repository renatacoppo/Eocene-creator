Configuration
=============

Every ``ecefast`` command reads one YAML file, one per machine. Start from a template and set
the paths:

.. code-block:: bash

   cp configs/laptop.tmpl configs/laptop.yml   # laptop or workstation
   cp configs/atos.tmpl configs/atos.yml       # ECMWF Atos (runs DOMAINcfg too)

``configs/*.yml`` is ignored by git. The file is checked when it is read: an unknown or missing
key, a value of the wrong type or a bad placeholder stops the run with an error naming the key and
the file. The read-only directories of a period are checked when that period runs.

Layout
------

The sections follow the **time periods**; the components are subsections of each period.

- ``machine``: where the EC-Earth tools (DOMAINcfg) run, and ``tmpdir``, where every command keeps
  its intermediate files.
- ``grids``: the model resolution, the same for every period (a paleo period modifies the
  present-day files of the same grids).
- one section per period, ``present`` and ``eocene``. Each has ``input`` (the EC-Earth tree it
  starts from, read-only), ``output`` (the tree it makes, laid out as in ECE4-DATA) and one
  subsection per component (``oifs``, ``nemo``, ``oasis``). Datasets of a period have their own
  key (``eocene.herold``), never ``input``.

Two kinds of commands read it:

.. code-block:: bash

   ecefast <period> run -c CONFIG [--steps a,b]           # every step of a period: present, eocene
   ecefast <component> run -c CONFIG [--period eocene]    # one component of one period (default: present)

The smallest file for ``ecefast eocene run`` on a laptop:

.. code-block:: yaml

   schema: 2
   machine:
     tmpdir: /path/to/tmp/ecefast
   eocene:
     input: /path/to/ECE4-DATA-V3
     herold: /path/to/herold-et-al-2014/Supp
     output: /path/to/OUTPUT/eocene
     nemo:
       domain: /path/to/data/domain/PALEORCA2/eocene
       minimum_depth: 30

Only ``schema`` and ``machine.tmpdir`` are always required; a command stops with an error if the
section of its period (or of its component in that period) is missing.

Placeholders
------------

Any string value may contain ``{section.key}`` placeholders that refer to another value of the
same file, defaults included: ``{present.input}``, ``{grids.nemo.name}``, ``{machine.tmpdir}``.
They are replaced when the file is read; a value may refer to a value that has placeholders itself.

.. code-block:: yaml

   eocene:
     input: "{present.input}"     # start from the present-day tree

A placeholder that names an unknown key, a key set to ``null`` or a section, or placeholders that
refer to each other in a cycle, stop the run with an error naming the key. Quote values that start
with ``{`` (YAML would read them as a mapping).

The steps' ``reads`` and ``writes`` (see :doc:`workflow`) use the same placeholders, plus the keys
of the running period without its name: ``{input}``, ``{output}``, ``{herold}``,
``{nemo.source_grid}``.

``schema`` and ``machine``
--------------------------

.. list-table::
   :header-rows: 1
   :widths: 24 10 10 56

   * - Key
     - Type
     - Default
     - Meaning
   * - ``schema``
     - int
     - required
     - Version of the configuration format. Must be ``2``.
   * - ``machine.tmpdir``
     - str
     - required
     - Intermediate files of every command, in ``<tmpdir>/<period>/<component>/`` (e.g. the remapped
       bathymetry, the DOMAINcfg namelist, the OIFS work files). Kept between runs, so a step can
       rerun on the files of an earlier one. It must not lie inside an ``input``, ``herold`` or
       ``output`` directory.
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
   * - ``machine.atos.ecearth4_sources``
     - str
     - ``null``
     - ``atos``: the EC-Earth4 source tree. DOMAINcfg is compiled and runs in its
       ``nemo-4.2/tools/DOMAINcfg/`` (the namelists are written there), and its
       ``oasis3-mct-5.2/arch_ecearth/lib`` is added to ``LD_LIBRARY_PATH``. Needed to run DOMAINcfg.

Example for Atos:

.. code-block:: yaml

   machine:
     name: atos
     tmpdir: /path/to/tmp/ecefast
     atos:
       ecearth4_sources: /path/to/ecearth4/sources

``grids``: the model resolution
-------------------------------

.. list-table::
   :header-rows: 1
   :widths: 24 10 10 56

   * - Key
     - Type
     - Default
     - Meaning
   * - ``grids.oifs.name``
     - str
     - ``TL63L31``
     - OIFS resolution, as the directory name under ``oifs/``; also the resolution the OIFS
       generator makes.
   * - ``grids.oifs.startdate``
     - str
     - ``19900101``
     - Initial-state folder under ``oifs/<name>/``. Quote it in YAML (``'19900101'``).
   * - ``grids.oifs.climate_version``
     - str
     - ``climate.v020``
     - Climate files folder under ``oifs/<name>/``: ``climate.v020`` for cy48, ``climate.v015`` for
       cy43.
   * - ``grids.nemo.name``
     - str
     - ``PALEORCA2``
     - NEMO grid, as the directory name under ``oasis/`` and ``nemo/domain/``; also the grid the
       domain pipeline builds.
   * - ``grids.nemo.coords_ori``
     - str
     - ``null``
     - Coordinates of the grid with halo (NEMO 3.6); the domain pipeline removes the halo. Needed to
       build a domain.
   * - ``grids.nemo.staggering``
     - str
     - ``T``
     - Staggering (``T`` or ``F``) of the grid's coordinate bounds used in remapping.

``present``: the present-day period
-----------------------------------

Read by ``ecefast present run``, ``ecefast oifs run`` and ``ecefast nemo run``. Its final files go
to ``present.output`` as in ECE4-DATA (``oifs/<grid>/<startdate>/``,
``oifs/<grid>/<climate_version>/``, ``nemo/domain/<grid>/``). A run stops if one of them exists
already, unless ``--overwrite`` is given.

.. list-table::
   :header-rows: 1
   :widths: 24 10 10 56

   * - Key
     - Type
     - Default
     - Meaning
   * - ``present.input``
     - str
     - required
     - EC-Earth4 input tree (ECE4-DATA-V3). Read-only: nothing is ever written here.
   * - ``present.output``
     - str
     - required
     - Tree of the present-day files made by ``ecefast``.
   * - ``present.oifs.source_grid``
     - str
     - ``TL255L91``
     - OIFS generator: the grid the data is made from, read from
       ``{input}/oifs/<source_grid>/<startdate>/``. With another number of levels than
       ``grids.oifs.name`` the initial state is interpolated vertically.
   * - ``present.oifs.climate_dir``
     - str
     - ``null``
     - ECMWF monthly climate fields (``<N>l_2/month_<var>``), merged into ``ICMCLECE4-1990`` by the
       ``boundary`` step when no precomputed file exists. Needed only then.
   * - ``present.oifs.precomputed_climate_dir``
     - str
     - ``null``
     - Ready climate files (``<grid>/<climate_version>/ICMCLECE4``); the ``boundary`` step copies
       the file of ``grids.oifs.name`` when it is there.
   * - ``present.oifs.steps.spectral``, ``.gridpoint``, ``.boundary``
     - bool
     - ``true``, ``true``, ``false``
     - Steps of the OIFS generator (see :doc:`workflow`); ``--oifs a,b`` overrides them for one run.
   * - ``present.nemo.source_grid``
     - str
     - ``eORCA1``
     - NEMO grid of the present-day bathymetry: ``{input}/nemo/domain/<source_grid>/domain_cfg.nc``
       holds both the bathymetry and its horizontal grid. The strait corrections are defined per
       source grid, target grid and remapping: a source grid without them is an error.
   * - ``present.nemo.source_staggering``
     - str
     - ``T``
     - Staggering (``T`` or ``F``) of the source-grid coordinate bounds (used in ``setgrid``).
   * - ``present.nemo.minimum_depth``
     - float
     - required
     - Minimum ocean depth (m): depths ``0 < d < minimum_depth`` are raised to it (``30``).
   * - ``present.nemo.steps.<step>``
     - bool
     - ``true``
     - Steps of the domain pipeline: ``coordinates``, ``bathymetry``, ``configure_domain``,
       ``domain_cfg``, ``generate_mask``, ``generate_subbasins``. The last three need DOMAINcfg
       output: ``domain_cfg`` runs it on ``machine.name`` and stops before the first step with
       ``local``, so a laptop turns them off. ``--nemo a,b`` overrides them for one run.

Example (laptop):

.. code-block:: yaml

   present:
     input: /path/to/ECE4-DATA-V3
     output: /path/to/OUTPUT/present
     nemo:
       source_grid: eORCA1
       minimum_depth: 30
       steps: {domain_cfg: false, generate_mask: false, generate_subbasins: false}

``eocene``: the Eocene (DeepMIP) period
---------------------------------------

Read by ``ecefast eocene run`` and by ``ecefast <component> run --period eocene``.

.. list-table::
   :header-rows: 1
   :widths: 24 10 10 56

   * - Key
     - Type
     - Default
     - Meaning
   * - ``eocene.input``
     - str
     - required
     - The EC-Earth tree to start from, read-only: the present-day one, written
       ``"{present.input}"`` in the templates. ``stage`` copies its base files to ``output``; the
       ``domain`` step checks the vertical grid against its ``nemo/domain/<grid>/domain_cfg.nc``.
   * - ``eocene.herold``
     - str
     - required
     - Herold et al. (2014) supplementary data (Eocene boundary conditions). Read-only.
   * - ``eocene.output``
     - str
     - required
     - The Eocene EC-Earth input tree. The ``stage`` step refuses it if it holds files, unless
       ``--overwrite`` is given: then it warns, waits 5 s (Ctrl-C to stop) and recreates it.
   * - ``eocene.nemo.domain``
     - str
     - required
     - Where the Eocene domain comes from: a directory holding its ``domain_cfg.nc`` and
       ``maskutil.nc`` (on a laptop, the domain built on Atos), or ``build``: the ``domain`` step
       first builds it with the domain pipeline and the Eocene bathymetry, in
       ``<tmpdir>/eocene/nemo``. ``build`` needs DOMAINcfg: with ``machine.name: local`` it is an
       error.
   * - ``eocene.nemo.minimum_depth``
     - float
     - required
     - Minimum ocean depth (m) of the Eocene domain, used with ``build`` (``30``).
   * - ``eocene.nemo.steps.<step>``
     - bool
     - ``true``
     - Steps of the domain pipeline with ``build``, as in ``present.nemo.steps``.
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
     input: "{present.input}"
     herold: /path/to/herold-et-al-2014/Supp
     output: /path/to/OUTPUT/eocene
     nemo:
       domain: build
       minimum_depth: 30
     oifs:
       aerosols: false
     oasis:
       constant_sst: 290.0

Overriding steps for one run
----------------------------

The configured ``steps`` of a component can be replaced for one run with ``--<component>``; every
step not listed is off:

.. code-block:: bash

   ecefast nemo run -c configs/laptop.yml --nemo coordinates,bathymetry
   ecefast eocene run -c configs/atos.yml --steps stage,domain --nemo configure_domain,domain_cfg,generate_mask

Local folders
-------------

The templates and the docs use one naming scheme for the local outputs: ``OUTPUT/<period>`` for
runs and ``BASELINE/<period>`` for the frozen reference, with ``<period>`` = ``present``,
``eocene``.

Migrating
---------

Files in an older layout are not read: loading one stops with an error that lists each old key
found in it and its new name. Move the keys by hand, starting from a template.

From the first schema 2 (sections by component):

.. list-table::
   :header-rows: 1
   :widths: 45 55

   * - Old key
     - New key
   * - ``inputs.ece4_data``
     - ``present.input``, and ``eocene.input: "{present.input}"``
   * - ``inputs.herold``
     - ``eocene.herold``
   * - ``tmpdir``
     - ``machine.tmpdir`` (required)
   * - ``machine.atos.oasis_lib_dir``, ``nemo.domain.tools_dir``
     - ``machine.atos.ecearth4_sources`` (the EC-Earth4 source tree holding both)
   * - ``oifs.grid``, ``nemo.grid``
     - ``grids.oifs.name``, ``grids.nemo.name``
   * - ``oifs.data``
     - ``present.oifs``; ``output_dir`` → ``present.output``; ``startdate`` and
       ``climate_version`` → ``grids.oifs``
   * - ``nemo.domain``
     - ``present.nemo`` (present-day domain) and ``eocene.nemo`` (Eocene domain);
       ``coords_ori`` and ``staggering.target`` → ``grids.nemo``; ``staggering.source`` →
       ``present.nemo.source_staggering``; ``output_dir`` → each period's ``output`` (final files)
       and ``machine.tmpdir`` (intermediate files)
   * - ``nemo.domain.bathymetries``
     - removed: each period uses its own bathymetry
   * - ``eocene.output_dir``
     - ``eocene.output``
   * - ``eocene.domain.from``, ``eocene.domain.build``
     - ``eocene.nemo.domain``: ``build``, or the directory
   * - ``ecefast oifs data``, ``ecefast nemo domain [--bathymetry ...]``
     - ``ecefast oifs run``, ``ecefast nemo run [--period eocene]``

From schema 1:

.. list-table::
   :header-rows: 1
   :widths: 45 55

   * - Schema 1
     - Schema 2
   * - ``paths.input``
     - ``present.input``, and ``eocene.input: "{present.input}"``
   * - ``paths.herold``, ``paths.output``, ``paths.tmpdir``
     - ``eocene.herold``, ``eocene.output``, ``machine.tmpdir``
   * - ``tools.backend``, ``tools.atos.*``
     - ``machine.name``, ``machine.atos.*``
   * - ``tools.precomputed.domain``
     - ``eocene.nemo.domain``
   * - ``grids.oifs``, ``grids.nemo``
     - ``grids.oifs.name``, ``grids.nemo.name``
   * - ``nemo_domain``
     - ``present.nemo``, ``eocene.nemo`` and ``grids.nemo``, as above
   * - placeholders ``{input}``, ``{herold}``, ``{output}``
     - ``{present.input}``, ``{eocene.herold}``, ``{eocene.output}``

The older ``dirs:`` (``eocene`` command) and ``profiles:`` (domain pipeline) files are not read
either.
