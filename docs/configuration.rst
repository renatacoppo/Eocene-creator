Configuration
=============

The ``eocene`` command reads a YAML file with a top-level ``dirs`` section. Start from
``eocene/config.tmpl``:

.. code-block:: yaml

   dirs:
     input: /path/to/ECE4-DATA-V3
     output: /path/to/EOCENE-TEST
     herold: /path/to/herold-et-al-2014/Supp
     domain: /path/to/domain/PALEORCA2/eocene
     tmpdir: /path/to/eocene_tmp

.. list-table::
   :header-rows: 1
   :widths: 15 85

   * - Key
     - Meaning
   * - ``input``
     - EC-Earth4 input tree (ECE4-DATA-V3). Read-only: the workflow never writes here.
   * - ``output``
     - Tree where the copied and generated files are written. ``--copy`` overwrites it.
   * - ``herold``
     - Herold et al. (2014) supplementary data.
   * - ``domain``
     - Eocene PALEORCA2 domain: directory with ``domain_cfg.nc`` and ``maskutil.nc``.
   * - ``tmpdir``
     - Temporary directory. Reserved, not read yet.

The keys have no default. ``input`` and ``output`` are read by every part of the workflow,
``herold`` by ``oifs``, ``nemo`` and ``rnfm``, ``domain`` only by ``nemo``.
