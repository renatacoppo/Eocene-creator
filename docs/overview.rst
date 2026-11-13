Overview
========

``ecefast`` turns the present-day EC-Earth4 input data into **Eocene (DeepMIP) boundary
conditions**. It copies the files EC-Earth4 reads (atmosphere OIFS TL63L31, ocean NEMO PALEORCA2,
coupler OASIS, runoff-mapper) and replaces their geography-dependent fields with the Eocene ones of
Herold et al. (2014). The output tree has the layout and file names of the input tree, so EC-Earth4
uses it in place of the present-day one.

Three commands do the work:

``ecefast eocene run``
   The **Eocene workflow**: six steps that build the Eocene input tree. Runs on a laptop in about
   a minute.
``ecefast nemo domain``
   The **NEMO domain pipeline**: builds NEMO ocean domains (grid, bathymetry, masks) from
   bathymetries. The DOMAINcfg part runs only on ECMWF Atos; the ``domain`` step of the Eocene
   workflow either uses its result or runs it.
``ecefast oifs data``
   The **OIFS generator**: makes the present-day OIFS base data of a resolution (e.g. TL63L31) from a
   finer one (TL255L91). Its inputs exist on ECMWF Atos only. The Eocene workflow reads its OIFS base
   from ECE4-DATA, not from this output.

Commands, sections and outputs
------------------------------

Each command reads its own section of the configuration file (:doc:`configuration`) and writes
only to its own ``output_dir``. A later run reads the output of an earlier one through a
``{section.key}`` placeholder; ``inputs`` are shared and read-only.

.. code-block:: text

   config file             command                 writes only to
   -----------             -------                 --------------
   inputs:  ece4_data, herold   (read-only, shared by every command)
   machine: name (local | atos | fake)

   nemo:                   ecefast nemo domain     nemo.domain.output_dir   = OUTPUT/nemo-domain/
     grid                                            nemo/domain/<grid>/<name>/  final files
     domain: ...                                     work/                       intermediates
                                                          |
                                                          | {nemo.domain.output_dir}/nemo/domain/
                                                          v   {nemo.grid}/eocene
   eocene:                 ecefast eocene run      eocene.output_dir        = OUTPUT/eocene/
     domain: from, build                             oifs/ nemo/ oasis/ runoff-mapper/  (EC-Earth tree)
     oifs, oasis                                     provenance.yml

   oifs:                   ecefast oifs data       oifs.data.output_dir     = OUTPUT/oifs-data/
     grid                  (Atos inputs)             oifs/<grid>/<startdate>/    initial state
     data: ...                                       oifs/<grid>/<climate>/      climate file
                                                     work/                       intermediates

On a laptop ``eocene.domain.from`` points at the Eocene domain copied from Atos; on Atos at the
output of ``ecefast nemo domain``, or ``eocene.domain.build: true`` runs the domain pipeline inside
the ``domain`` step. The frozen references live next to the outputs in ``BASELINE/<command>``.

Inputs and outputs
------------------

.. code-block:: text

   INPUTS (read-only)                               OUTPUT (eocene.output_dir)
   ------------------                               ---------------------
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
     - ``inputs.ece4_data``
     - The present-day files to modify, and the present-day domains. Fetched with
       ``scripts/get_ece4_data.sh``.
   * - Herold et al. (2014) supplement
     - ``inputs.herold``
     - Eocene topography and bathymetry, subgrid orography, biomes, river flow direction, M2 tidal
       dissipation, ocean-floor age.
   * - PALEORCA2 ``coords_ori.nc``
     - ``nemo.domain.coords_ori``
     - The PALEORCA2 grid, for the NEMO domain pipeline.
   * - Eocene NEMO domain
     - ``eocene.domain.from``
     - ``domain_cfg.nc`` and ``maskutil.nc`` built on Atos; used on a laptop instead of running
       DOMAINcfg.

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
     - Files written (under ``eocene.output_dir``)
   * - ``stage``
     - Copies the base files of the input tree: ``oifs/`` (grid, ``ifsdata``, ``composition``,
       tables), ``nemo/`` (``initial``, ``climatology``, ``cfc``, ``weights``),
       ``oasis/PALEORCA2``; symlinks ``cmip6-data``. Refuses a non-empty output without
       ``--overwrite``.
     - ``oifs/``, ``nemo/``, ``oasis/PALEORCA2/``
   * - ``domain``
     - Installs the Eocene PALEORCA2 domain from ``eocene.domain.from``: the one built on Atos
       (laptop), the output of ``ecefast nemo domain``, or built first by the NEMO domain pipeline
       (``eocene.domain.build: true``, Atos). Fails if its vertical levels differ from the
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
       ``oifs/TL63L31/climate.v020/ICMCLECE4``, ``bare_soil_albedos.grb``
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

The NEMO domain pipeline
------------------------

``ecefast nemo domain`` builds one NEMO domain per bathymetry listed in ``nemo.domain.bathymetries``
(``present_day`` from the eORCA1 domain of the input tree, ``eocene`` from Herold). Each step is
switched on or off in ``nemo.domain.steps``:

.. code-block:: text

   coords_ori.nc --> coordinates         cell bounds, PALEORCA2 + eORCA1  |
   bathymetries  --> bathymetry          one bathymetry per name          |  laptop
                     configure_domain    one namelist per name            |  and Atos
                            |
                            v
                     domain_cfg          run DOMAINcfg (raw output)       |
                     generate_mask       domain_cfg.nc, maskutil.nc       |  Atos only
                     generate_subbasins  subbasins.nc                     |  (need DOMAINcfg)

.. list-table::
   :header-rows: 1
   :widths: 18 52 30

   * - Step
     - What it does
     - Output (under ``nemo.domain.output_dir``)
   * - ``coordinates``
     - Removes the halo of the PALEORCA2 coordinates; computes cell bounds of the target grid and
       of the source grid (eORCA1, from the input tree), for remapping.
     - ``work/coordinates/``
   * - ``bathymetry``
     - One processor per bathymetry: ``PresentDayBathymetry`` remaps eORCA1 (nearest neighbour) and
       opens or closes straits; ``EoceneBathymetry`` remaps the Herold paleotopography (bilinear).
       Both apply the minimum depth (30 m).
     - ``work/bathymetry/PALEORCA2/``
   * - ``configure_domain``
     - Writes one DOMAINcfg namelist per bathymetry.
     - ``work/domaincfg/`` (laptop) or ``<tools_dir>/DOMAINcfg/`` (Atos)
   * - ``domain_cfg``
     - Runs DOMAINcfg on ``machine.name`` (``atos``; ``fake`` in tests).
     - raw ``domain_cfg_<name>.nc``, ``mesh_mask_<name>.nc``
   * - ``generate_mask``
     - Post-processes the raw output into the files EC-Earth reads.
     - ``nemo/domain/PALEORCA2/<name>/domain_cfg.nc``, ``maskutil.nc``
   * - ``generate_subbasins``
     - Basin masks: Atlantic, Pacific, Indian, Indo-Pacific and global for present day; global
       only for the Eocene.
     - ``nemo/domain/PALEORCA2/<name>/subbasins.nc``

Where each part runs
--------------------

.. list-table::
   :header-rows: 1
   :widths: 30 35 35

   * -
     - Laptop (``machine.name: local``)
     - ECMWF Atos (``machine.name: atos``)
   * - ``ecefast eocene run``
     - all steps; ``domain`` copies the Eocene domain built on Atos (``eocene.domain.from``)
     - all steps; ``domain`` installs the output of ``ecefast nemo domain``, or builds it first
       (``eocene.domain.build: true``)
   * - ``ecefast nemo domain``
     - ``coordinates``, ``bathymetry``, ``configure_domain``
     - all steps
   * - Tests (CI)
     - ``fake`` backend: DOMAINcfg replaced by a small stand-in
     -

Next: :doc:`installation`, then :doc:`quickstart`.
