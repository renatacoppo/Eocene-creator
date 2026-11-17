Quickstart
==========

``ecefast`` runs on ECMWF Atos, where DOMAINcfg and SECTIONS_DIADCT (the NEMO tools that build a
domain) are available. A full generation is two commands, the present day first, since the
Eocene starts from its tree:

.. code-block:: bash

   ecefast present run -c configs/atos.yml     # present-day tree, with the PALEORCA2 domain (~3 min)
   ecefast eocene run -c configs/atos.yml      # Eocene tree, with the Eocene domain (~5 min)

1. Set up (once)
----------------

.. code-block:: bash

   git clone https://github.com/renatacoppo/Eocene-creator.git
   cd Eocene-creator
   module load conda                     # or your own Miniforge
   mamba env create -f environment.yaml  # environment "eocene", with the package installed in editable mode

What a run needs on Atos:

- **CDO 2.5.x**, outside the environment: ``module load cdo/2.5.3`` (the default module is newer).
  The run stops with any other CDO, see :ref:`data-version`.
- **An EC-Earth4 build**: its source tree, holding ``nemo-4.2/tools`` (``maketools``,
  ``DOMAINcfg/``, ``SECTIONS_DIADCT/``) and ``oasis3-mct-5.2/arch_ecearth/lib``. ``ecefast``
  compiles DOMAINcfg and SECTIONS_DIADCT there the first time, with the modules of
  ``src/ecefast/tools/hpc_profiles.yaml``.
- **The inputs**, all read-only:

  - an ECE4-DATA tree (4.1.10 or later, with ``initial_state/``), e.g. ECE4-DATA-4.1.11;
  - the Herold et al. (2014) supplementary data (``Supp/``), with the 55 Ma ocean-floor age grid of
    Müller et al. (2008) added to it, read by the Eocene ``nemo`` step:

    .. code-block:: bash

       cd /path/to/herold-et-al-2014/Supp
       curl -O https://www.earthbyte.org/webdav/ftp/earthbyte/agegrid/Palaeo/2008/Data/age_depth_bath_55.xyadb.bz2
       bunzip2 age_depth_bath_55.xyadb.bz2

  - the PALEORCA2 coordinates with halo, ``coords_ori.nc``.

2. Write the configuration
--------------------------

.. code-block:: bash

   cp configs/atos.tmpl configs/atos.yml       # configs/*.yml is ignored by git

Set the paths marked ``/path/to/...``: ``machine.tmpdir`` (intermediate files),
``machine.atos.ecearth4_sources``, ``grids.nemo.coords_ori``, ``present.input`` (the ECE4-DATA
tree), ``present.output``, ``eocene.herold`` and ``eocene.output``. Leave the rest as it is: the
template reproduces the existing data (``data_version: v1``). The steps of every component are
listed in full; set one to ``false`` to skip it. :doc:`configuration` describes every key.

3. Run
------

On an interactive node (``ecinteractive``) or in a batch job, not on a login node:

.. code-block:: bash

   conda activate eocene
   module load cdo/2.5.3

   ecefast present run -c configs/atos.yml --dry-run   # check every input, show the plan, write nothing
   ecefast present run -c configs/atos.yml
   ecefast eocene run -c configs/atos.yml --dry-run
   ecefast eocene run -c configs/atos.yml

A run first logs the CDO version and the data version, then checks that every input exists and
that nothing would be written into an input directory; a missing input stops it with one error
listing them all, before anything is written. The tree is built in ``<output>.partial`` and moved
to ``output`` only when every step has succeeded. If ``output`` holds files already, add
``--overwrite``: the run warns, waits 5 s (Ctrl-C to stop) and replaces the tree at the end.

At the end each tree holds ``provenance.yml``: the steps, the configuration file and its hash,
the git commit, the data version and the versions of Python, CDO and ecCodes.

What the steps make
-------------------

``ecefast <period> steps`` lists the steps of a period with what each needs, reads and writes.

.. list-table:: ``ecefast present run`` (section ``present``)
   :header-rows: 1
   :widths: 12 50 38

   * - Step
     - What it does
     - Files in ``present.output``
   * - ``stage``
     - Copies the base files of ``present.input`` (see below), and its ORCA2 domain.
     - the EC-Earth tree
   * - ``oifs``
     - The OIFS generator: OIFS base data of ``grids.oifs`` from a finer grid. Off for
       ``data_version: v1``, whose TL63L31 initial state is the one of the input tree.
     - ``initial_state/oifs/TL63L31/``, ``oifs/TL63L31/climate.v020/``
   * - ``nemo``
     - The NEMO domain pipeline with the present-day bathymetry: eORCA1 remapped to PALEORCA2,
       strait corrections, DOMAINcfg, masks, basins, ``diadct`` transport sections.
     - ``nemo/domain/PALEORCA2/``: ``domain_cfg.nc``, ``maskutil.nc``, ``subbasins.nc``,
       ``section_ijglobal.diadct``

.. list-table:: ``ecefast eocene run`` (section ``eocene``)
   :header-rows: 1
   :widths: 12 50 38

   * - Step
     - What it does
     - Files in ``eocene.output``
   * - ``stage``
     - Copies the base files of ``eocene.input`` (the present-day tree).
     - the EC-Earth tree
   * - ``domain``
     - Builds the Eocene domain with the NEMO domain pipeline and the Herold bathymetry
       (``eocene.nemo.domain: build``), installs it, and checks that it has the vertical grid of
       the present-day domain.
     - ``nemo/domain/PALEORCA2/domain_cfg.nc``, ``maskutil.nc``
   * - ``oasis``
     - Coupler restart without sea ice and with a constant SST (``eocene.oasis.constant_sst``).
     - ``initial_state/oasis/PALEORCA2/default/rstos.nc``
   * - ``oifs``
     - Herold land-sea mask, orography, subgrid orography, vegetation, soil, albedos and LAI; dry
       upper air; snow, lakes and other present-day fields set to 0.
     - ``initial_state/oifs/TL63L31/19900101/ICM*``, ``oifs/TL63L31/climate.v020/ICMCLECE4``,
       ``bare_soil_albedos.grb``
   * - ``nemo``
     - Eocene M2 tidal dissipation, geothermal flux from the ocean-floor age, three ocean initial
       states (DeepMIP cold and warm, present-day WOA) on the present-day levels, runoff set to 0.
     - ``nemo/initial/zdfiwm_forcing_r720x360.nc``, ``Goutorbe_ghflux.nc``;
       ``initial_state/nemo/ts_state/*.nc``; ``nemo/climatology/runoff_DaiTrenberth_PALEORCA2.nc``
   * - ``rnfm``
     - River basins from the Herold river flow direction, regridded to the runoff-mapper grid.
     - ``runoff-mapper/runoff_maps.nc``

``stage`` copies only what the steps and EC-Earth need: ``oifs/`` (``composition``, ``ifsdata``,
``vtables``, ``rtables`` and the OIFS grid), ``nemo/`` (``cfc``, ``climatology``, ``initial``,
``weights``), ``oasis/PALEORCA2``, ``runoff-mapper/`` and, from ``initial_state/``, the folders of
the grids in use. Everything else of ``initial_state/`` and ``cmip6-data`` are symlinked. After an
Eocene run, a check fails the run if a declared output is missing, if a NetCDF output holds NaN,
or if the Eocene vertical grid differs from the present-day one.

Rerunning part of a run
-----------------------

``--steps`` runs some steps on an existing tree; ``ecefast <component> run`` runs the steps of
one component (``--period present`` by default). ``--nemo`` and ``--oifs`` replace the configured
steps of that component for one run.

.. code-block:: bash

   ecefast eocene run -c configs/atos.yml --steps oifs -l DEBUG    # one step, more logging
   ecefast nemo run -c configs/atos.yml --overwrite                # present-day domain again
   ecefast nemo run -c configs/atos.yml --nemo sections --overwrite  # only the transport sections
   ecefast nemo run -c configs/atos.yml --period eocene            # Eocene steps domain and nemo

Options of ``ecefast <period> run`` and ``ecefast <component> run``:

.. code-block:: text

   -c, --config      Configuration file. Required.
   --steps a,b       Steps to run, in pipeline order (only ecefast <period> run). Default: all.
   --period P        present (default) or eocene (only ecefast <component> run).
   --oifs a,b        Run only these steps of <period>.oifs.steps.
   --nemo a,b        Run only these steps of <period>.nemo.steps.
   --dry-run         Check all inputs and show the plan; write nothing.
   --overwrite       Replace existing outputs, after a warning and a 5 s pause.
   -l, --loglevel    DEBUG, INFO (default), WARNING, ...

Intermediate files stay in ``<machine.tmpdir>/<period>/<component>/`` (e.g. the remapped
bathymetry, the DOMAINcfg namelist), so they can be inspected after a run. DOMAINcfg itself runs
in ``<ecearth4_sources>/nemo-4.2/tools/DOMAINcfg/``, which receives the namelists and raw output.

Check the result
----------------

``scripts/compare_trees.py`` compares two trees and writes a Markdown report: files in only one
of them, identical files and, for each file that differs, where and by how much; for a NEMO
``domain_cfg.nc`` also the vertical grid, the cells that change between land and ocean and
``bottom_level``.

.. code-block:: bash

   python scripts/compare_trees.py /path/to/OUTPUT/present /path/to/ECE4-DATA-V3 \
       --labels new V3 --include 'nemo/domain/*' -o present_vs_V3.md

With ``data_version: v1`` the domains match those of the existing experiments
(``PALEORCA2-definitive``): the same 16870 present-day and 16832 Eocene ocean columns, the same
levels and depths.

``ecefast <period> plot`` draws maps of the output of a period next to a reference tree, by
default the period's ``input`` (the present-day tree); ``--reference`` takes any other tree, for
instance another run. The figures go to the directory given with ``-o``, outside the EC-Earth
trees, with ``summary.yml`` holding the numbers, so two runs can be compared at a glance.

.. code-block:: bash

   ecefast eocene plot -c configs/atos.yml -o plots/eocene
   ecefast eocene plot -c configs/atos.yml -o plots/eocene-vs-old --reference /path/to/old/eocene
   ecefast present plot -c configs/atos.yml -o plots/present --only nemo

.. list-table::
   :header-rows: 1
   :widths: 15 85

   * - Group
     - What it draws (``--only`` selects groups)
   * - ``nemo``
     - ``nemo/domain.png``: depth, ocean basins and one-cell passages of the NEMO domain (basins
       other than the main one are closed seas or closed straits; ``summary.yml`` gives a cell of
       each). ``nemo/vs_reference_<grid>.png``: the land-sea mask against each domain of the
       reference tree: on the same grid the cells that change and the depth difference, on another
       grid (present day: ORCA2, eORCA1) the reference mask at the nearest point.
       ``nemo/vs_source.png`` (Eocene): the mask against the Herold et al. (2014) bathymetry.
   * - ``oifs``
     - ``oifs/<file>/<variable>.png``: every variable of ``ICMGGECE4INIT``, ``ICMSHECE4INIT``
       (orography), ``ICMCLECE4`` (annual mean and seasonal range) and ``bare_soil_albedos.grb``
       that differs from the reference: reference, test and difference where both have the same
       surface type; vegetation and soil types as classes.
   * - ``coupling``
     - ``coupling/oifs_lsm_vs_nemo.png``: the OIFS land-sea mask (land where ``lsm > 0.5``)
       against the NEMO ocean mask.

The present-day plot needs a built domain (``present.output/nemo/domain/<grid>/domain_cfg.nc``,
made on Atos).

Without Atos
------------

On a laptop (``configs/laptop.tmpl``, ``machine.name: local``) there is no DOMAINcfg: the
Eocene run installs the domain built on Atos (``eocene.nemo.domain`` set to its directory), and
``ecefast nemo run`` goes as far as the DOMAINcfg namelist. ``scripts/get_ece4_data.sh`` fetches the
subset of ECE4-DATA the Eocene run reads. This is meant for development and tests.
