Quickstart
==========

All commands run from the repository root, in the ``eocene`` environment
(see :doc:`installation`).

1. Fetch the input data
-----------------------

``scripts/get_ece4_data.sh`` copies the subset of ECE4-DATA-V3 used by the workflow
(OIFS TL63L31, NEMO PALEORCA2, OASIS PALEORCA2, runoff-mapper) into ``ECE4-DATA-V3/``.
Give the source as an argument or in ``ECE4_DATA_SRC``:

.. code-block:: bash

   ECE4_DATA_SRC=user@host:/path/to/ECE4-DATA-V3 ./scripts/get_ece4_data.sh

The Herold et al. (2014) datasets and the Eocene PALEORCA2 domain are copied by hand
(from the HPC or the paper supplement).

2. Write a configuration file
-----------------------------

.. code-block:: bash

   cp configs/laptop.tmpl configs/laptop.yml

Then set the paths in ``configs/laptop.yml`` (see :doc:`configuration`). ``configs/*.yml`` is
ignored by git. On ECMWF Atos start from ``configs/atos.tmpl``.

3. Run the workflow
-------------------

Check that every input exists and see what would run, without writing anything:

.. code-block:: bash

   ecefast eocene run -c configs/laptop.yml --dry-run

Copy the input subtree to the output directory and run every step (``--overwrite`` replaces an
output directory that is not empty):

.. code-block:: bash

   ecefast eocene run -c configs/laptop.yml --overwrite

Rerun some steps (``domain``, ``oasis``, ``oifs``, ``nemo``, ``rnfm``) on that output, with more
logging:

.. code-block:: bash

   ecefast eocene run -c configs/laptop.yml --steps nemo -l DEBUG

Options:

.. code-block:: text

   -c, --config      Configuration file (schema 1). Required.
   --steps a,b       Comma-separated step names. Default: all steps.
   --dry-run         Check all inputs and show the plan; write nothing.
   --overwrite       Let 'stage' replace an output directory that is not empty.
   -l, --loglevel    Log level. Default: INFO.

To build NEMO domains from the bathymetries of the ``nemo_domain`` section (on a laptop: the
coordinates, bathymetries and DOMAINcfg namelists; DOMAINcfg itself runs on Atos):

.. code-block:: bash

   ecefast nemo domain -c configs/laptop.yml

``ecefast eocene steps`` lists the steps. The pipeline, the steps and ``provenance.yml`` are
described in :doc:`workflow`.

Tutorials
---------

The notebooks in ``notebooks/tutorials/`` show the workflow step by step, with a plot of each field before
(present-day input) and after (Eocene output). Read them in order:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Notebook
     - What it shows
   * - ``01_quickstart.ipynb``
     - The steps above from Python: check the input data, write a configuration from ``configs/laptop.tmpl``,
       ``ecefast eocene steps``, a dry run, a full run, the output tree and ``provenance.yml``.
   * - ``02_oifs.ipynb``
     - The ``oifs`` step: land-sea mask, orography, sub-grid orography, vegetation, albedo and leaf area index.
   * - ``03_nemo.ipynb``
     - The ``domain`` and ``nemo`` steps: Eocene bathymetry, the vertical grid check, tidal mixing, geothermal heat
       flux, ocean initial state, runoff; the laptop part of ``ecefast nemo domain``.
   * - ``04_oasis_rnfm.ipynb``
     - The ``oasis`` and ``rnfm`` steps (both small, so they share a notebook): OASIS restart and river basins.

They run in the ``eocene`` environment with Jupyter (``ipykernel`` is part of the environment), in about two
minutes in all, on the local test data. Two environment variables give the paths:

.. code-block:: bash

   export ECEFAST_TEST_DATA=/path/to/data          # holds ECE4-DATA-V3/, herold-et-al-2014/, data/
   export ECEFAST_TUTORIAL_DIR=/path/to/scratch    # optional; default: ecefast-tutorial in the system temp dir

``01_quickstart.ipynb`` writes the configuration and the output into ``ECEFAST_TUTORIAL_DIR``; the other notebooks
read them, so run it first.
