Changelog
=========

All notable changes to this project are listed here. The format is based on
`Keep a Changelog <https://keepachangelog.com/en/1.1.0/>`_. Versions are ``0.MINOR.PATCH``
while the tool is in development: MINOR for new features or output changes, PATCH for fixes
that do not change output.

Sections: *Added*, *Changed*, *Fixed*, *Removed* and *Output*. *Output* lists every change to
the generated data (which files, and why); it stays empty for refactors.

Unreleased
----------

Added
~~~~~

- ``AGENTS.md``: rules for contributors and coding agents; ``CLAUDE.md`` imports it.
- ``CHANGELOG.rst``.
- ``get_ece4_data.sh``: fetches the OIFS TL63L31, NEMO PALEORCA2, OASIS PALEORCA2 and
  runoff-mapper subset of ECE4-DATA-V3 for local runs.
- Refactor plan towards a single ``ecefast`` package (``docs/refactor-plan.md``, issue #16).

Changed
~~~~~~~

- ``.gitignore`` ignores local test data and outputs.

0.0.2
-----

Changes up to this version are recorded only in the git history.
