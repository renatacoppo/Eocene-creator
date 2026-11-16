ecefast
=======

``ecefast`` builds EC-Earth4 input data for a time period, on ECMWF Atos:

``present``
   The present-day base data of the model grids: the NEMO PALEORCA2 domain (``domain_cfg.nc``,
   ``maskutil.nc``, ``subbasins.nc``, ``section_ijglobal.diadct``), built with DOMAINcfg from the
   eORCA1 bathymetry of an ECE4-DATA tree.
``eocene``
   Eocene (DeepMIP) boundary conditions: a copy of the present-day tree in which the
   geography-dependent fields of OIFS TL63L31, NEMO PALEORCA2, OASIS and the runoff-mapper are
   replaced with those of Herold et al. (2014), with its own NEMO domain.

Each period writes a tree with the layout and file names of an EC-Earth4 input tree, so EC-Earth4
uses it in place of the original one.

- :doc:`quickstart`: set up on Atos and generate both trees.
- :doc:`configuration`: every key of the configuration file.
- :doc:`bathymetry`: how a NEMO bathymetry is made, and how to add a new one.
- :doc:`api`: the reference of the package, generated from the docstrings.

.. toctree::
   :maxdepth: 2
   :hidden:

   quickstart
   configuration
   bathymetry
   api
   contributing
   changelog
