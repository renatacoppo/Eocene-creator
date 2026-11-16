Installation
============

CDO is not part of the environment, but the 2.5 series is required for now:

.. code-block:: bash

   module load cdo/2.5.3                     # ECMWF Atos
   conda install -c conda-forge "cdo=2.5"    # laptop (macOS or Linux); Homebrew ships only the latest

The exact CDO version matters: the land-sea mask of the NEMO bathymetries has cells with an ocean
fraction of exactly 0.5, and the rounding that decides them changes between versions (2.6.x moves
some cells compared with 2.5.x, which made the domains of the existing experiments). The frozen
baseline records the version it was made with (see ``AGENTS.md``, *Scientific integrity*).

Create the conda environment from ``environment.yaml`` (it installs ecCodes, xESMF, the Python
dependencies and the package itself in editable mode), then activate it:

.. code-block:: bash

   git clone https://github.com/renatacoppo/Eocene-creator.git
   cd Eocene-creator
   mamba env create -f environment.yaml
   conda activate eocene

``conda env create -f environment.yaml`` works too. Check the installation:

.. code-block:: bash

   eocene --help
