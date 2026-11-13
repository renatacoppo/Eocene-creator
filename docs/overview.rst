Overview
========

``ecefast`` builds EC-Earth4 input data for a **time period**. Two periods exist:

``present``
   The present-day base data of the model grids: the OIFS initial state and climate file of a
   resolution (e.g. TL63L31), made from a finer one, and the NEMO domain of the ocean grid
   (PALEORCA2), made from the bathymetry of a present-day domain (eORCA1).
``eocene``
   **Eocene (DeepMIP) boundary conditions**. It copies the files EC-Earth4 reads (atmosphere OIFS
   TL63L31, ocean NEMO PALEORCA2, coupler OASIS, runoff-mapper) and replaces their
   geography-dependent fields with the Eocene ones of Herold et al. (2014). Runs on a laptop in
   about a minute.

Each period writes a tree with the layout and file names of an EC-Earth4 input tree, so EC-Earth4
uses it in place of the present-day one.

Two kinds of commands run them:

``ecefast <period> run``
   The whole pipeline of a period: ``ecefast present run``, ``ecefast eocene run``.
``ecefast <component> run [--period present|eocene]``
   Only the steps of one component (``oifs``, ``nemo``, ``oasis``, ``rnfm``) in one period,
   ``present`` by default: ``ecefast nemo run`` builds the present-day NEMO domain,
   ``ecefast nemo run --period eocene`` runs the Eocene ``domain`` and ``nemo`` steps.

Commands, sections and outputs
------------------------------

A period reads its own section of the configuration file (:doc:`configuration`) and writes its
final files only to that section's ``output``. Intermediate files of every command go to
``<machine.tmpdir>/<period>/<component>/``. ``input`` and ``eocene.herold`` are read-only.

.. code-block:: text

   config file                command                  writes only to
   -----------                -------                  --------------
   machine: name, tmpdir      (every command)          <tmpdir>/<period>/<component>/   intermediates
   grids:   oifs, nemo        (the model resolution, shared by every period)

   present:                   ecefast present run      present.output = OUTPUT/present/
     input       (read-only)    oifs  (Atos inputs)      oifs/<grid>/<startdate>/, oifs/<grid>/<climate_version>/
     oifs, nemo                 nemo                     nemo/domain/<grid>/  domain_cfg.nc, maskutil.nc, subbasins.nc
                                                         provenance.yml

   eocene:                    ecefast eocene run       eocene.output  = OUTPUT/eocene/
     input: "{present.input}"   stage, domain, oasis,    oifs/ nemo/ oasis/ runoff-mapper/  (EC-Earth tree)
     herold      (read-only)    oifs, nemo, rnfm         provenance.yml
     nemo, oifs, oasis

.. list-table::
   :header-rows: 1
   :widths: 34 33 33

   * - Command
     - Steps with ``--period present`` (default)
     - Steps with ``--period eocene``
   * - ``ecefast oifs run``
     - ``oifs`` (OIFS generator)
     - ``oifs``
   * - ``ecefast nemo run``
     - ``nemo`` (present-day domain)
     - ``domain``, ``nemo``
   * - ``ecefast oasis run``
     - none (error)
     - ``oasis``
   * - ``ecefast rnfm run``
     - none (error)
     - ``rnfm``

``eocene.nemo.domain`` says where the Eocene NEMO domain comes from: on a laptop, the directory of
the domain copied from Atos; on Atos, ``build`` runs the NEMO domain pipeline with the Eocene
bathymetry inside the ``domain`` step. Local runs write to ``OUTPUT/<period>``; the frozen
references live in ``BASELINE/<period>``.

Inputs and outputs
------------------

.. code-block:: text

   INPUTS (read-only)                               OUTPUT (eocene.output)
   ------------------                               ----------------------
   ECE4-DATA-V3/      present-day EC-Earth4 -+      oifs/             atmosphere
                      inputs                 |      nemo/             ocean and domain
   herold-et-al-2014/ Eocene topography,     +-->   oasis/PALEORCA2/  coupler restart
                      biomes, runoff, tides  |      runoff-mapper/    river basins
   data/              PALEORCA2 coords, -----+      provenance.yml    what ran, versions
                      Eocene domain (Atos)

.. list-table::
   :header-rows: 1
   :widths: 22 30 48

   * - Input
     - Config key
     - What it provides
   * - ECE4-DATA-V3 (subset)
     - ``present.input``, ``eocene.input`` (``"{present.input}"``)
     - The present-day files to modify, and the present-day domains. Fetched with
       ``scripts/get_ece4_data.sh``.
   * - Herold et al. (2014) supplement
     - ``eocene.herold``
     - Eocene topography and bathymetry, subgrid orography, biomes, river flow direction, M2 tidal
       dissipation, ocean-floor age.
   * - PALEORCA2 ``coords_ori.nc``
     - ``grids.nemo.coords_ori``
     - The PALEORCA2 grid, to build a NEMO domain.
   * - Eocene NEMO domain
     - ``eocene.nemo.domain``
     - The directory holding ``domain_cfg.nc`` and ``maskutil.nc`` built on Atos; used on a laptop
       instead of running DOMAINcfg.

The Eocene workflow
-------------------

``ecefast eocene run`` runs the steps in this order. Every step after ``stage`` works on the copy
in the output tree, never on the input:

.. code-block:: text

                     +--> domain   Eocene NEMO domain (+ vertical grid check)
                     +--> oasis    coupler restart: no sea ice, constant SST
   input --> stage --+--> oifs     atmosphere: land-sea mask, orography, vegetation, albedo, ...
     (copy base      +--> nemo     ocean: tides, geothermal flux, initial state, runoff
      files)         +--> rnfm     runoff-mapper: river basins and arrival points
                                          |
                                          v
                              provenance.yml + verify (outputs exist, no NaN, vertical grid)

All steps need only ``stage``; they are independent of each other, and any of them can be rerun
alone (``--steps oifs``) on an existing output.

.. list-table::
   :header-rows: 1
   :widths: 10 45 45

   * - Step
     - What it changes, and from what
     - Files written (under ``eocene.output``)
   * - ``stage``
     - Copies the base files of the input tree: ``oifs/`` (grid, ``ifsdata``, ``composition``,
       tables), ``nemo/`` (``initial``, ``climatology``, ``cfc``, ``weights``),
       ``oasis/PALEORCA2``; symlinks ``cmip6-data``. Refuses an output that holds files without
       ``--overwrite``; with it, removes the whole Eocene tree first.
     - ``oifs/``, ``nemo/``, ``oasis/PALEORCA2/``
   * - ``domain``
     - Installs the Eocene PALEORCA2 domain: from the directory of ``eocene.nemo.domain`` (the
       one built on Atos), or, with ``eocene.nemo.domain: build`` (Atos), built first by the NEMO
       domain pipeline with the Eocene bathymetry. Fails if its vertical levels differ from the
       present-day domain (the ocean initial state is built on those levels).
     - ``nemo/domain/PALEORCA2/domain_cfg.nc``, ``maskutil.nc``
   * - ``oasis``
     - Coupler restart: sea-ice fraction, thickness, snow, ice albedo and temperature set to 0;
       SST set to ``eocene.oasis.constant_sst`` (290 K).
     - ``oasis/PALEORCA2/rstos.nc``
   * - ``oifs``
     - Atmosphere and land surface on the Herold geography: land-sea mask and its gradient,
       orography (spectral ``z``), subgrid orography and slope, vegetation types and cover, soil
       type, albedos and LAI, bare-soil albedos; snow, lake and other present-day fields set to 0;
       dry upper-air state (humidity and clouds 0), spectral fields truncated to their mean.
       Optional Eocene aerosols (``eocene.oifs.aerosols``).
     - ``oifs/TL63L31/19900101/ICMGGECE4INIT``, ``ICMGGECE4INIUA``, ``ICMSHECE4INIT``;
       ``oifs/TL63L31/climate.v020/ICMCLECE4``, ``bare_soil_albedos.grb`` (grid, start date and
       climate version from ``grids.oifs``)
   * - ``nemo``
     - Ocean forcing and initial state: M2 tidal dissipation and bathymetry from Green & Huber;
       geothermal flux from the Eocene ocean-floor age; two ocean initial states (DeepMIP
       ``deepmip_cold`` profile and present-day WOA ``woa_pi``) on the present-day levels; runoff
       climatology set to 0 (rivers go through the runoff-mapper).
     - ``nemo/initial/zdfiwm_forcing_r720x360.nc``, ``Goutorbe_ghflux.nc``,
       ``woa13-levitus-L31_deepmip-30.nc``, ``woa13-levitus-L31_woa-pi.nc``;
       ``nemo/climatology/runoff_DaiTrenberth_PALEORCA2.nc``
   * - ``rnfm``
     - River basins traced on the Herold river flow direction, small basins merged, then regridded
       to the runoff-mapper grid; calving points equal arrival points (no ice sheets).
     - ``runoff-mapper/runoff_maps.nc``

Each step declares the files it reads and writes; ``ecefast eocene steps`` prints them, and
:doc:`workflow` describes each step in detail.

What a run checks
~~~~~~~~~~~~~~~~~

.. code-block:: text

   before:  config valid -> every declared input exists -> nothing written inside input/herold
   during:  each step writes all its declared outputs (atomically: no half-written files)
   after:   provenance.yml -> verify: all outputs exist, no NaN, Eocene vs present-day vertical grid

``--dry-run`` does the checks of the first line and shows the plan without writing anything.

The present-day period
----------------------

``ecefast present run`` has two steps, one per component:

``oifs`` (``ecefast oifs run``)
   The **OIFS generator**: makes the OIFS base data of ``grids.oifs`` from the finer
   ``present.oifs.source_grid`` (TL255L91). Its inputs exist on ECMWF Atos only. The Eocene
   workflow reads its OIFS base from ``eocene.input``, not from this output.
``nemo`` (``ecefast nemo run``)
   The **NEMO domain pipeline** for the present-day bathymetry: the bathymetry of
   ``{input}/nemo/domain/<present.nemo.source_grid>/domain_cfg.nc`` (eORCA1) on the grid of
   ``grids.nemo``. The DOMAINcfg part runs only on ECMWF Atos.

Present-day runs refuse to replace final files that exist already, unless ``--overwrite`` is
given.

The NEMO domain pipeline
~~~~~~~~~~~~~~~~~~~~~~~~

The same pipeline builds the present-day domain (``nemo`` step, ``PresentDayBathymetry``) and,
with ``eocene.nemo.domain: build``, the Eocene one (inside the ``domain`` step,
``EoceneBathymetry``). Each of its steps is switched on or off in ``<period>.nemo.steps``, or for
one run with ``--nemo a,b``:

.. code-block:: text

   coords_ori.nc --> coordinates         cell bounds, target + source grid  |
   bathymetry    --> bathymetry          remapped, corrected bathymetry     |  laptop
                     configure_domain    DOMAINcfg namelist                 |  and Atos
                            |
                            v
                     domain_cfg          run DOMAINcfg (raw output)         |
                     generate_mask       domain_cfg.nc, maskutil.nc         |  Atos only
                     generate_subbasins  subbasins.nc                       |  (need DOMAINcfg)

.. list-table::
   :header-rows: 1
   :widths: 18 52 30

   * - Step
     - What it does
     - Output (``<tmp>`` = ``<machine.tmpdir>/<period>/nemo``)
   * - ``coordinates``
     - Removes the halo of the PALEORCA2 coordinates; computes cell bounds of the target grid and,
       for the present day, of the source grid (eORCA1, from the input tree), for remapping.
     - ``<tmp>/coordinates/``
   * - ``bathymetry``
     - ``PresentDayBathymetry`` remaps eORCA1 (nearest neighbour), opens or closes straits and
       plots the land-sea mask; ``EoceneBathymetry`` remaps the Herold paleotopography (bilinear).
       Both apply ``<period>.nemo.minimum_depth`` (30 m).
     - ``<tmp>/bathymetry/PALEORCA2/``
   * - ``configure_domain``
     - Writes the DOMAINcfg namelist of the bathymetry.
     - ``<tmp>/domaincfg/`` (laptop) or ``<ecearth4_sources>/nemo-4.2/tools/DOMAINcfg/`` (Atos)
   * - ``domain_cfg``
     - Runs DOMAINcfg on ``machine.name`` (``atos``; ``fake`` in tests).
     - raw ``domain_cfg_<name>.nc``, ``mesh_mask_<name>.nc``
   * - ``generate_mask``
     - Post-processes the raw output into the files EC-Earth reads.
     - ``domain_cfg.nc``, ``maskutil.nc`` (see below)
   * - ``generate_subbasins``
     - Basin masks: Atlantic, Pacific, Indian, Indo-Pacific and global for present day; global
       only for the Eocene.
     - ``subbasins.nc`` (see below)

The final files go to ``<present.output>/nemo/domain/PALEORCA2/`` for the present day, and to
``<machine.tmpdir>/eocene/nemo/domain/PALEORCA2/`` for the Eocene build, from where the ``domain``
step installs ``domain_cfg.nc`` and ``maskutil.nc`` into ``eocene.output``.

Where each part runs
--------------------

.. list-table::
   :header-rows: 1
   :widths: 30 35 35

   * -
     - Laptop (``machine.name: local``)
     - ECMWF Atos (``machine.name: atos``)
   * - ``ecefast eocene run``
     - all steps; ``domain`` copies the Eocene domain built on Atos (``eocene.nemo.domain``: its
       directory)
     - all steps; ``domain`` builds the Eocene domain first (``eocene.nemo.domain: build``), or
       installs one from a directory
   * - ``ecefast nemo run``
     - ``coordinates``, ``bathymetry``, ``configure_domain``
     - all steps
   * - ``ecefast oifs run``
     - not available (inputs on Atos only)
     - all steps
   * - Tests (CI)
     - ``fake`` backend: DOMAINcfg replaced by a small stand-in
     -

Next: :doc:`installation`, then :doc:`quickstart`.
