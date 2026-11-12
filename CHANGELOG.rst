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

- ``AGENTS.md``: rules for contributors and coding agents; ``CLAUDE.md`` imports it (#17).
- ``scripts/compare_outputs.py``: compares a run with the frozen baseline (NetCDF within
  ``rtol=1e-6``, GRIB with ``grib_compare``), with a self-test (#20).
- ``CHANGELOG.rst`` (#17).
- ``get_ece4_data.sh``: fetches the OIFS TL63L31, NEMO PALEORCA2, OASIS PALEORCA2 and
  runoff-mapper subset of ECE4-DATA-V3 for local runs (#17).
- Refactor plan towards a single ``ecefast`` package (``docs/refactor-plan.md``, issue #16) (#17).

Changed
~~~~~~~

- ``.gitignore`` ignores local test data and outputs (#17).
- Refactor plan and ``AGENTS.md`` revised after a feasibility review: domain-pipeline baseline,
  shared CDO wrapper in ``core``, per-file atomic writes, old ``eocene`` CLI and ``dirs:`` config
  dropped, phases 1 and 4 split, Eocene subbasins as the one planned output change (#18).
- Refactor work moves to the ``refactor`` branch; ``docs/refactor-plan.md`` gets the task and wave
  table; ``data/`` is ignored (#16).
- ``EoceneNEMO.create_ocean_init`` defaults to ``profile=None``, which builds both ocean initial
  files (``deepmip_cold`` and ``woa_pi``); the ``eocene`` CLI calls it without arguments (#19).
- ``get_ece4_data.sh`` also fetches ``nemo/domain/eORCA1/domain_cfg.nc`` (#20).

Output
~~~~~~

- ``nemo/initial/woa13-levitus-L31_deepmip-30.nc`` is now built alongside
  ``nemo/initial/woa13-levitus-L31_woa-pi.nc`` (#19).

0.0.2
-----

Changes up to this version are recorded only in the git history.
