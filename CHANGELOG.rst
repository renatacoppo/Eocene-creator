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

- ``tests/hpc/test_domaincfg_contract.py``: checks on Atos that the ``fake`` backend has the structure of
  the real DOMAINcfg output; checklist for a run on Atos in ``docs/external_tools.rst`` (#44).
- Tutorial notebooks in ``notebooks/tutorials/`` (``01_quickstart``, ``02_oifs``, ``03_nemo``,
  ``04_oasis_rnfm``), linked from ``docs/quickstart.rst``; plot helper ``plot_before_after`` (#43).
- ``ecefast eocene run`` checks the outputs of the steps that ran (``paleo/eocene/verify.py``): every
  declared output exists, no NaN in NetCDF data variables, vertical grid rule; integration test of
  the pipeline on a synthetic input tree that holds only the declared ``reads`` (#42).
- OIFS unit tests on synthetic data and tiny GRIB files (``tests/unit/oifs/``) (#40).
- CI step that fails on hardcoded personal or HPC paths (allowlist: the OIFS generator and planning
  notes) (#38).
- import-linter contracts in ``pyproject.toml`` (layers ``cli > paleo > components > tools >
  core``; OIFS, NEMO, OASIS and RNFM independent), checked by ``lint-imports`` in CI (#37).
- The Eocene ``domain`` step builds the Eocene domain with the NEMO domain pipeline when
  ``tools.backend`` is ``atos`` or ``fake`` (``local`` still installs ``tools.precomputed.domain``);
  the vertical grid check runs in both cases (#37).

- ``ecefast eocene run -c CONFIG [--steps a,b] [--dry-run] [--overwrite] [-l LEVEL]`` runs the
  Eocene pipeline (``paleo/eocene/pipeline.py``: ``stage``, ``domain``, ``oasis``, ``oifs``,
  ``nemo``, ``rnfm``); ``ecefast eocene steps`` lists the steps with what they need, read and
  write. A successful run writes ``provenance.yml`` into the output directory (steps, config file
  and its SHA-256, ``ecefast`` version and git commit, Python, CDO and ecCodes versions, start and
  end time); ``docs/workflow.rst`` describes the pipeline and each step (#36).
- ``ecefast.tools.ecearth`` with the ``atos``, ``local`` and ``fake`` backends for NEMO DOMAINcfg;
  config keys ``tools.atos.profile`` and ``tools.atos.oasis_lib_dir``; ``tools.backend`` accepts
  ``atos`` and ``fake`` (#35).
- Step runner: ``ComponentStep`` and ``run_pipeline`` (``needs`` order, preflight on ``reads``
  that lists every missing input at once, dry run, step selection, check of ``writes``) in
  ``core/steps.py``; run ``Context`` with path placeholders and read-only guards, and the
  ``Stage`` step (the former ``run_copy``, used by ``eocene --copy``) in ``core/workspace.py``;
  ``atomic_write`` in ``core/io.py``; ``docs/workflow.rst`` (#31).
- Config options ``eocene.oifs.aerosols`` (default ``false``) and ``eocene.oasis.constant_sst``
  (default ``290.0``) (#30).
- ``AGENTS.md``: rules for contributors and coding agents; ``CLAUDE.md`` imports it (#17).
- ``scripts/compare_outputs.py``: compares a run with the frozen baseline (NetCDF within
  ``rtol=1e-6``, GRIB with ``grib_compare``), with a self-test (#20).
- pytest markers (``unit``, ``integration``, ``local_data``, ``hpc``), first unit tests, a local
  regression test against the baseline and a CI workflow on Python 3.14 (#24).
- Documentation skeleton (Sphinx, reStructuredText, Read the Docs config) and a docs build
  workflow (#23).
- ruff configuration (line length 120, lenient rule set) and a lint/format check in CI;
  ``.git-blame-ignore-revs`` (#25).
- ``CHANGELOG.rst`` (#17).
- ``get_ece4_data.sh``: fetches the OIFS TL63L31, NEMO PALEORCA2, OASIS PALEORCA2 and
  runoff-mapper subset of ECE4-DATA-V3 for local runs (#17).
- Refactor plan towards a single ``ecefast`` package (``docs/refactor-plan.md``, issue #16) (#17).

Changed
~~~~~~~

- WEIGHTS namelists use ``{input}`` and ``{woce_dir}`` placeholders instead of HPC paths;
  ``create_corners.py`` (``--oifs-dir``, ``--tgt-dir``) and ``descriptor_generator.py``
  (``--oifs-bc``) take their paths as arguments; notebook paths are placeholders (#38).
- The NEMO domain pipeline writes ``subbasins.nc`` for every bathymetry; processors with
  ``regional_subbasins = False`` (``EoceneBathymetry``) get the global mask ``glomsk`` only;
  ``subbasins.py`` logs instead of printing; ``notebooks/analysis/eocene-subbasins.ipynb`` records
  the assessment of present-day basins on Eocene geography (#39).
- The vertical grid check of the ``domain`` step accepts differences up to 1e-6 m in ``nav_lev``
  and ``e3t_1d`` (floating-point rounding between DOMAINcfg builds and the fake backend, about
  1e-12 m); a different number of levels or a larger difference is still an error, whose message
  now shows the maximum absolute difference (#37).
- ``ecefast nemo domain -c CONFIG [--bathymetry NAME ...]`` replaces ``ecefast nemo-domain`` and
  its ``--only``. The NEMO domain pipeline runs DOMAINcfg through the backend of
  ``tools.backend`` (``run_domain_cfg.sh`` moved to ``tools/``) and stops before its first step
  if ``domain_cfg`` is on and the backend is not available. Bathymetry processors come from plain
  mappings passed by the caller (``components/nemo/bathymetry.PROCESSORS``,
  ``paleo/eocene/bathymetry.EOCENE_PROCESSORS``), so ``components`` no longer imports ``paleo``;
  an unknown ``processor`` name lists the known ones (#37).

- ``stage`` refuses an output directory that is not empty unless ``--overwrite`` is given (the old
  ``--copy`` always replaced it); configuration errors and preflight failures exit with code 1
  after one log line (#36).
- ``.gitignore`` ignores local test data and outputs (#17).
- Refactor plan and ``AGENTS.md`` revised after a feasibility review: domain-pipeline baseline,
  shared CDO wrapper in ``core``, per-file atomic writes, old ``eocene`` CLI and ``dirs:`` config
  dropped, phases 1 and 4 split, Eocene subbasins as the one planned output change (#18).
- Refactor work moves to the ``refactor`` branch; ``docs/refactor-plan.md`` gets the task and wave
  table; ``data/`` is ignored (#16).
- ``EoceneNEMO.create_ocean_init`` defaults to ``profile=None``, which builds both ocean initial
  files (``deepmip_cold`` and ``woa_pi``); the ``eocene`` CLI calls it without arguments (#19).
- ``get_ece4_data.sh`` also fetches ``nemo/domain/eORCA1/domain_cfg.nc`` (#20).
- Frozen baseline layout ``EOCENE-BASELINE/{eocene,domain}`` documented; the Eocene domain is read
  from ``data/``; pre-existing issues found while building the baseline added to the plan (#21).
- Notebooks moved to ``notebooks/analysis/`` with outputs cleared; ``get_ece4_data.sh`` and
  ``add_lonlat.py`` moved to ``scripts/``; placeholder paths in ``eocene/config.tmpl`` (#22).
- ``environment.yaml``: Python >= 3.11, all Python dependencies from conda-forge, ``jinja2`` and
  ``shapely`` declared; CDO is no longer part of the environment (system CDO, not pinned; the
  baseline records its version) (#24).
- One logger hierarchy ``ecefast``: ``core.logger.setup_logger`` replaces the NEMO
  ``setup_logging``, modules log through ``logging.getLogger(__name__)``; one shared, lazily
  created ``Cdo`` instance (``core.cdo.get_cdo``), so importing a module no longer starts CDO; the
  ``eocene`` CLI and the NEMO domain pipeline log the CDO version at start (#27).
- Whole repository formatted with ``ruff format`` in one formatting-only commit (#25).
- All code moves into one ``ecefast`` package with a ``src/`` layout (``core``, ``tools``,
  ``components``, ``paleo/eocene``, ``cli``); new ``ecefast`` command with the ``eocene`` and
  ``nemo-domain`` subcommands; the config template moves to ``configs/eocene.tmpl`` (#26).
- One configuration file per machine, schema 1 (``paths``, ``tools``, ``grids``, ``nemo_domain``,
  ``eocene``), read by ``ecefast.core.config.load_config``; the old ``dirs:`` and ``profiles:``
  formats are no longer read, see ``docs/configuration.rst`` (#30).
- GRIB and grid helpers merged into ``ecefast.core.grib``; Eocene OIFS field operations in
  ``paleo/eocene/oifs/fields.py``; the OIFS generator logs instead of printing (#29).
- NEMO domain post-processing: ``common/util.py`` is the one ``domain_cfg``/``maskutil`` writer,
  with docstrings and tests (#28).
- ``EoceneOASIS`` and a new ``EoceneRNFM`` (today's runoff code, moved as-is) are pipeline steps
  (``oasis``, ``rnfm``) with declared reads and writes; outputs written atomically (#32).
- ``EoceneNEMO`` is the ``nemo`` step (needs only ``stage``); new ``domain`` step
  (``EoceneDomain``) installs the precomputed Eocene domain and fails if its vertical grid
  (``nav_lev``, ``e3t_1d``) differs from the present-day one; outputs written atomically (#33).
- ``EoceneOIFS`` is the ``oifs`` step with declared reads and writes; outputs written
  atomically (#34).
- HPC modules moved to ``tools/hpc_profiles.yaml``; ``run_domain_cfg.sh`` reads them with the
  running Python and adds the OASIS library to ``LD_LIBRARY_PATH`` only if
  ``tools.atos.oasis_lib_dir`` is set (it was a hardcoded path) (#35).

Fixed
~~~~~

- ``load_grib_var_spec`` returned ``lat_bnds`` instead of the field for spectral GRIB files (#43).
- Tests restore the ``ecefast`` logger after each test, so the ``local_data`` NEMO domain test no longer
  breaks the logger unit test (#41).
- NEMO domain pipeline: with ``domaincfg_dir: null`` the ``generate_mask`` and
  ``generate_subbasins`` steps looked for the DOMAINcfg output in a relative ``DOMAINcfg/``
  folder instead of next to the namelists (``output_dir/domain``) (#37).

- NEMO domain pipeline: helper scripts run with the current Python interpreter, not ``python3``
  from ``PATH``, and are found from the package directory (#26).
- OIFS: intermediate files (``landsea_mask.nc``, ``orography.nc``, ``sd_orography.nc``, their
  ``_remap`` versions, the aerosol standard atmosphere) go to ``tmpdir`` instead of the read-only
  Herold folder (#34).
- ``run_domain_cfg.sh`` could not import its module list after the ``src/`` move (#35).

Removed
~~~~~~~

- Config key ``nemo_domain.mesh_mask`` and the ``data/eORCA1/mesh_mask.nc`` input: the source grid of the
  present-day bathymetry is read from ``{input}/nemo/domain/<grids.source>/domain_cfg.nc``, which holds the
  same horizontal grid; an old config with the key fails with an unknown-key error (pushed to ``refactor``).
- The old ``eocene`` command and ``cli/eocene.py`` (``-r/--run``, ``--copy``), replaced by
  ``ecefast eocene run`` (#36).
- Tracked ``__pycache__`` files; ``modify_oifs.ipynb`` and ``modify_nemo.ipynb``, replaced by
  ``notebooks/analysis/plots.ipynb`` (#22).
- ``nemo-workflow.sh``, superseded by the NEMO domain pipeline (#26).
- Standalone ``domain/mask_util.py``, a duplicate of the pipeline's ``maskutil`` writer (#28).
- ``configs/eocene.tmpl`` and the in-package ``nemo_workflow.yaml``, replaced by
  ``configs/laptop.tmpl`` and ``configs/atos.tmpl`` (#30).

Output
~~~~~~

- NEMO domain pipeline: the intermediate ``coordinates/eORCA1/coords_bounds_{T,F}.nc`` carry the global
  attributes of the eORCA1 ``domain_cfg.nc`` (``CfgName``, ``Iperio``, ``NFold``, ...); their data and every
  bathymetry, namelist and domain file are unchanged (pushed to ``refactor``).
- NEMO domain pipeline: ``domain/PALEORCA2/eocene/subbasins.nc`` is now built, with ``glomsk`` only
  (present-day basin polygons do not fit Eocene geography; Eocene basins are a later task) (#39).
- ``nemo/initial/woa13-levitus-L31_deepmip-30.nc`` is now built alongside
  ``nemo/initial/woa13-levitus-L31_woa-pi.nc`` (#19).

0.0.2
-----

Changes up to this version are recorded only in the git history.
