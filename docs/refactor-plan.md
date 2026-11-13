# ecefast refactor plan

Working notes for issue [#16](https://github.com/renatacoppo/Eocene-creator/issues/16). The issue is the
version for discussion; this file is the checklist. Rules are in [AGENTS.md](../AGENTS.md).

## Ground rules

- **Output must not change.** Every refactor PR reproduces the baseline from phase 0 (`compare_outputs.py`
  reports 0 differences). Exception, agreed in advance: **phase 5** adds the Eocene subbasins file; it is declared
  under *Output* and the baseline is regenerated after it is merged.
- **One PR per task** (see the wave table below), into the `refactor` branch. Moves use `git mv`.
- **Freeze** during task 2.1 (the `src/` move): no other PR into `refactor` open at the same time.
- **Out of scope**: WEIGHTS driver (namelists move as data; only their hardcoded paths become placeholders),
  OIFS generator rework (moved as-is, constants stay), finer-grained steps, HPC targets other than Atos.

## Branching

- `refactor` is created from `main` after #18. `main` stays frozen until the refactor is done.
- Each task: a branch from `origin/refactor` (its own worktree when sessions run in parallel), one PR into `refactor`.
- The author merges a PR into `refactor` once CI is green and `compare_outputs.py` reports 0 differences. Planned
  output changes (0.2, 5.3) list the changed files instead, and the baseline is regenerated right after.
- The final `refactor` → `main` PR is reviewed by the other author and merged with a merge commit (no squash).
- `main` → `refactor` with `git merge` if anything lands on `main`; never rebase `refactor`.
- CI (from task 1.2) runs on pull requests to both `main` and `refactor`.

## Tasks and waves

A wave starts when the tasks it depends on are merged into `refactor`. Tasks in the same wave marked ‖ touch
disjoint files and can run in parallel sessions; "serial" tasks touch files that every later task depends on.

| ID | Task | Files | Depends on | Runs |
|---|---|---|---|---|
| 0.1 ✅ | Create `refactor`; AGENTS.md git rules; `data/` in `.gitignore` | AGENTS.md, plan | #18 | serial |
| 0.2 ✅ | Ocean init: `profile=None` builds both files, CLI calls it without arguments (**output change**) | `eoceneNEMO.py`, `cli_eocene.py`, CHANGELOG | 0.1 | ‖ 0.3 |
| 0.3 ✅ | `compare_outputs.py` with a self-test on tiny synthetic files; fetch script gets eORCA1 | `scripts/compare_outputs.py`, `get_ece4_data.sh` | 0.1 | ‖ 0.2 |
| 0.4 ✅ | Fetch all local data (rsync, Eocene domain, `data/`) | local only | 0.3 | Paolo |
| 0.5 ✅ | Env, both baselines, vertical-grid check, `BASELINE.txt` | local only | 0.2, 0.3, 0.4 | serial, with Paolo |
| 1.1 ✅ | Housekeeping: pycache, notebooks, `scripts/`, `config.tmpl` placeholders | notebooks, `unsorted/`, `eocene/config.tmpl` | 0.5 | ‖ 1.2, 1.3 |
| 1.2 ✅ | Env, `pyproject`, pytest markers, first tests, `ci.yml`, local regression test; declare `jinja2` and `shapely` (imported, undeclared); move pip-installed deps (`scipy`, `netcdf4`, `dask`, `cartopy`, ...) to conda | `environment.yaml`, `pyproject.toml`, `tests/`, `.github/workflows/ci.yml` | 0.5 | ‖ 1.1, 1.3 |
| 1.3 ✅ | Docs skeleton, `docs.yml` workflow, `.readthedocs.yaml` | `docs/*.rst`, `docs/conf.py`, `.github/workflows/docs.yml` | 0.5 | ‖ 1.1, 1.2 |
| 1.4 ✅ | ruff config, one format-only commit, `.git-blame-ignore-revs` | everything | 1.1–1.3 | serial |
| 2.1 ✅ | `src/` move, import fixes, broken scripts, package data, `ecefast` entry point; `common/executor.py` runs scripts with `sys.executable`, not `python3` from PATH | everything | 1.4 | serial, freeze |
| 3.0 ✅ | `core/logging`, `core/cdo`; replace 2 loggers and 8 `Cdo()` | imports in many files | 2.1 | serial |
| 3.1 ✅ | Config schema v1, `configs/*.tmpl`, `configuration.rst`, migrate both configs | `core/config.py`, `configs/`, docs | 3.0 | ‖ 3.2, 3.3 |
| 3.2 ✅ | `core/grib.py` merge; Eocene OIFS non-GRIB helpers to `fields.py` | `components/oifs/`, `paleo/eocene/oifs/` | 3.0 | ‖ 3.1, 3.3 |
| 3.3 ✅ | `components/nemo/domain/postprocess.py`; delete `domain/mask_util.py` | `components/nemo/domain/` | 3.0 | ‖ 3.1, 3.2 |
| 4.0 ✅ | `core/steps.py`, `workspace.py`, `io.py` (atomic helper), `Stage`, runner tests | new `core/` files, `tests/` | 3.1 | serial |
| 4.1 ✅ | `EoceneOIFS` step, atomic writes, `aerosols` option; `prepare_herold` writes to `tmpdir`, not into the herold folder | `paleo/eocene/oifs/` | 4.0, 3.2 | ‖ 4.2, 4.3, 5.1 |
| 4.2 ✅ | `EoceneNEMO`, `EoceneDomain` with vertical-grid check | `paleo/eocene/nemo.py`, `domain.py` | 4.0 | ‖ 4.1, 4.3, 5.1 |
| 4.3 ✅ | `EoceneOASIS`, new `EoceneRNFM` | `paleo/eocene/oasis.py`, `rnfm.py` | 4.0 | ‖ 4.1, 4.2, 5.1 |
| 4.4 ✅ | `pipeline.py`, `ecefast eocene run`, provenance, remove `cli/eocene.py`, `workflow.rst` | `cli/`, `paleo/eocene/pipeline.py` | 4.1–4.3 | serial |
| 5.1 ✅ | `tools/ecearth.py` (atos, local, fake), `hpc_profiles.yaml`, `run_domain_cfg.sh` without paths | `tools/` | 3.0 | ‖ wave 4 |
| 5.2 ✅ | Bathymetry registry, backend in the domain pipeline, `ecefast nemo domain`, `EoceneDomain` uses the backend, import-linter | `components/nemo/domain/`, `cli/` | 5.1, 4.4 | serial |
| 5.3 ✅ | Subbasins for every bathymetry, check notebook (**output change**) | subbasins code, `notebooks/analysis/` | 5.2 | ‖ 5.4, 6.2 |
| 5.4 ✅ | Remaining hardcoded paths (WEIGHTS namelists → placeholders), grep check in CI | scattered, `components/nemo/namelists/` | 5.2 | ‖ 5.3, 6.2 |
| 6.1 ✅ | Synthetic fixtures (declared reads only), integration tests, `verify` checks | `tests/integration/`, `paleo/eocene/verify.py` | 5.2 | ‖ 6.3 |
| 6.2 ✅ | OIFS unit tests on small CDO-made GRIB | `tests/unit/oifs/` | 4.1 | ‖ 5.3, 5.4 |
| 6.3 ✅ | Tutorials from `plots.ipynb`, `quickstart.rst` | `notebooks/tutorials/`, docs | 4.4 | ‖ 6.1 |
| 8.1 | Config schema 2: component sections (`oifs:`, `nemo:`, `eocene:`), one `output_dir` per command, `{section.key}` placeholders, explicit `eocene.domain`; homogeneous local folder names (see Phase 8) | `core/config.py`, `core/workspace.py`, every `from_context`, `components/nemo/domain/`, `tools/ecearth.py`, `configs/`, docs, tutorials, tests, `.gitignore` | 6.1–6.3 | serial |
| 8.2 | `ecefast oifs data`: the OIFS generator as a command, its constants in `oifs.data`, output only to `oifs.data.output_dir` | `components/oifs/generator.py`, `cli/`, `configs/`, docs, tests | 8.1 | serial |
| 8.3 | Config by time period: `machine` (with `tmpdir`), `grids`, `present`, `eocene`; `paleo/` → `periods/`; `ecefast <component> run [--period]` and `ecefast <period> run` (see Phase 8) | `core/`, `tools/ecearth.py`, `components/`, `periods/`, `cli/`, `configs/`, docs, tutorials, tests | 8.2 | serial |
| 7.1 | Atos validation (DOMAINcfg contract, full run, OIFS generator vs ECE4-DATA TL63L31) | Atos | 8.3 | Paolo |
| 7.2 | `refactor` → `main`, baseline regenerated, release, issue #16 updated | — | 7.1 | Renata reviews |

```
W0  0.1 ─┬─ 0.2 ──────────────┐
         └─ 0.3 ─ 0.4 (Paolo) ─┴─ 0.5 baseline
W1  1.1 ‖ 1.2 ‖ 1.3  ─→ 1.4 ruff
W2  2.1 src move (freeze)
W3  3.0 ─→ 3.1 ‖ 3.2 ‖ 3.3
W4  4.0 ─→ 4.1 ‖ 4.2 ‖ 4.3 ‖ 5.1  ─→ 4.4
W5  5.2 ─→ 5.3 ‖ 5.4 ‖ 6.2
W6  6.1 ‖ 6.3
W8  8.1 config schema 2 ─→ 8.2 oifs data ─→ 8.3 config by period
W7  7.1 Atos ─→ 7.2 merge to main
```

The phase sections below hold the detailed checklists; task IDs map onto them (0.x = phase 0, 1.1–1.2 and 1.4 =
phase 1a, 1.3 = phase 1b, 4.0–4.3 = phase 4a, 4.4 = phase 4b).

## Decisions (agreed)

| Topic | Decision |
|---|---|
| Package | single `ecefast`, `src/` layout. The old `eocene` command and the old `dirs:` config format are **dropped** in phase 4b; both existing configs are migrated by hand |
| Python | >= 3.11, CI on 3.14 |
| Layers | `core` → `tools` → `components/{oifs,nemo,oasis,rnfm}` → `paleo/eocene` → `cli`, enforced by import-linter; components don't import each other |
| CDO | one shared `Cdo` wrapper in `core` (replaces the module-level `cdo = Cdo()` in 8 files); `tools` is only for EC-Earth binaries (DOMAINcfg) and HPC modules |
| Bathymetry | `EoceneBathymetry` moves to `paleo/eocene`, registered by name in `components.nemo.bathymetry` |
| Steps | existing classes subclass `ComponentStep` (`name`, `needs`, `reads`, `writes`, `from_context()`, `run()`); `__init__` and `create_*` keep their signatures and logic; `PIPELINE` = ordered class list |
| Atomic writes | per file: every `create_*` writes through one `core` helper (temporary file, then rename). This is the only change allowed inside `create_*`, and it must reproduce the baseline |
| Preflight | `--dry-run` runs all input checks and prints the plan; a normal run does the same checks first. No separate `check` command |
| External tools | `tools.ecearth` with backends `atos`, `local` (precomputed domain), `fake` (tests) |
| Herold | each topography file serves its own task; no consolidation |
| Subbasins | built for every bathymetry by the NEMO domain pipeline, from phase 5 (output change, see above); Eocene method checked by eye in a notebook before merge |
| Ocean init | `create_ocean_init()` with no arguments builds both `woa-pi` and `deepmip-30` (phase 0a); no config option |
| Aerosols | off by default (`eocene.oifs.aerosols: false`), code kept |
| CI integration tests | runner + NEMO, OASIS, RNFM, domain pipeline on synthetic data with the `fake` backend. OIFS is covered by unit tests and by the `local_data` regression, not by a synthetic end-to-end test |
| Formatting | `ruff format` on the whole repo in one format-only commit in PR 1a, listed in `.git-blame-ignore-revs` |
| Notebooks | `plots.ipynb` replaces `modify_oifs.ipynb` and `modify_nemo.ipynb`; tutorials start from it |

## Domain files read by `EoceneNEMO`

`create_ocean_init` opens two **present-day** domains from the input tree:

1. `nemo/domain/PALEORCA2/domain_cfg.nc`: only `nav_lev`, to relabel the WOA depth axis.
2. `nemo/domain/ORCA2/domain_cfg.nc` (PR #15): the present-day ocean mask for the `woa-pi` zonal mean.

Both reads stay. The rule they rely on: **the present-day and Eocene PALEORCA2 domains share the vertical grid**
(`nav_lev`, `e3t_1d`). Phase 0b checks it holds today; phase 4a makes `EoceneDomain` fail on a mismatch; the
`verify` checks in phase 6 repeat it. In the pipeline, `nemo` does not depend on `domain`.

## Phase 0a: both ocean initial files (PR, output change)

- [ ] `create_ocean_init(profile=None, ...)`: `None` builds both profiles; `"woa_pi"` or `"deepmip_cold"` builds one.
- [ ] `cli_eocene.py` calls `create_ocean_init()` without arguments.
- [ ] Unit test is not possible yet (no pytest until 1a); the PR shows `ncdump -h` of both files.
- [ ] `CHANGELOG.rst` *Output*: new file `nemo/initial/woa13-levitus-L31_deepmip-30.nc`.

## Phase 0b: baseline (no PR, after 0a is merged)

Local data needed (all gitignored, see AGENTS.md):

| Directory | Contents | Source |
|---|---|---|
| `ECE4-DATA-V3/` | Eocene workflow inputs, plus `nemo/domain/eORCA1/domain_cfg.nc` (present-day bathymetry source) | `get_ece4_data.sh`, extended with the eORCA1 domain |
| `data/` | `PALEORCA2/coords_ori.nc`, `eORCA1/mesh_mask.nc` (plus outputs of earlier runs) | copied by hand from the HPC |
| `herold-et-al-2014/` | Herold et al. (2014) supplement | HPC or paper |

Steps:

1. Extend `get_ece4_data.sh` with `/nemo/domain/eORCA1/domain_cfg.nc` and re-run it. Today the local tree lacks
   `oasis/`, `nemo/initial/` and `nemo/domain/ORCA2`.
2. Create the env (`mamba env create -f environment.yaml`); check it resolves on Python 3.14 with `esmpy`/`xesmf`.
   Write down CDO, Python and ecCodes versions.
3. Fetch the Eocene domain and the coordinates folder.
4. **Eocene baseline**: `./eocene/cli_eocene.py -c eocene/config.yml --run all --copy` on `main`, unchanged.
   A failure here is a pre-existing bug: open an issue, do not fix it in the refactor.
5. **Domain baseline** (laptop part of the NEMO domain pipeline, no DOMAINcfg): run `cli-domain-paleorca.py` up to
   the namelist step for `present_day` and `eocene` (bathymetry, coordinates, namelists), plus the
   post-processing (`process_domain_cfg`, `extract_maskutil`) on the Atos-built `domain_cfg_*.nc` /
   `mesh_mask_*.nc` if available. Save as `EOCENE-BASELINE/domain/`. Done: DOMAINcfg output is not on the laptop, so the baseline covers coordinates, bathymetry and namelists; the post-processing is covered by unit tests in 3.3.
6. Check `nav_lev` and `e3t_1d` are identical in the present-day and Eocene PALEORCA2 domains.
7. `mv EOCENE-TEST EOCENE-BASELINE/eocene`; write `BASELINE.txt` (git commit, CDO, Python, ecCodes versions).
8. `scripts/compare_outputs.py BASELINE NEW`:
   - same file list;
   - NetCDF: every data variable with `np.testing.assert_allclose(rtol=1e-6)`; variable/dimension names, order,
     dtypes and attributes compared too; `history` and date attributes ignored;
   - GRIB: `grib_compare` per file (values, keys and message order), not only `cdo diffn`;
   - exit code 0/1 and a short report. Sanity check: baseline against itself.

Note: `repack_grib_file` already regroups messages (all GRIB1, then all GRIB2), so the output message order differs from
the original files. That is existing behaviour, frozen in the baseline; the AGENTS.md GRIB rule applies to new code.

## Phase 1a: housekeeping, env, tests, CI (PR)

No behaviour change.

- [ ] `git rm -r --cached` `__pycache__/`, `.ipynb_checkpoints/`; extend `.gitignore` (`docs/_build/`; `data/` is already ignored by 0.1).
- [ ] Remove `modify_oifs.ipynb`, `modify_nemo.ipynb`; other notebooks to `notebooks/analysis/` with outputs cleared.
- [ ] `get_ece4_data.sh`, `unsorted/add_lonlat.py` to `scripts/`.
- [ ] Placeholder paths in `eocene/config.tmpl`.
- [ ] `environment.yaml`: `python>=3.11`; CDO not pinned and not in the env (Homebrew on macOS, conda-forge in CI);
      the regression test skips unless `cdo` matches the version in `BASELINE.txt`.
- [ ] `pyproject.toml`: `requires-python = ">=3.11"`, fix the `hhttps` typo, `dev` extras (pytest, pytest-cov, ruff, import-linter).
- [ ] pytest config with markers `unit`, `integration`, `local_data`, `hpc`.
- [ ] `tests/test_import.py`: import every module of the `eocene` package. `ecefast/` is not a package yet
      (flat imports, hyphenated scripts) and is covered from phase 2.
- [ ] First unit tests: `present_day_ocean_mask`, `woa_zonal_mean`.
- [ ] `tests/local/test_regression.py` (`local_data`): runs the workflow and `compare_outputs.py`.
- [ ] ruff config (line length 120, lenient rule set), then **one format-only commit** listed in `.git-blame-ignore-revs`.
- [ ] `.github/workflows/ci.yml`: Python 3.14, micromamba from `environment.yaml` (cached), `ruff check`, `pytest -m "unit or integration"`.

Done when: CI green; local regression passes.

## Phase 1b: documentation skeleton (PR)

- [ ] `docs/conf.py` (autodoc, napoleon, viewcode; exclude the planning `.md` files), `docs/index.rst`, stub pages
      `installation`, `quickstart` (port the README usage), `configuration`, `workflow`, `external_tools`, `contributing`, `api`, `changelog`.
- [ ] `docs` extras (sphinx + theme), `.readthedocs.yaml`, `sphinx-build -W` job in CI.

## Phase 2: `src/` layout (PR, freeze)

Pure moves and import fixes.

- [ ] `src/ecefast/{core,tools,components/{oifs,nemo,oasis,rnfm},paleo/eocene,cli}` with `__init__.py`.
- [ ] `git mv` every file; hyphenated scripts get module names (`cli-domain-paleorca.py` → `components/nemo/domain/pipeline.py`, ...).
- [ ] Fix the flat imports (`from utils import ...`, `from common...`, `sys.path` in `run_domain_cfg.sh`). `descriptor_generator.py`
      and `oifs_create_corners.py` import a `utils` module that does not exist in `ecefast/oifs/`: point them to `utils_oifs`,
      no logic change.
- [ ] `EoceneBathymetry` → `paleo/eocene/bathymetry.py` (temporary direct import from the NEMO pipeline until phase 5).
- [ ] WEIGHTS namelists → `components/nemo/namelists/` (paths become placeholders in 5.4); OIFS generator → `components/oifs/generator.py`, unchanged.
- [ ] Package data in `pyproject.toml` (grids, yaml, j2, namelists). Retire `nemo-workflow.sh`.
- [ ] Entry point `ecefast` dispatching to the existing Eocene and NEMO mains (the old `eocene` entry point stays until 4b).
- [ ] Extend the import smoke test to every module.

Done when: `pip install -e .` works; both baselines match; CI green.

## Phase 3: shared helpers and config (PR)

- [x] `core/logger.py` (one `ecefast` logger) (task 3.0).
- [ ] `core/config.py` (one YAML loader).
- [x] `core/cdo.py`: one shared `Cdo` instance/accessor; replace the module-level `Cdo()` (task 3.0).
- [ ] `core/grib.py`: merge `utils_oifs.py` and the GRIB half of `paleo/eocene/oifs/utils.py` (`unpack/repack_grib_file`,
      `extract_grid_info`); the rest → `paleo/eocene/oifs/fields.py`.
- [ ] `components/nemo/domain/postprocess.py`: one `domain_cfg` + `maskutil` writer (keep `common/util.py`; delete
      `domain/mask_util.py` if the domain baseline matches).
- [ ] Config schema v1 (`schema: 1`; `paths`, `tools`, `grids`, `nemo_domain`, `eocene`) as dataclasses with validation.
      The old `dirs:` format is no longer read; migrate both personal configs. `configs/laptop.tmpl`, `configs/atos.tmpl`.
- [ ] Unit tests: config (good/bad), GRIB helpers on a CDO-made tiny GRIB, postprocess on a tiny synthetic `domain_cfg`.
- [ ] `docs/configuration.rst`.

## Phase 4a: steps, runner, preflight, atomic writes (PR)

- [x] `core/workspace.py`: roots (`input` read-only, `tmpdir`, `output`), placeholders (`{input}`, `{output}`, `{herold}`, ...),
      guards, `Stage` (today's `run_copy`).
- [x] `core/steps.py`: `ComponentStep`, `run_pipeline(PIPELINE, ctx, select, dry_run)`: `needs` order, preflight on `reads`, run, check `writes`.
- [ ] `core/io.py`: atomic write helper (write to a temporary file in the same directory, then `os.replace`); every
      `create_*` writes through it. Baseline must match.
- [ ] Wrap `EoceneOIFS`, `EoceneNEMO`, `EoceneOASIS`; new thin `EoceneRNFM` around `run_runoff`; `EoceneDomain`
      (install precomputed domain + vertical grid check).
- [ ] `eocene.oifs.aerosols: false` option.
- [x] `paleo/eocene/pipeline.py`: `PIPELINE = [Stage, EoceneDomain, EoceneOASIS, EoceneOIFS, EoceneNEMO, EoceneRNFM]`.
- [ ] Tests: runner with dummy steps (order, missing read, dry-run writes nothing, `--steps` subset), atomic helper
      (no partial file on exception), workspace guards.
- [x] `docs/workflow.rst`.

## Phase 4b: CLI and provenance (PR)

- [x] `ecefast eocene run -c ... [--steps] [--dry-run] [--overwrite]`.
- [x] Remove the `eocene` entry point and `cli/eocene.py`.
- [x] `provenance.yml` per run: steps, config hash, git commit, tool versions, time.
- [x] Tests: CLI via `main(argv)`.

## Phase 5: external tools and domain pipeline (PR, output change)

- [x] `tools/ecearth.py`: `AtosBackend` (wraps `run_domain_cfg.sh`, HPC profile from `tools/hpc_profiles.yaml`),
      `LocalBackend` (installs `tools.precomputed.domain`), `FakeBackend` (minimal valid `domain_cfg.nc` + `mesh_mask.nc`).
- [x] Bathymetry registry; `present_day` and `eocene` registered; the domain pipeline no longer imports `paleo`.
- [x] `NEMOWorkflow` takes the backend; `EoceneDomain` calls it with `bathymetry="eocene"`.
- [ ] Subbasins for every bathymetry. **Output change**: Eocene subbasins file added. Checked by eye in a notebook,
      listed in the PR and under *Output*; baseline regenerated after merge.
- [x] `ecefast nemo domain -c ... --bathymetry present_day eocene`.
- [x] import-linter contract in CI.
- [ ] No hardcoded `/lus`, `/home`, `/ec`, `/Users` paths left outside the OIFS generator (flagged for later); WEIGHTS namelists get placeholders, nothing else changes in them.

## Phase 6: CI integration tests and tutorials (PR)

- [ ] `tests/conftest.py`: synthetic ECE4 tree and Herold folder for NEMO, OASIS, RNFM and the domain pipeline.
      The fixture contains **only** the files declared in `reads`, so an undeclared read fails the test.
- [ ] `tests/integration/`: pipeline with `--steps domain,oasis,nemo,rnfm` and the `fake` backend; `ecefast nemo domain` with `fake`.
- [ ] `verify` checks: file list complete, no NaN in written fields, vertical grid rule.
- [ ] OIFS: unit tests on the `create_*` helpers with small CDO-made GRIB; end-to-end only via `local_data`.
- [ ] Tutorials in `notebooks/tutorials/` (`01_quickstart`, then one per component, starting from `plots.ipynb`), linked from `docs/quickstart.rst`.

Done when: CI runs end to end in a few minutes.

## Phase 7: Atos validation (manual, by a person)

- [ ] Recreate the env on Atos; `ecefast eocene run --dry-run -c configs/atos.yml`.
- [ ] `ecefast nemo domain` with `AtosBackend`; compare the new Eocene `domain_cfg.nc` with `data/domain/PALEORCA2/eocene/`.
- [ ] `tests/hpc/test_domaincfg_contract.py`: the real `domain_cfg.nc` has every variable/dimension the fake produces.
- [ ] Full run with `AtosBackend`; compare with the baseline.

## Phase 8: untangle the configuration, OIFS data command (PRs, no output change)

Why: `paths.output` (the Eocene tree) and `nemo_domain.output_dir` (the domain work folder) are easy to
confuse; `tools.backend` silently decides whether the `domain` step copies or builds the Eocene domain;
`grids.nemo` and `nemo_domain.grids.target` say the same thing twice; `nemo_domain.domaincfg_dir` is an Atos
path far from the rest; local folders are named three ways (`EOCENE-TEST`, `EOCENE-DOMAIN-TEST`,
`EOCENE-BASELINE/{eocene,domain}`); and the OIFS generator that made the TL63L31 base data cannot be run from
`ecefast` (hardcoded Atos paths, writes into the ECE4-DATA tree).

Decisions (Paolo, 2026-11-12):

- Config sections follow the components: `oifs:`, `nemo:` (and later `oasis:`, `rnfm:`) hold what is specific
  to that component, including its commands (`nemo.domain`, `oifs.data`); paleo runs have their own section
  (`eocene:`). Settings that belong to a component move there (`grids.nemo` → `nemo.grid`, DOMAINcfg dir →
  `nemo.domain.tools_dir`).
- **One rule for commands and sections:** `ecefast <component> <command>` reads section `<component>.<command>`
  (`ecefast nemo domain` → `nemo.domain`, `ecefast oifs data` → `oifs.data`); `ecefast eocene run` reads
  `eocene`.
- **Every command writes only to its own `output_dir`**, the same key name everywhere. A run combines the
  output of earlier runs by referring to it: any path may use `{section.key}` placeholders, e.g.
  `{nemo.domain.output_dir}`. One placeholder syntax for configs and for the steps' `reads`/`writes`.
- Final products are laid out as in ECE4-DATA inside each `output_dir` (`oifs/<grid>/...`,
  `nemo/domain/<grid>/<name>/...`), so a later run finds them where an EC-Earth tree has them; intermediate
  files of a command go to `<output_dir>/work/`.
- Local folders homogeneous: `OUTPUT/<command>` for runs and `BASELINE/<command>` for the frozen reference,
  with `<command>` = `eocene`, `nemo-domain`, `oifs-data`.
- The `domain` step can still build the Eocene domain (nested), but the config says so explicitly.
- Before the Atos validation, so Atos validates the final structure and users migrate their configs once.

### 8.1 Config schema 2

```yaml
schema: 2

inputs:                           # read-only, shared                    (was paths.input, paths.herold)
  ece4_data: /path/to/ECE4-DATA-V3
  herold: /path/to/herold-et-al-2014/Supp
tmpdir: null                      # scratch for every command            (was paths.tmpdir)

machine:                          # where EC-Earth tools run             (was tools)
  name: local                     # local | atos | fake                  (was tools.backend)
  atos: {profile: atos, oasis_lib_dir: /path/to/oasis3-mct-5.2/arch_ecearth/lib}

oifs:
  grid: TL63L31                   #                                      (was grids.oifs)
  data: {...}                     # ecefast oifs data, task 8.2

nemo:
  grid: PALEORCA2                 #                       (was grids.nemo and nemo_domain.grids.target)
  domain:                         # ecefast nemo domain                  (was nemo_domain)
    output_dir: /path/to/OUTPUT/nemo-domain   # nemo/domain/<grid>/<name>/ + work/  (was output_dir)
    tools_dir: /path/to/nemo-4.2/tools        # NEMO tools with DOMAINcfg/, Atos  (was domaincfg_dir)
    coords_ori: /path/to/data/PALEORCA2/coords_ori.nc
    source_grid: eORCA1           # grid of the present_day bathymetry   (was grids.source)
    staggering: {source: T, target: T}        #                          (was grids.staggering_*)
    minimum_depth: 30             #                                      (was parameters.minimum_depth)
    steps: {...}
    bathymetries:
      - name: eocene
        processor: EoceneBathymetry
        source_file: "{inputs.herold}/herold_etal_stddev_subgrid_etopo1_to_eocene_1x1.nc"

eocene:                           # ecefast eocene run
  output_dir: /path/to/OUTPUT/eocene          # the Eocene tree        (was paths.output)
  domain:                         # Eocene NEMO domain to install   (was tools.precomputed.domain + backend)
    from: "{nemo.domain.output_dir}/nemo/domain/{nemo.grid}/eocene"   # output of an earlier `nemo domain`
    build: false                  # true: run nemo.domain (eocene bathymetry) first; needs machine atos/fake
  oifs: {aerosols: false}
  oasis: {constant_sst: 290.0}
```

On a laptop `eocene.domain.from` points at the domain copied from Atos (`data/domain/PALEORCA2/eocene`); on
Atos it points at `{nemo.domain.output_dir}/...`, built by `ecefast nemo domain` or with `build: true`.

- [x] `core/config.py`: schema 2 dataclasses; `{section.key}` placeholders resolved from the config (unknown
      key, or a cycle, is an error); a schema 1 file fails with one error listing each old key and its new
      name (no automatic migration, no support for both).
- [x] Step `reads`/`writes` use the same placeholders (`{inputs.ece4_data}/nemo/...`,
      `{eocene.output_dir}/...`, `{nemo.grid}`).
- [x] `EoceneDomain.from_context` reads `eocene.domain`, not the backend name; `build: true` with
      `machine.name: local` is a config error.
- [x] NEMO domain pipeline: final files under `<output_dir>/nemo/domain/<grid>/<name>/`, intermediates
      (coordinates, bathymetries, namelists) under `<output_dir>/work/`. Same file contents; the baseline
      layout moves with it.
- [x] Local folders: `OUTPUT/{eocene,nemo-domain}`, `BASELINE/{eocene,nemo-domain}` (moved from
      `EOCENE-TEST`, `EOCENE-DOMAIN-TEST`, `EOCENE-BASELINE`); `.gitignore`, `compare_outputs.py`,
      `test_regression.py`, AGENTS.md. The domain baseline is regenerated (its namelists hold absolute paths).
- [x] Templates `configs/laptop.tmpl`, `configs/atos.tmpl`; `docs/configuration.rst` (new layout, old → new
      table); `overview.rst` gets a "commands, sections and outputs" diagram; quickstart, workflow, external
      tools, tutorials, AGENTS.md commands.
- [x] Tests: schema, placeholders, schema 1 error; fixtures in `tests/synthetic.py`; all groups.
- Done when: both baselines give 0 differences (apart from moved paths), and `ecefast eocene run` and
  `ecefast nemo domain` run with the migrated `configs/laptop.yml`.

### 8.2 `ecefast oifs data`

The generator (`components/oifs/generator.py`, moved unchanged) makes the present-day OIFS base data of a
resolution (e.g. TL63L31 from TL255L91: spectral and gridpoint initial state, optional climate files, vertical
interpolation). Today it is a script with hardcoded Atos paths that writes into the ECE4-DATA tree.

```yaml
oifs:
  grid: TL63L31                   # target resolution
  data:                           # ecefast oifs data (inputs exist on Atos only)
    output_dir: /path/to/OUTPUT/oifs-data     # writes oifs/<grid>/<startdate>/, oifs/<grid>/<climate>/
    source_grid: TL255L91         # read from {inputs.ece4_data}/oifs/<source_grid>/<startdate>
    startdate: '19900101'
    climate_dir: /path/to/climate.v020        # was OIFS_BC['compute']; needed only with steps.boundary
    vertical_grids_dir: /path/to/oifs-grids   # was GRIDS (made by create_corners.py)
    steps: {spectral: true, gridpoint: true, boundary: false}
```

- [x] Module-level constants become `oifs.data`, with today's values as defaults where they are not paths;
      the generation logic does not change.
- [x] Writes only under `oifs.data.output_dir` (never `inputs.ece4_data`), through `atomic_write`; temporary
      files in `<output_dir>/work/` or `tmpdir`; logging, not `print`; preflight of every input with one error.
- [x] `ecefast oifs data -c CONFIG [--dry-run]` in `cli/`; `docs/workflow.rst` section; `overview.rst`.
- [x] Unit tests where synthetic GRIB allows; `tests/hpc`: generate TL63L31 on Atos and compare with
      `{inputs.ece4_data}/oifs/TL63L31` with `scripts/compare_outputs.py`.
- [x] AGENTS.md "Out of scope": drop "reworking the OIFS generator" (needs Renata's agreement).
- Not in scope: `create_corners.py`, `descriptor_generator.py`, `convert_aka_bika.py` stay scripts (documented
  as the tools that make `vertical_grids_dir` and the grid descriptions). Making `eocene` read its OIFS base
  from `{oifs.data.output_dir}` instead of ECE4-DATA is possible with the same placeholders but not planned.

### 8.3 Configuration by time period

Why (Paolo, 2026-11-13): the schema 2 of 8.1 still mixes the time periods. `inputs.herold` is required by every
command although only the Eocene steps read it; `nemo.domain` holds both the grid tooling and the period choice
(the `bathymetries` list with its `eocene` entry); `source_grid` and `staggering.source` belong to the present-day
bathymetry only; the EC-Earth4 source tree is given twice (`machine.atos.oasis_lib_dir`, `nemo.domain.tools_dir`);
`EoceneOIFS` and `EoceneNEMO` hardcode `19900101`, `climate.v020` and `PALEORCA2`. This replaces the 8.1
decision "sections follow the components": sections follow the **time periods**, and the components are
subsections of each period.

Decisions (Paolo, 2026-11-13):

- **Two axes.** A component (`components/`) is *how*: tools that know nothing about a period (the domain
  pipeline for one bathymetry, the OIFS generator). A period (`periods/`) is *what*: its datasets, its choices,
  its output tree. Every paleo period starts from an EC-Earth tree (`input`), usually the present-day one.
- **Sections:** `machine` (where: backend, `tmpdir`, Atos options), `grids` (the model resolution, shared by
  every period), one section per period: `present`, `eocene`. Each period has `input` (the EC-Earth tree it
  starts from, read-only), `output` (the tree it makes) and one subsection per component. Datasets of a period
  have their own key (`eocene.herold`), never `input`.
- **`machine.tmpdir`** (required): intermediate files of every command, in `<tmpdir>/<period>/<component>/`, kept
  between runs. No `work/` inside an output tree. Must not lie inside an `input`, `herold` or `output`.
- **`machine.atos.ecearth4_sources`** replaces `oasis_lib_dir` and `tools_dir`; the subfolders
  (`oasis3-mct-5.2/arch_ecearth/lib`, `nemo-4.2/tools`) are constants of the atos backend.
- **`grids.oifs`**: `name`, `startdate`, `climate_version` (used by the generator and by `EoceneOIFS`).
  **`grids.nemo`**: `name`, `coords_ori`, `staggering` (target grid).
- **Bathymetries are not configured:** each period's pipeline uses its own processor class
  (`PresentDayBathymetry`, `EoceneBathymetry`), which declares its source files; the name registry
  (`PROCESSORS`, `EOCENE_PROCESSORS`) goes. Only `present.nemo.source_grid` (default `eORCA1`) and
  `source_staggering` stay visible, because the source of the present-day bathymetry matters; its file is
  `{input}/nemo/domain/<source_grid>/domain_cfg.nc`. The strait corrections are looked up by source grid,
  target grid and remap method; a source grid without corrections is a config error.
- **`minimum_depth`** per period (`present.nemo`, `eocene.nemo`).
- **Mask comparison plot** always on: one panel per `{input}/nemo/domain/*/domain_cfg.nc` found, plus the new
  domain.
- **`eocene.nemo.domain`**: `build` (run the domain pipeline with the Eocene bathymetry; not with
  `machine.name: local`) or a directory holding `domain_cfg.nc` and `maskutil.nc`. Replaces `from` + `build`.
- **`eocene.input`** is written explicitly in the templates: `"{present.input}"`.
- **Steps:** `steps:` stays in the config (`present.oifs.steps`, `present.nemo.steps`, `eocene.nemo.steps`); the
  command line overrides them for one run with `--oifs a,b` and `--nemo c,d`. `--steps` selects pipeline steps.
- **CLI:** `ecefast <component> run -c CONFIG [--period present|eocene]` (default `present`) runs that
  component's steps of one period; `ecefast <period> run -c CONFIG [--steps ...]` runs the whole period. Each step
  declares its `component`. Replaces `ecefast oifs data`, `ecefast nemo domain` and `--bathymetry`.
- **Overwrite:** `--overwrite` on every run. `stage` refuses a non-empty Eocene tree without it; a present-day
  run refuses final files that already exist without it. With it, the command logs what it replaces and waits
  5 s (Ctrl-C to stop), then replaces it. No other protection.
- **Placeholders in step templates:** `{input}`, `{output}`, `{herold}` are keys of the running period;
  dotted names (`{grids.nemo.name}`, `{present.input}`) are keys of the file. The config file itself uses
  dotted names only.
- **Code:** `paleo/` → `periods/eocene/`, new `periods/present/` (with `PresentDayBathymetry`); layers
  `core` → `tools` → `components` → `periods` → `cli`.
- Stays `schema: 2` (not released). One PR. Local folders: `OUTPUT/{present,eocene}`,
  `BASELINE/{present,eocene}`; the domain baseline is regenerated (its intermediate files move to `tmpdir`).

```yaml
schema: 2

machine:
  name: atos                      # local | atos | fake
  tmpdir: /path/to/tmp/ecefast
  atos:
    profile: atos
    ecearth4_sources: /path/to/ecearth4/sources

grids:
  oifs: {name: TL63L31, startdate: '19900101', climate_version: climate.v020}
  nemo: {name: PALEORCA2, coords_ori: /path/to/coords_ori.nc, staggering: T}

present:
  input: /path/to/ECE4-DATA-V3
  output: /path/to/OUTPUT/present
  oifs: {source_grid: TL255L91, climate_dir: ..., precomputed_climate_dir: ..., vertical_grids_dir: ..., steps: {...}}
  nemo: {source_grid: eORCA1, minimum_depth: 30, steps: {...}}

eocene:
  input: "{present.input}"
  herold: /path/to/herold-et-al-2014/Supp
  output: /path/to/OUTPUT/eocene
  nemo: {domain: build, minimum_depth: 30, steps: {...}}
  oifs: {aerosols: false}
  oasis: {constant_sst: 290.0}
```

- [ ] `core/config.py`: the layout above; `core/workspace.py`: `Context` knows the running period.
- [ ] `tools/ecearth.py`: `ecearth4_sources`, namelist folder from the backend.
- [ ] Domain pipeline for one bathymetry; intermediates to `tmpdir`; final files to the given folder.
- [ ] `periods/present` (oifs, nemo steps), `periods/eocene` (moved); grid names and dates from `grids`.
- [ ] CLI, overwrite pause; templates, docs, tutorials, AGENTS.md, CHANGELOG; tests.
- Done when: `pytest -m "unit or integration"` and `local_data` pass, the Eocene output gives 0 differences
  against the baseline, and the domain intermediates are equal to the baseline ones (same files, moved).

### Open points

- Renata agrees to wire in the OIFS generator: agreed (task 8.2).
- Whether the generator output matches `ECE4-DATA-V3/oifs/TL63L31` can only be checked on Atos (7.1).

## Later

- WEIGHTS driver (`tools.ecearth.weights()`, templated namelists).
- OIFS generator: constants → config, pipeline, tests.
- Finer steps, other HPC profiles, new palaeo periods under `periods/`.
- Dead code to remove or fix: `vegetation.prepare_vegetation` (undefined `NC4`), `EoceneOIFS.create_sic`/`create_sst`
  (undefined `idir_amip`), `fields.modify_grib` (unused) (found in #25, #34).
