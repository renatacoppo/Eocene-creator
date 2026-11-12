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

Copy the input subtree to the output directory and run every component:

.. code-block:: bash

   ecefast eocene -c configs/laptop.yml --run all --copy

Run one component (``oifs``, ``nemo``, ``oasis`` or ``rnfm``) with more logging:

.. code-block:: bash

   ecefast eocene -c configs/laptop.yml --run nemo -l DEBUG

Options:

.. code-block:: text

   -c, --config     Path to the YAML configuration file. Required.
   -l, --loglevel   Logging level. Default: INFO.
   -r, --run        Part of the workflow to run: oasis, oifs, nemo, rnfm, all. Default: all.
   --copy           Copy the required input subtree to the output directory before running.
