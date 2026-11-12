External tools
==============

Only one EC-Earth program is needed outside Python: the NEMO **DOMAINcfg** tool, which turns a
bathymetry and the PALEORCA2 coordinates into the NEMO domain (``domain_cfg.nc``, ``mesh_mask.nc``).
It is part of the EC-Earth4 NEMO sources and runs only where EC-Earth is built: ECMWF Atos.

The code reaches it through one small interface, :mod:`ecefast.tools.ecearth`, with three
versions ("backends"). The domain pipeline writes one ``namelist_cfg_<name>`` per bathymetry and
asks the backend to run DOMAINcfg; every backend leaves the raw ``domain_cfg_<name>.nc`` and
``mesh_mask_<name>.nc`` next to the namelists, which the pipeline then post-processes into
``domain_cfg.nc`` and ``maskutil.nc``.

Two commands use the backend of ``tools.backend``:

- ``ecefast nemo domain`` (the domain pipeline): its ``domain_cfg`` step runs DOMAINcfg through
  the backend. If the step is on and the backend is not available (``local``, or ``atos`` off
  Atos), the pipeline stops before its first step; on a laptop the step is off.
- the ``domain`` step of ``ecefast eocene run``: with ``local`` it installs the domain of
  ``tools.precomputed.domain``; with ``atos`` or ``fake`` it builds the Eocene domain with the
  domain pipeline (bathymetry ``eocene`` only, the steps of ``nemo_domain.steps``) and installs
  the post-processed ``domain_cfg.nc`` and ``maskutil.nc``. The vertical grid check runs in both
  cases (see :doc:`workflow`).

Backends
--------

Select the backend with ``tools.backend`` (see :doc:`configuration`):

.. list-table::
   :header-rows: 1
   :widths: 10 25 65

   * - Backend
     - Where
     - What it does
   * - ``atos``
     - ECMWF Atos
     - Loads the HPC modules, compiles DOMAINcfg if ``make_domain_cfg.exe`` is missing, and runs
       it once per bathymetry (``run_domain_cfg.sh``).
   * - ``local``
     - laptop, workstation (default)
     - Nothing: DOMAINcfg is not available. The ``domain`` step uses the Eocene domain built on
       Atos, given with ``tools.precomputed.domain``. Asking it to run DOMAINcfg stops with an
       error that says so.
   * - ``fake``
     - tests, CI
     - Writes small but valid raw outputs with the structure of DOMAINcfg's, without running
       DOMAINcfg (see :ref:`fake-backend`).

``atos``: DOMAINcfg on ECMWF Atos
---------------------------------

.. code-block:: yaml

   tools:
     backend: atos
     atos:
       profile: atos            # modules from ecefast/tools/hpc_profiles.yaml
       oasis_lib_dir: /path/to/ecearth4/sources/oasis3-mct-5.2/arch_ecearth/lib
   nemo_domain:
     domaincfg_dir: /path/to/ecearth4/sources/nemo-4.2/tools

The namelists must be in the ``DOMAINcfg/`` folder of the NEMO tools directory
(``nemo_domain.domaincfg_dir``), which holds ``maketools``. The backend runs

.. code-block:: bash

   bash src/ecefast/tools/run_domain_cfg.sh <nemo tools dir> <name> [<name> ...]

which

1. reads the module list of the profile with the Python running ``ecefast``
   (``python -m ecefast.tools.ecearth atos`` prints it), runs ``module reset`` and loads the modules;
2. adds the library directories of the modules and ``tools.atos.oasis_lib_dir`` (if set) to
   ``LD_LIBRARY_PATH``;
3. compiles DOMAINcfg with ``./maketools -m ecearth -n DOMAINcfg`` unless
   ``DOMAINcfg/make_domain_cfg.exe`` exists;
4. for each name, copies ``namelist_cfg_<name>`` to ``namelist_cfg``, runs ``make_domain_cfg.exe``
   and renames the outputs to ``domain_cfg_<name>.nc`` and ``mesh_mask_<name>.nc``. A non-zero
   exit (DOMAINcfg sometimes crashes after writing its output) is accepted only if CDO can read
   ``domain_cfg.nc``.

HPC profiles live in ``src/ecefast/tools/hpc_profiles.yaml``: a name, a description and the list
of modules, loaded in order. Only ``atos`` is defined.

.. _fake-backend:

``fake``: tests without DOMAINcfg
---------------------------------

For each ``namelist_cfg_<name>`` the fake backend reads the bathymetry (``cn_topo``, variable
``cn_bath``) and the coordinates (``cn_fcoord``), and writes ``domain_cfg_<name>.nc`` and
``mesh_mask_<name>.nc`` with the dimensions, variable names, order and dtypes of the DOMAINcfg
output, so that the post-processing and the Eocene workflow can run on them:

- horizontal grid (``glam*``, ``gphi*``, ``e1*``, ``e2*``) copied from the coordinates file,
  ``ff_t`` and ``ff_f`` from the latitude;
- vertical grid (``nav_lev``, ``gdept_1d``, ``gdepw_1d``, ``e3t_1d``, ``e3w_1d``) computed with the
  DOMAINcfg formula from the analytic ORCA coefficients of the namelist (``ppsur``, ``ppa0``,
  ``ppa1``, ``ppkth``, ``ppacr``); for PALEORCA2 L31 this is the grid of the real domain;
- ``bottom_level`` (and ``mbathy``): number of levels whose top lies above the sea floor, at most
  ``jpkglo - 1``; ``top_level`` is 1 over the ocean;
- ``tmask``, ``umask``, ``vmask``, ``fmask`` and the ``*maskutil`` from ``bottom_level``.

What it does **not** do, so its numbers are not those of DOMAINcfg:

- no partial steps: the 3-D scale factors (``e3t_0``, ...) repeat the 1-D ones;
- no minimum depth or ``rn_e3zps_*`` adjustment of the bathymetry;
- no closed seas, no ice-shelf cavities (``isf_draft`` and ``misf`` are 0);
- no north-fold treatment of the masks (periodic in ``x``, closed at the last row);
- no ``gdept_0`` / ``gdepw_0`` and no ``DOMAIN_*`` global attributes;
- other vertical grid definitions (``ppdzmin``/``pphmax``, double tanh) are refused.

Its ``e3t_1d`` differs from the one of the real PALEORCA2 L31 domain by rounding (about 1e-12 m:
NumPy and the Fortran build evaluate the same formula), while ``nav_lev`` is equal. The vertical
grid check of the Eocene ``domain`` step allows 1e-6 m for such rounding, so the fake domain
passes it.

Use it to test the workflow, never to produce a domain for EC-Earth.

API
---

.. automodule:: ecefast.tools.ecearth
   :members: EcEarthTools, AtosBackend, LocalBackend, FakeBackend, get_backend, hpc_modules, vertical_grid
