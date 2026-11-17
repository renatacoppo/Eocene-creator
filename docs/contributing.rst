Contributing
============

The rules for contributors and coding agents are in
`AGENTS.md <https://github.com/renatacoppo/Eocene-creator/blob/main/AGENTS.md>`_:
design principles, architecture and naming, recipes to add a step or a component,
scientific integrity, tests, documentation, changelog and git workflow.

Checks before pushing:

.. code-block:: bash

   ruff check --fix . && ruff format .
   pytest -m "unit or integration"
   pip install -e ".[docs]" && sphinx-build -W -b html docs docs/_build/html

Checks on Atos
--------------

Coding agents and CI cannot run on Atos: a person runs these before a change to the domain
pipeline, the OIFS generator or the NEMO tools reaches ``main``, and reports them in the pull
request.

.. code-block:: bash

   module load cdo/2.5.3
   ECEFAST_HPC_DOMAINCFG_DIR=/path/to/ecearth4/sources/nemo-4.2/tools/DOMAINcfg \
       pytest -m hpc tests/hpc/test_domaincfg_contract.py      # fake backend still matches DOMAINcfg
   ecefast present run -c configs/atos.yml --overwrite
   ecefast eocene run -c configs/atos.yml --overwrite
   python scripts/compare_trees.py /path/to/OUTPUT/eocene /path/to/reference/eocene -o eocene.md

The ``fake`` backend (``machine.name: fake``, used by the tests) writes small files with the
structure of the DOMAINcfg and SECTIONS_DIADCT output, without running them: see
:class:`~ecefast.tools.ecearth.FakeBackend`. Never use it to produce data for EC-Earth.
