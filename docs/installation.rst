Installation
============

Create the conda environment from ``environment.yaml`` (it installs CDO, ecCodes, xESMF and the
package itself in editable mode), then activate it:

.. code-block:: bash

   git clone https://github.com/renatacoppo/Eocene-creator.git
   cd Eocene-creator
   mamba env create -f environment.yaml
   conda activate eocene

``conda env create -f environment.yaml`` works too. Check the installation:

.. code-block:: bash

   eocene --help
