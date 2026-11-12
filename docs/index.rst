ecefast
=======

``ecefast`` builds EC-Earth4 input data (OIFS TL63L31, NEMO PALEORCA2, OASIS, runoff-mapper)
and modifies it for Eocene (DeepMIP) boundary conditions, starting from the ECE4-DATA-V3 tree
and the Herold et al. (2014) paleo datasets.

The code is being restructured into a single ``ecefast`` package; until then the Eocene
workflow is run with the ``eocene`` command described in :doc:`quickstart`.

.. toctree::
   :maxdepth: 2
   :caption: User guide

   installation
   quickstart
   configuration
   workflow
   external_tools

.. toctree::
   :maxdepth: 2
   :caption: Developer guide

   contributing
   api
   changelog
