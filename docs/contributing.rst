Contributing
============

The rules for contributors and coding agents are in
`AGENTS.md <https://github.com/renatacoppo/Eocene-creator/blob/main/AGENTS.md>`_:
design principles, architecture and naming, recipes to add a step or a component,
scientific integrity, tests, documentation, changelog and git workflow.

Before pushing, build the docs without warnings:

.. code-block:: bash

   pip install sphinx sphinx-rtd-theme
   sphinx-build -W -b html docs docs/_build/html
