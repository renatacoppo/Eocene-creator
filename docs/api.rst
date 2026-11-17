API reference
=============

Generated from the docstrings. The package has one-way layers: ``core`` → ``tools`` →
``components`` → ``periods`` → ``cli``.

Core
----

.. automodule:: ecefast.core.config
   :members: Config, load_config, ConfigError, DATA_VERSIONS

.. automodule:: ecefast.core.cdo
   :members: check_cdo_version

.. automodule:: ecefast.core.steps
   :members:

.. automodule:: ecefast.core.runner
   :members:

.. automodule:: ecefast.core.workspace
   :members:

.. automodule:: ecefast.core.layout
   :members:

.. automodule:: ecefast.core.io
   :members:

.. automodule:: ecefast.core.provenance
   :members:

.. automodule:: ecefast.core.grib
   :members:
   :undoc-members:

.. automodule:: ecefast.core.plotting
   :members:

EC-Earth tools
--------------

.. automodule:: ecefast.tools.ecearth
   :members: EcEarthTools, AtosBackend, LocalBackend, FakeBackend, get_backend, hpc_modules, vertical_grid

NEMO
----

.. automodule:: ecefast.components.nemo.domain.pipeline
   :members: NEMOWorkflow

.. automodule:: ecefast.components.nemo.bathymetry.base
   :members: BathymetryProcessor, MASK_PRESETS

.. automodule:: ecefast.components.nemo.config.loader
   :members: get_corrections_for_grid

.. automodule:: ecefast.components.nemo.sections
   :members:

.. automodule:: ecefast.components.nemo.plots
   :members:

OIFS
----

.. automodule:: ecefast.components.oifs.generator
   :members: OIFSData

.. automodule:: ecefast.components.oifs.initial_state

.. automodule:: ecefast.components.oifs.climate

.. automodule:: ecefast.components.oifs.corners
   :members:

.. automodule:: ecefast.components.oifs.grid_files
   :members:

.. automodule:: ecefast.components.oifs.plots
   :members:

.. automodule:: ecefast.components.oifs.land_cover

Plots
-----

.. automodule:: ecefast.periods.plots
   :members:

Present-day period
------------------

.. automodule:: ecefast.periods.present.pipeline
   :members:

.. automodule:: ecefast.periods.present.bathymetry
   :members:

Eocene period
-------------

.. automodule:: ecefast.periods.eocene.pipeline
   :members:

.. automodule:: ecefast.periods.eocene.bathymetry
   :members:

.. automodule:: ecefast.periods.eocene.nemo.domain
   :members:

.. automodule:: ecefast.periods.eocene.oifs.eoceneOIFS
   :members:
   :undoc-members:

.. automodule:: ecefast.periods.eocene.nemo.eoceneNEMO
   :members:
   :undoc-members:

.. automodule:: ecefast.periods.eocene.oasis.eoceneOASIS
   :members:
   :undoc-members:

.. automodule:: ecefast.periods.eocene.rnfm.eoceneRNFM
   :members:
   :undoc-members:

.. automodule:: ecefast.periods.eocene.verify
   :members:
