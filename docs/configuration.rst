Configuration
=============

``ecefast eocene`` and ``ecefast nemo-domain`` read one YAML file, one per machine. Start from a
template and set the paths:

.. code-block:: bash

   cp configs/laptop.tmpl configs/laptop.yml   # laptop or workstation
   cp configs/atos.tmpl configs/atos.yml       # ECMWF Atos (runs DOMAINcfg too)

``configs/*.yml`` is ignored by git. The file is checked when it is read: an unknown or missing
key, a value of the wrong type or a missing input directory stops the run with an error naming
the key and the file.

The file has a ``schema`` number and five sections. Only ``schema`` and ``paths`` are required;
the other sections, and every key with a default, can be left out.

.. code-block:: yaml

   schema: 1
   paths:
     input: /path/to/ECE4-DATA-V3
     output: /path/to/EOCENE-TEST
     herold: /path/to/herold-et-al-2014/Supp
   tools:
     precomputed:
       domain: /path/to/domain/PALEORCA2/eocene

This is enough for ``ecefast eocene -c configs/laptop.yml --run all --copy``.

``schema``
----------

.. list-table::
   :header-rows: 1
   :widths: 20 10 10 60

   * - Key
     - Type
     - Default
     - Meaning
   * - ``schema``
     - int
     - required
     - Version of the configuration format. Must be ``1``.

``paths``: root directories
---------------------------

.. list-table::
   :header-rows: 1
   :widths: 20 10 10 60

   * - Key
     - Type
     - Default
     - Meaning
   * - ``paths.input``
     - str
     - required
     - EC-Earth4 input tree (ECE4-DATA-V3). Must exist. Read-only: nothing is ever written here.
   * - ``paths.output``
     - str
     - required
     - Output tree of ``ecefast eocene``. ``--copy`` deletes and recreates it.
   * - ``paths.herold``
     - str
     - required
     - Herold et al. (2014) supplementary data. Must exist. Read-only.
   * - ``paths.tmpdir``
     - str
     - ``null``
     - Temporary directory. Reserved, not read yet.

The four paths are also placeholders in ``nemo_domain.bathymetries`` (``{input}``, ``{output}``,
``{herold}``, ``{tmpdir}``).

``tools``: external tools and precomputed files
-----------------------------------------------

.. list-table::
   :header-rows: 1
   :widths: 20 10 10 60

   * - Key
     - Type
     - Default
     - Meaning
   * - ``tools.backend``
     - str
     - ``local``
     - How EC-Earth tools are run. Only ``local`` for now.
   * - ``tools.precomputed.domain``
     - str
     - ``null``
     - Directory with the Eocene ``domain_cfg.nc`` and ``maskutil.nc``, built on Atos by the
       NEMO domain pipeline. ``ecefast eocene --run nemo`` (and ``all``) copies them into the
       output tree and stops with an error if the key is not set.

``grids``: model resolutions
----------------------------

.. list-table::
   :header-rows: 1
   :widths: 20 10 10 60

   * - Key
     - Type
     - Default
     - Meaning
   * - ``grids.oifs``
     - str
     - ``TL63L31``
     - OIFS resolution, as the directory name under ``oifs/`` in the input tree.
   * - ``grids.nemo``
     - str
     - ``PALEORCA2``
     - NEMO grid, as the directory name under ``oasis/`` and ``nemo/domain/``.

``nemo_domain``: the NEMO domain pipeline
-----------------------------------------

Read only by ``ecefast nemo-domain``; leave the section out if you do not run it.

.. list-table::
   :header-rows: 1
   :widths: 20 10 10 60

   * - Key
     - Type
     - Default
     - Meaning
   * - ``nemo_domain.output_dir``
     - str
     - required
     - Output of the pipeline: ``coordinates/``, ``bathymetry/``, ``domain/``.
   * - ``nemo_domain.domaincfg_dir``
     - str
     - ``null``
     - NEMO tools directory holding ``DOMAINcfg/``. With ``null`` (laptop) the namelists are
       written to ``output_dir/domain``; on Atos they go to ``DOMAINcfg/``, where DOMAINcfg runs.
   * - ``nemo_domain.coords_ori``
     - str
     - required
     - PALEORCA2 coordinates with halo (NEMO 3.6); the pipeline removes the halo.
   * - ``nemo_domain.mesh_mask``
     - str
     - required
     - eORCA1 ``mesh_mask`` (NEMO 4.2), source grid of the present-day bathymetry.
   * - ``nemo_domain.aliases``
     - mapping
     - ``{}``
     - Extra placeholders for ``source_file``, e.g. ``my_dir: /path`` → ``"{my_dir}/file.nc"``.
   * - ``nemo_domain.grids``
     - mapping
     - required
     - ``target`` (produced grid, ``PALEORCA2``), ``source`` (``eORCA1``), ``staggering_source``
       and ``staggering_target`` (``T`` or ``F``).
   * - ``nemo_domain.parameters``
     - mapping
     - required
     - ``minimum_depth`` (m): depths ``0 < d < minimum_depth`` are raised to it.
   * - ``nemo_domain.steps``
     - mapping
     - required
     - ``true``/``false`` per step: ``coordinates``, ``bathymetry``, ``configure_domain``,
       ``domain_cfg``, ``generate_mask``, ``generate_subbasins``. A missing step is off. The last
       three need DOMAINcfg, so they run on Atos only.
   * - ``nemo_domain.bathymetries``
     - list
     - required
     - One entry per bathymetry: ``name``, ``enabled``, ``processor`` (a ``BathymetryProcessor``
       class name) and ``source_file`` (placeholders: the ``paths`` keys, ``{output_dir}`` and the
       aliases). ``PresentDayBathymetry`` also takes ``orca2_file`` for a comparison plot.

Example (laptop part of the pipeline):

.. code-block:: yaml

   nemo_domain:
     output_dir: /path/to/EOCENE-DOMAIN-TEST
     domaincfg_dir: null
     coords_ori: /path/to/data/PALEORCA2/coords_ori.nc
     mesh_mask: /path/to/data/eORCA1/mesh_mask.nc
     grids: {target: PALEORCA2, source: eORCA1, staggering_source: T, staggering_target: T}
     parameters: {minimum_depth: 30}
     steps: {coordinates: true, bathymetry: true, configure_domain: true}
     bathymetries:
       - name: eocene
         enabled: true
         processor: EoceneBathymetry
         source_file: "{herold}/herold_etal_stddev_subgrid_etopo1_to_eocene_1x1.nc"

``eocene``: Eocene (DeepMIP) options
------------------------------------

.. list-table::
   :header-rows: 1
   :widths: 25 10 10 55

   * - Key
     - Type
     - Default
     - Meaning
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

Example:

.. code-block:: yaml

   eocene:
     oifs:
       aerosols: false
     oasis:
       constant_sst: 290.0

Migrating from the old format
-----------------------------

The old ``dirs:`` file of the ``eocene`` command and the ``profiles:`` file of the domain
pipeline are no longer read; loading one stops with an error. Move the keys by hand:

.. list-table::
   :header-rows: 1
   :widths: 45 55

   * - Old key
     - New key
   * - ``dirs.input``, ``dirs.output``, ``dirs.herold``, ``dirs.tmpdir``
     - ``paths.input``, ``paths.output``, ``paths.herold``, ``paths.tmpdir``
   * - ``dirs.domain``
     - ``tools.precomputed.domain``
   * - ``profiles.<name>.*`` (domain pipeline)
     - ``nemo_domain.*``: one file per machine replaces the profiles
   * - ``grids``, ``parameters``, ``steps``, ``bathymetries`` (domain pipeline)
     - the same keys under ``nemo_domain``
   * - ``aliases`` ``{domain_dir}``, ``{herold_dir}``
     - ``{input}/nemo/domain``, ``{herold}`` (or keep them under ``nemo_domain.aliases``)
