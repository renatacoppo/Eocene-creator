Configuration
=============

Every command reads one YAML file. Start from the template and set the paths:

.. code-block:: bash

   cp configs/atos.tmpl configs/atos.yml       # ECMWF Atos
   cp configs/laptop.tmpl configs/laptop.yml   # laptop: no DOMAINcfg, development only

``configs/*.yml`` is ignored by git. The templates list every step of every component, with its
default; optional keys are shown commented out with their default. The file is checked when it is
read: an unknown or missing key, a value of the wrong type or a bad placeholder stops the run with
an error naming the key. The read-only directories of a period are checked when that period runs.

Layout
------

.. code-block:: yaml

   schema: 2                  # format of this file
   data_version: v1           # the data a run reproduces, and the CDO it needs
   machine: ...               # where the EC-Earth tools run, and the intermediate files
   grids: ...                 # the model resolution, shared by every period
   present: ...               # ecefast present run, ecefast <component> run
   eocene: ...                # ecefast eocene run, ecefast <component> run --period eocene

A period has ``input`` (the EC-Earth tree it starts from, read-only), ``output`` (the tree it
makes, laid out as in ECE4-DATA) and one subsection per component (``oifs``, ``nemo``,
``oasis``). A run writes only to its period's ``output`` and to
``<machine.tmpdir>/<period>/<component>/``; on Atos DOMAINcfg also writes in its own directory of
the EC-Earth4 sources. Only ``schema`` and ``machine.tmpdir`` are always required; a command stops
if the section of its period, or of its component in that period, is missing.

Placeholders
~~~~~~~~~~~~

A string may refer to another value of the file, defaults included, with ``{section.key}``:

.. code-block:: yaml

   eocene:
     input: "{present.output}"     # start from the tree of ecefast present run

Placeholders are replaced when the file is read, and may refer to values that hold placeholders
themselves. An unknown key, a key set to ``null``, a section or a cycle is an error. Quote values
that start with ``{`` (YAML would read a mapping).

Top level
---------

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
     - Version of the configuration format: ``2``.
   * - ``data_version``
     - str
     - ``v1``
     - Version of the generated data, and the CDO series it needs (below). Only ``v1`` is
       supported; ``v2`` is reserved and rejected.

.. _data-version:

Data version and CDO
~~~~~~~~~~~~~~~~~~~~

``data_version`` names the data a run reproduces. Every run, dry runs included, checks the CDO
version against it before anything else and stops if it is not the right series. The data version
is written to ``provenance.yml``.

.. list-table::
   :header-rows: 1
   :widths: 12 14 74

   * - Version
     - CDO
     - Data
   * - ``v1``
     - 2.5.x
     - The data of the existing experiments: the PALEORCA2 domains of ECE4-DATA-V3 and
       ``PALEORCA2-definitive``, made with CDO 2.5.0 (2.5.1 and 2.5.3 reproduce them bit for bit);
       the TL63L31 OIFS initial state of the input tree.
   * - ``v2``
     - (none)
     - Not defined yet.

Why CDO matters: the land-sea mask of a NEMO bathymetry is the ``remapcon`` ocean fraction
thresholded at 0.5 (see :doc:`bathymetry`), and many PALEORCA2 cells have a fraction of exactly
0.5 (200 for the Eocene, 135 for the present day). Floating-point rounding decides on which side
they fall, and it changes between CDO versions: 2.6.x moves 25 Eocene and 4 present-day cells
compared with 2.5.x. ``REMAP_AREA_MIN`` does not change this.

.. code-block:: bash

   module load cdo/2.5.3                     # ECMWF Atos
   conda install -c conda-forge "cdo=2.5"    # elsewhere

``machine``
-----------

.. list-table::
   :header-rows: 1
   :widths: 24 10 10 56

   * - Key
     - Type
     - Default
     - Meaning
   * - ``machine.name``
     - str
     - ``local``
     - Where the NEMO tools DOMAINcfg and SECTIONS_DIADCT run: ``atos`` (compiled and run on ECMWF
       Atos), ``local`` (not available: the steps that need them must be off) or ``fake`` (tests:
       small files with the structure of the real output).
   * - ``machine.tmpdir``
     - str
     - required
     - Intermediate files, in ``<tmpdir>/<period>/<component>/``. Kept between runs, so a step can
       rerun on the files of an earlier one. Not inside an ``input``, ``herold`` or ``output``.
   * - ``machine.atos.profile``
     - str
     - ``atos``
     - The profile of ``src/ecefast/tools/hpc_profiles.yaml`` whose modules are loaded before the
       NEMO tools are compiled and run. If a module is retired, update the profile.
   * - ``machine.atos.ecearth4_sources``
     - str
     - ``null``
     - The EC-Earth4 source tree. DOMAINcfg and SECTIONS_DIADCT are compiled (if their executable
       is missing) and run in its ``nemo-4.2/tools/``; ``oasis3-mct-5.2/arch_ecearth/lib`` is added
       to ``LD_LIBRARY_PATH``. Required with ``atos``.

.. code-block:: yaml

   machine:
     name: atos
     tmpdir: /path/to/tmp/ecefast
     atos:
       ecearth4_sources: /path/to/ecearth4/sources

``grids``
---------

The model resolution, the same for every period (a paleo period modifies the present-day files of
the same grids).

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
     - OIFS resolution, the directory under ``oifs/`` and ``initial_state/oifs/``.
   * - ``grids.oifs.startdate``
     - str
     - ``19900101``
     - Initial-state folder under ``initial_state/oifs/<name>/``. Quote it (``'19900101'``).
   * - ``grids.oifs.climate_version``
     - str
     - ``climate.v020``
     - Climate folder under ``oifs/<name>/``: ``climate.v020`` for cy48, ``climate.v015`` for cy43.
   * - ``grids.nemo.name``
     - str
     - ``PALEORCA2``
     - NEMO grid, the directory under ``nemo/domain/`` and ``oasis/``; the grid the domain
       pipeline builds.
   * - ``grids.nemo.coords_ori``
     - str
     - ``null``
     - Coordinates of the grid with halo (NEMO 3.6); the domain pipeline removes the halo.
       Required to build a domain.
   * - ``grids.nemo.staggering``
     - str
     - ``T``
     - Staggering (``T`` or ``F``) of the cell bounds of the grid used in remapping.

``present``
-----------

Read by ``ecefast present run`` and ``ecefast <component> run``. Its final files go to
``present.output``. On a tree that exists already, a step refuses to replace them unless
``--overwrite`` is given.

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
     - The ECE4-DATA tree. Read-only.
   * - ``present.output``
     - str
     - required
     - The present-day tree: ``stage`` copies the base files of ``input`` here, ``oifs`` and
       ``nemo`` add theirs.
   * - ``present.nemo.source_grid``
     - str
     - ``eORCA1``
     - The present-day bathymetry: ``{input}/nemo/domain/<source_grid>/domain_cfg.nc``, which also
       holds its horizontal grid. It needs strait corrections for this grid (see :doc:`bathymetry`).
   * - ``present.nemo.source_staggering``
     - str
     - ``T``
     - Staggering of the cell bounds of the source grid.
   * - ``present.nemo.minimum_depth``
     - float
     - required
     - Minimum ocean depth (m): depths ``0 < d < minimum_depth`` are raised to it. ``30`` in v1.
   * - ``present.nemo.steps.<step>``
     - bool
     - ``true``
     - The steps of the NEMO domain pipeline (below).
   * - ``present.oifs.source_grid``
     - str
     - ``TL255L91``
     - OIFS generator: the grid the data is made from,
       ``{input}/initial_state/oifs/<source_grid>/<startdate>/``. With another number of levels than
       ``grids.oifs.name``, the initial state is interpolated vertically.
   * - ``present.oifs.climate_dir``
     - str
     - ``null``
     - ECMWF monthly climate fields (``<N>l_2/month_<var>``), merged into ``ICMCLECE4`` by
       ``boundary`` when there is no precomputed file.
   * - ``present.oifs.precomputed_climate_dir``
     - str
     - ``null``
     - Ready climate files (``<grid>/<climate_version>/ICMCLECE4``), copied by ``boundary``.
   * - ``present.oifs.steps.<step>``
     - bool
     - see below
     - The steps of the OIFS generator (below).

Steps of the NEMO domain pipeline
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The same pipeline builds the present-day domain (``present.nemo.steps``) and the Eocene one
(``eocene.nemo.steps``, unless ``eocene.nemo.domain_dir`` is set). Each step needs the files of the ones
before it, from this run or an earlier one.

.. list-table::
   :header-rows: 1
   :widths: 20 52 28

   * - Step
     - What it does
     - Writes
   * - ``coordinates``
     - Removes the halo of ``coords_ori``; cell bounds of the target grid and, for the present
       day, of the source grid.
     - ``<tmp>/coordinates/``
   * - ``bathymetry``
     - The bathymetry of the period on the target grid (:doc:`bathymetry`).
     - ``<tmp>/bathymetry/PALEORCA2/``
   * - ``configure_domain``
     - The DOMAINcfg namelist.
     - ``namelist_cfg_<name>`` in ``<ecearth4_sources>/nemo-4.2/tools/DOMAINcfg/`` (Atos)
   * - ``domain_cfg``
     - Runs DOMAINcfg (Atos only).
     - raw ``domain_cfg_<name>.nc``, ``mesh_mask_<name>.nc``, next to the namelist
   * - ``generate_mask``
     - Post-processes the raw output into the files EC-Earth reads.
     - ``domain_cfg.nc``, ``maskutil.nc``
   * - ``generate_subbasins``
     - Basin masks: Atlantic, Pacific, Indian, Indo-Pacific and global for the present day; global
       only for the Eocene.
     - ``subbasins.nc``
   * - ``sections``
     - The transport sections of the NEMO diagnostic ``diadct``, with SECTIONS_DIADCT (Atos only)
       on the 132 global sections of its ``list_sections.ascii_global``. Sections narrower than the
       grid have no points and are logged as a warning. Present day only: on for the present day,
       ``false`` for the Eocene, where turning it on is an error (the sections are present-day
       straits and passages).
     - ``section_ijglobal.diadct``

``<tmp>`` is ``<machine.tmpdir>/<period>/nemo``. The final files go to
``<present.output>/nemo/domain/PALEORCA2/`` for the present day, and to
``<tmp>/domain/PALEORCA2/`` for the Eocene, from where the ``domain`` step installs them. On a
laptop ``domain_cfg``, ``generate_mask``, ``generate_subbasins`` and ``sections`` are off.

Steps of the OIFS generator
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 14 10 76

   * - Step
     - Default
     - What it does
   * - ``spectral``
     - ``true``
     - Truncates ``ICMSHECE4INIT`` to the target spectral resolution.
   * - ``gridpoint``
     - ``true``
     - Remaps ``ICMGGECE4INIT`` and ``ICMGGECE4INIUA`` to the target reduced Gaussian grid.
   * - ``boundary``
     - ``false``
     - The climate file ``ICMCLECE4``: copies a precomputed one, or merges the monthly fields.

**For** ``data_version: v1`` **all three are off** (as in the templates), or ``present.oifs`` is
left out: the OIFS initial state of v1 is the TL63L31 one of the input tree, copied by ``stage``.
It was made by an IFS run (experiment ``i8ak``), not by the generator, and rebuilding it from
TL255L91 gives a different state.

``eocene``
----------

Read by ``ecefast eocene run`` and ``ecefast <component> run --period eocene``.

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
     - The tree to start from, read-only: ``"{present.output}"`` on Atos, the tree of
       ``ecefast present run`` with the present-day PALEORCA2 domain. The Eocene vertical grid is
       checked against its ``nemo/domain/PALEORCA2/domain_cfg.nc``.
   * - ``eocene.herold``
     - str
     - required
     - Herold et al. (2014) supplementary data, with the Müller et al. (2008) ocean-floor age grid.
       Read-only.
   * - ``eocene.output``
     - str
     - required
     - The Eocene tree. If it holds files, the run needs ``--overwrite``.
   * - ``eocene.nemo.domain_dir``
     - str
     - ``null``
     - ``null``: the ``domain`` step builds the Eocene domain with the NEMO domain pipeline and the
       Eocene bathymetry (needs ``machine.name: atos``). A directory holding ``domain_cfg.nc`` and
       ``maskutil.nc`` of a domain built before (e.g. on Atos, for a laptop): installed as it is.
       Example: ``domain_dir: /path/to/data/domain/PALEORCA2/eocene``.
   * - ``eocene.nemo.minimum_depth``
     - float
     - required
     - Minimum ocean depth (m) of the Eocene domain. ``30`` in v1.
   * - ``eocene.nemo.steps.<step>``
     - bool
     - ``true``; ``sections``: ``false``
     - The steps of the NEMO domain pipeline, used when ``domain_dir`` is not set.
   * - ``eocene.oifs.aerosols``
     - bool
     - ``false``
     - Build the Herold Eocene aerosol climatology. Off: the present-day files are kept.
   * - ``eocene.oasis.constant_sst``
     - float
     - ``290.0``
     - SST (K) written everywhere in the OASIS restart ``rstos.nc``.

Whatever its origin, the Eocene domain must have the vertical grid of the present-day one (same
number of levels, ``nav_lev`` and ``e3t_1d`` within 1e-6 m): the ocean initial state is built on
the present-day levels. A mismatch stops the run.

Example
-------

The ``present`` and ``eocene`` sections of ``configs/atos.tmpl``, without the comments:

.. code-block:: yaml

   present:
     input: /path/to/ECE4-DATA-4.1.11
     output: /path/to/OUTPUT/present
     oifs:
       steps: {spectral: false, gridpoint: false, boundary: false}
     nemo:
       source_grid: eORCA1
       minimum_depth: 30
       steps:
         coordinates: true
         bathymetry: true
         configure_domain: true
         domain_cfg: true
         generate_mask: true
         generate_subbasins: true
         sections: true

   eocene:
     input: "{present.output}"
     herold: /path/to/herold-et-al-2014/Supp
     output: /path/to/OUTPUT/eocene
     nemo:
       minimum_depth: 30
       steps:
         coordinates: true
         bathymetry: true
         configure_domain: true
         domain_cfg: true
         generate_mask: true
         generate_subbasins: true
         sections: false

Overriding the steps for one run
--------------------------------

``--nemo a,b`` and ``--oifs a,b`` replace the configured ``steps`` of that component for one run;
every step not listed is off:

.. code-block:: bash

   ecefast nemo run -c configs/atos.yml --nemo coordinates,bathymetry,configure_domain
   ecefast eocene run -c configs/atos.yml --steps stage,domain --nemo domain_cfg,generate_mask

Files in an older layout of the configuration are not read: the error lists each old key with its
new name.
