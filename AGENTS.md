# AGENTS.md

Rules for anyone changing this repository: humans and coding agents alike.

**When in doubt, ask.** If a rule is unclear, blocks you, or two rules conflict, stop and ask
(on the PR, the issue, or the person you are working with). Do not guess and do not work around
a rule.

All code, comments, docstrings, documentation, commit messages, issues and PRs are written in
**English**.

## What this repo does

Builds EC-Earth4 input data (OIFS TL63L31, NEMO PALEORCA2, OASIS, runoff-mapper) and modifies it
for Eocene (DeepMIP) boundary conditions, starting from the ECE4-DATA-V3 tree and the
Herold et al. (2014) paleo datasets.

## Status: refactor in progress

The repo is being restructured into a single `ecefast` package
(issue [#16](https://github.com/renatacoppo/Eocene-creator/issues/16), plan in
[docs/refactor-plan.md](docs/refactor-plan.md)). Some rules below refer to pieces that do not
exist yet; they are tagged **(from phase N)** and apply as soon as that phase is merged into
the `refactor` branch. Until then, follow the spirit of the rule in the current layout
(`ecefast/`, `eocene/`). Refactor work targets the `refactor` branch, not `main` (see
[Git and pull requests](#git-and-pull-requests)).

Target layout:

```
src/ecefast/
  core/          config, logging, workspace, io, cdo, grib, ComponentStep, runner  (no internal deps)
  tools/         EC-Earth binaries and HPC modules: ecearth backends               (imports core)
  components/    oifs/ nemo/ oasis/ rnfm/                                    (imports core, tools)
  paleo/eocene/  Eocene steps, EoceneBathymetry, PIPELINE                    (imports components)
  cli/           argument parsing only                                       (imports everything)
```

## Commands

```bash
# environment (conda env name: eocene)
mamba env create -f environment.yaml
conda activate eocene
pip install -e .                       # (from phase 1) pip install -e ".[dev,docs]"

# local test data, see "Local test data" below
ECE4_DATA_SRC=user@host:/path/to/ECE4-DATA-V3 ./get_ece4_data.sh   # moves to scripts/ in phase 1

# run the Eocene workflow
cp eocene/config.tmpl eocene/config.yml          # then set the paths; config.yml is gitignored
eocene -c eocene/config.yml --run all --copy     # same as ./eocene/cli_eocene.py (removed in phase 4b)
eocene -c eocene/config.yml --run nemo -l DEBUG  # one component: oifs, nemo, oasis, rnfm
ecefast eocene run -c configs/laptop.yml [--steps nemo] [--dry-run]   # (from phase 4b) replaces the above

# checks before pushing
ruff check --fix . && ruff format .                             # (from phase 1)
pytest -m "unit or integration"                                 # (from phase 1)
python scripts/compare_outputs.py EOCENE-BASELINE/eocene EOCENE-TEST          # Eocene workflow
python scripts/compare_outputs.py EOCENE-BASELINE/domain EOCENE-DOMAIN-TEST   # NEMO domain pipeline
sphinx-build -W -b html docs docs/_build/html                   # (from phase 1b)
```

## Local test data

All of these live at the repo root and are gitignored; never commit them.

| Directory | What | How to get it |
|---|---|---|
| `ECE4-DATA-V3/` | subset of the EC-Earth4 input tree, including the eORCA1 domain used by the present-day bathymetry | `get_ece4_data.sh` (source from argument or `ECE4_DATA_SRC`) |
| `data/` | inputs of the NEMO domain pipeline (`PALEORCA2/coords_ori.nc`, `eORCA1/mesh_mask.nc`) and the Eocene domain built on Atos (`domain/PALEORCA2/eocene/`, the config's `dirs.domain`) | copy from the HPC |
| `herold-et-al-2014/` | Herold et al. (2014) supplementary data | copy from the HPC or the paper supplement |
| `EOCENE-TEST/` | output of your Eocene run | `eocene -c eocene/config.yml --run all --copy` |
| `EOCENE-DOMAIN-TEST/` | output of your domain-pipeline run (laptop part); always at this path in the main checkout, because the namelists contain absolute paths | see `EOCENE-BASELINE/BASELINE.txt` |
| `EOCENE-BASELINE/` | frozen reference output: `eocene/` (Eocene workflow) and `domain/` (laptop part of the NEMO domain pipeline), with `BASELINE.txt` (how each was run) (commit, CDO, Python, ecCodes versions) | phase 0 of the plan; do not modify |

Tests that need this data use the `local_data` marker and read its location from
`ECEFAST_TEST_DATA`; they skip when the variable is unset.

## Design principles

These come first; the more specific rules below follow from them.

- **Simplicity.** Prefer the plainest code that does the job: functions and small classes, no
  metaclasses, no clever indirection, no framework where a loop will do. If a reviewer needs
  the author to explain how it works, it is too complicated.
- **Short learning curve.** A new user should be able to run the tool from the README and one
  config file, and a new contributor should be able to add a step by copying an existing one.
  Prefer explicit names over abbreviations, one obvious way to do each thing, and defaults that
  match the standard EC-Earth4 setup. Tutorial notebooks (see below) show the main workflows.
- **Modularity.** Each module has one job and a small public surface. Components are independent
  of each other; shared logic goes down a layer, not sideways. A change to one component should
  not require edits in another.
- **No code repetition.** Before writing a helper, search for an existing one (`core`, `tools`).
  If the same logic appears twice, move it into a shared function in the lowest layer that
  needs it. Copy-paste between components is not allowed; parametrise instead.
- **No speculative generality.** Build what is needed now; do not add options, hooks or
  abstractions "for later". It is easier to add a layer later than to remove one.

## Architecture rules

- **Layers** go one way: `core` → `tools` → `components` → `paleo` → `cli`. A module may only
  import from layers to its left. Enforced by import-linter **(from phase 5)**.
- **Components do not import each other.** If OIFS and NEMO need the same helper, it belongs in
  `core` or `tools`.
- **Steps** are classes that subclass `ComponentStep` **(from phase 4a)** and declare `name`, `needs`,
  `reads`, `writes`, `from_context()` and `run()`. Keep the signatures and logic of `__init__` and
  the `create_*` methods; the step is a thin wrapper. The only change inside `create_*` is writing
  through the atomic-write helper in `core`. A pipeline is an ordered list of step classes. Do not
  introduce decorator- or lambda-based step registration.
- **`reads` and `writes` are the truth.** A step reads only the paths it declares in `reads` and
  writes only the paths in `writes`. No hidden file access inside `create_*`.
- **Bathymetries** are registered by name in the NEMO bathymetry registry; paleo-specific ones
  (e.g. `EoceneBathymetry`) live in `paleo/`, never in `components/nemo`.
- **External tools** (DOMAINcfg, OASIS lib, HPC modules) are reached only through
  `tools.ecearth` and its backends `atos`, `local`, `fake`. No direct `subprocess` calls to
  EC-Earth binaries elsewhere.
- **CDO** is used through the one shared wrapper in `core` **(from phase 3)**. No module-level
  `Cdo()` instances.
- **CLI code only parses arguments** and calls the runner. No science in `cli/`.

## Naming

Keep the current naming scheme; new code follows it.

- Modules and packages: lowercase `snake_case` (`subgrid_orog.py`, `utils_oifs.py`). Anything that
  is imported must be a valid module name; hyphens only in standalone scripts
  (`cli-domain-paleorca.py`).
- Paleo component classes: `Eocene<COMPONENT>` with the component acronym in capitals
  (`EoceneOIFS`, `EoceneNEMO`, `EoceneOASIS`, `EoceneRNFM`), in a module `eocene<COMPONENT>.py`.
- Bathymetry processors: `<Name>Bathymetry`, subclassing `BathymetryProcessor`
  (`PresentDayBathymetry`, `EoceneBathymetry`).
- Component short names in config and CLI: `oifs`, `nemo`, `oasis`, `rnfm`.
- Resolutions and grids as in ECE4-DATA: `TL63L31`, `PALEORCA2`, `ORCA2`.
- Output files keep the file name and relative path they have in the input tree, so EC-Earth
  finds them where it expects them. Variants of the same file add `_<suffix>` before the
  extension (`woa13-levitus-L31_woa-pi.nc`).

## Recipes

### Adding a config key

1. Add the key with its type and default to the config schema **(from phase 3)**. The default
   is the current behaviour, so existing configs keep working.
2. Add it, commented, with its default to the config templates (`*.tmpl`).
3. Document it in `docs/configuration.rst`: name, type, default, meaning, an example.
4. Unit test: default value, and one override.
5. Add a line to `CHANGELOG.rst` under *Added*.

### Adding a step

1. Copy the closest existing step and rename it following [Naming](#naming).
2. Declare `name`, `needs`, `reads`, `writes`; implement `from_context()` and `run()`, with
   `run()` calling the `create_*` methods.
3. Add the class to the right `PIPELINE`, after the steps it `needs`.
4. Unit tests for the new `create_*` methods; integration test for the step (dry run and real run
   with the `fake` backend).
5. Describe it in `docs/workflow.rst` (what it reads, what it writes, why).
6. Add a line to `CHANGELOG.rst`.

### Adding a component

A new folder `components/<name>/` with its steps, following the same recipe. It may import
`core` and `tools` only, never another component. Add it to the import-linter contract and to
the docs.

## Scientific integrity

- **Output must not change by accident.** Every refactor must reproduce the frozen baseline
  (`EOCENE-BASELINE`), checked with `scripts/compare_outputs.py` **(from phase 0)**: same file
  list, NetCDF data variables equal within `rtol=1e-6` with the same names, order, dtypes and
  attributes, GRIB files identical in values, keys and message order (`grib_compare`);
  `history` and date attributes are ignored. A refactor PR that changes numbers is a bug.
- **Output-changing PRs are allowed, but must say so.** The PR description lists which files
  change and why, the change needs explicit approval from a reviewer, and it gets an *Output*
  entry in the changelog. After merge, the baseline is regenerated in a separate commit.
- **Never change scientific choices silently**: constants, remapping methods (`remapbil`,
  `remapcon`, ...), thresholds, masks, vertical levels, file variants. If one must change, ask
  first.
- **Scientific values have a source.** They live in config or in a named constant with a comment
  citing where they come from (paper, dataset, namelist). No magic numbers inline.
- **Hardcoded choices become config options with today's value as default** (e.g.
  `eocene.oifs.aerosols: false`, `eocene.oasis.constant_sst: 290.0`). Do not delete
  disabled code paths such as aerosols; switch them off in config.
- **Vertical grid rule.** The present-day and Eocene PALEORCA2 domains must share the vertical
  grid (`nav_lev`, `e3t_1d`). `EoceneNEMO` reads the present-day domain from the input tree on
  purpose; do not change which domain it reads. The check in `EoceneDomain` / `verify` must fail
  on a mismatch, never warn.
- **CDO.** Use the most recent CDO release available on conda-forge, pinned exactly in
  `environment.yaml`. Follow the grid naming scheme of that version (ECMWF style: `F<N>` regular
  Gaussian, `N<N>` reduced Gaussian, e.g. `F32` for TL63); do not add version checks to support
  old names. Upgrading CDO is its own PR: bump the pin, regenerate the baseline, list the output
  changes in the changelog.

## Data formats: NetCDF and GRIB

When a file is derived from an original EC-Earth file, it must look like the original to
EC-Earth. Preserve, whenever possible:

- **NetCDF:** variable names and order, dimension names and order, dtypes, `_FillValue`, global
  and variable attributes, encoding (compression, chunking). Start from the original dataset and
  replace values; do not rebuild the file from scratch. Append to the global `history`
  attribute, never overwrite it.
- **GRIB:** message order and all metadata (`paramId`, `shortName`, grid definition, level,
  dates, packing type, `bitsPerValue`). Change values with ecCodes on a clone of the original
  message; avoid GRIB → NetCDF → GRIB round trips. If a round trip cannot be avoided, restore the
  metadata and message order afterwards. Existing code that already changes the message order
  (`repack_grib_file` groups GRIB2 before GRIB1) is frozen in the baseline; do not copy that
  pattern into new code.
- When preserving something is not possible, say why in a code comment and in the PR.
- Files created from scratch use CF-style `units`, `long_name` and, where one exists,
  `standard_name`.

## Data safety

- **The input tree is read-only.** Never write, move or delete anything under the configured
  `input` (ECE4-DATA-V3) or `herold` directories. Write only to `output` and `tmpdir`.
- **No data in git.** Never commit `.nc`, `.grb`, `.grib` or other large binaries. Test fixtures
  are generated synthetically at test time, not stored.
- **No hardcoded paths** in code, scripts, namelist templates or tests: no `/home/...`,
  `/lus/...`, `/Users/...` or `hpcperm` paths, no host names. Paths come from config, from
  command-line arguments or from environment variables. Local configs (`eocene/config.yml`) are
  gitignored; committed templates (`*.tmpl`) use placeholder or example paths.
- **No secrets.** Never commit credentials, tokens, passwords, private keys, user names or ssh
  host aliases, in code, configs, notebooks (including cell outputs) or logs.

## Code style

- Python >= 3.11 **(from phase 1)**.
- `ruff` for lint and format, line length 120 **(config from phase 1)**. Run
  `ruff check --fix . && ruff format .` before pushing.
- NumPy-style docstrings on public functions and classes.
- Type hints on every new or changed public signature.
- Match the surrounding code; do not reformat files you are not otherwise changing. The one-off
  repository-wide `ruff format` is a single commit listed in `.git-blame-ignore-revs`.

## Runtime conventions

- **Logging, not printing.** Use the single `ecefast` logger from `core`. No `print()` in library
  code.
- **Fail early with clear errors.** Check inputs before running (preflight). Error messages name
  the step and the missing or bad path. No bare `except`, no silent fallbacks to defaults.
- **Atomic writes.** Every output file is written through the `core` helper **(from phase 4a)**:
  temporary file in the same directory, then rename. Never leave half-written outputs.
  Each run records what it did in `provenance.yml` **(from phase 4b)**.
- **`create_*` methods are pure with respect to files**: they read only declared inputs and either
  return data or write their declared outputs.

## Tests

Test groups (pytest markers **from phase 1**):

| Marker | Data | Where it runs |
|---|---|---|
| `unit` | synthetic, in memory | CI (3.14) |
| `integration` | synthetic tree, `fake` backend; runner, NEMO, OASIS, RNFM, domain pipeline (OIFS: unit tests and `local_data` only) | CI |
| `local_data` | real subset, `ECEFAST_TEST_DATA=<dir>` | your machine, opt-in |
| `hpc` | real data and DOMAINcfg | ECMWF Atos, manual |

- **New or changed function → unit test** on synthetic data.
- **New step in a pipeline → integration test** (dry run and real run with the `fake` backend).
- Run before pushing: `pytest -m "unit or integration"`.
- **Say what you ran.** Coding agents cannot run on ECMWF Atos. Validate with the `fake` backend
  and, when the data is available, `local_data`. The PR description lists which test groups
  ran and which did not; never claim HPC validation that did not happen. HPC runs are done by a
  person.

## Notebooks

Notebooks are the fastest way to learn the tool, so tutorials are part of the deliverable.

- **Tutorials** live in `notebooks/tutorials/`, numbered in reading order: `01_quickstart.ipynb`
  (fetch data, write a config, run the pipeline), then one per component (`02_oifs.ipynb`,
  `03_nemo.ipynb`, ...) showing what each step changes, with a plot before and after.
- Tutorials use only the public API, run top to bottom in a few minutes on the local test data
  or synthetic data, and are linked from `docs/quickstart.rst`.
- A PR that changes an API used by a tutorial updates the tutorial in the same PR.
- **Exploratory and analysis notebooks** live in `notebooks/analysis/`. They may be rough, but
  library code never imports from any notebook: code worth reusing moves into the package, with
  a test.
- Clear outputs before committing (`jupyter nbconvert --clear-output --inplace <file>`), so no
  data, paths or secrets end up in git.

## Documentation

Documentation is written in reStructuredText (`.rst`) and built with Sphinx, so it can be
published on Read the Docs.

- **Location.** User and developer docs live in `docs/` as `.rst` files, with `docs/conf.py` and
  `docs/index.rst` as the entry point. Planning notes (`docs/refactor-plan.md`, issue drafts)
  are working files, not part of the built docs.
- **Planned structure:** `installation.rst`, `quickstart.rst` (fetch data, write a config, run),
  `configuration.rst` (every config key, its default and meaning), `workflow.rst` (pipelines and
  steps, what each reads and writes), `external_tools.rst` (DOMAINcfg, backends, Atos),
  `contributing.rst` (how to add a step or a component; points to this file), `api.rst` and
  `changelog.rst` (includes `CHANGELOG.rst`).
- **API reference is generated from docstrings** (`sphinx.ext.autodoc` + `sphinx.ext.napoleon`
  for NumPy style). Do not duplicate docstring content by hand in `.rst` files.
- **Docs change with the code.** A PR that adds a config key, a step, a CLI option or changes
  user-visible behaviour updates the matching `.rst` page in the same PR.
- **Examples over prose.** Each user page shows a command or a config snippet that works as
  written.
- The docs must build without warnings: `sphinx-build -W -b html docs docs/_build/html`
  **(from phase 1b)**.

## Changelog

`CHANGELOG.rst` at the repo root, format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

- **Every PR adds a line** under *Unreleased*, in one of the sections *Added*, *Changed*,
  *Fixed*, *Removed* or *Output*, ending with the PR number: `- Short description (#17).`
- ***Output*** lists every change to the generated data: which files and why. It must stay empty
  for refactors.
- **Versions** are `0.MINOR.PATCH` while the tool is in development: bump MINOR for new features
  or output changes, PATCH for fixes that do not change output. The version lives in
  `__version__` in the package.
- **Releasing** (a maintainer): rename *Unreleased* to `X.Y.Z (YYYY-MM-DD)`, bump `__version__`,
  merge, tag `vX.Y.Z`, open a new empty *Unreleased* section.

## Dependencies

- **Ask before adding any dependency.** It must be on conda-forge.
- Add it to both `environment.yaml` and `pyproject.toml`.
- Do not bump pinned versions in a non-science PR (CDO: see [Scientific integrity](#scientific-integrity)).

## Git and pull requests

- **Never commit to `main`.** Work on a branch, open a PR against
  `renatacoppo/Eocene-creator` `main`.
- **Every PR to `main` is reviewed by the other author** (Renata or Paolo). No self-merge.
- The PR description says what changed, whether output changes, and which test groups ran.
- File moves use `git mv` so history follows the file.
- One topic per PR.

### During the refactor: the `refactor` branch

- All refactor work goes into the long-lived `refactor` branch; `main` stays frozen until the
  refactor is done. Each task of [docs/refactor-plan.md](docs/refactor-plan.md) (wave table) is
  one branch, created from `origin/refactor`, with one PR **against `refactor`**.
- PRs into `refactor` may be merged by their author once CI is green and
  `scripts/compare_outputs.py` reports 0 differences against `EOCENE-BASELINE` (the PR says so).
  Planned output changes (0.2, 5.3) are the exception: they say which files change, and the
  baseline is regenerated right after the merge.
- The other author reviews the final `refactor` → `main` PR. It is merged with a merge commit
  (no squash, no rebase) so the `git mv` history is kept.
- Bring `main` into `refactor` with `git merge`, never rebase `refactor`.
- Parallel tasks must not touch the same files (see the wave table). While task 2.1 (the `src/`
  move) is open, no other PR into `refactor` is open.

## Out of scope for now

Do not start these without an issue agreed by both authors:

- reworking the WEIGHTS driver (its namelists move as data; only their hardcoded paths become
  placeholders);
- reworking the OIFS generator (moved as-is, constants stay);
- splitting steps more finely than one per component;
- HPC targets other than ECMWF Atos.

## When in doubt, ask

Before changing an area you do not know, read its steps (`reads`, `writes`) and its tests. If the
intent is still unclear, ask instead of guessing. At the end of a task, report what you ran,
what you did not run, and anything you assumed.
