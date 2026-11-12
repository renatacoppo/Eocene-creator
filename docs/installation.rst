Installation
============

CDO is not part of the environment: install it on the system, so the most recent release is used.

.. code-block:: bash

   brew install cdo          # macOS
   # Linux: conda install -c conda-forge cdo, or load the CDO module on the HPC

The exact CDO version matters: results can change between versions, and the frozen baseline
records the one it was made with (see ``AGENTS.md``, *Scientific integrity*).

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
