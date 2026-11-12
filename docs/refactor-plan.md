# ecefast refactor plan

Design: https://claude.ai/artifact/GHWfP5ho6rG27i4KWTfM9Y (private, share before linking in the issue)

## Ground rules

- **Output must not change.** Every phase ends with the Eocene run producing the same data as the baseline from phase 0. A refactor PR that changes numbers is a bug, not a feature.
- **One PR per phase**, reviewed by Renata. Moves use `git mv` so history follows the files.
- **Freeze**: no parallel feature PRs during phase 2 (the `src/` move touches every import). Agree on the date with Renata.
- **Out of scope** for now: WEIGHTS driver (namelists move as data, untouched), OIFS generator rework (moved as-is, constants stay), finer-grained steps, HPC targets other than Atos.

## Decisions (agreed)

| Topic | Decision |
|---|---|
| Package | single `ecefast`, `src/` layout, `eocene` CLI kept as alias |
| Python | >= 3.11, CI on 3.14 |
| Layers | `core` → `tools` → `components/{oifs,nemo,oasis,rnfm}` → `paleo/eocene` → `cli`, enforced by import-linter; components don't import each other |
| Bathymetry | `EoceneBathymetry` moves to `paleo/eocene`, registered by name in `components.nemo.bathymetry` |
| Steps | option B: existing classes subclass `ComponentStep` (`name`, `needs`, `reads`, `writes`, `from_context()`, `run()`); `__init__` and `create_*` untouched; `PIPELINE` = ordered class list |
| External tools | `tools.ecearth` with backends `atos`, `local` (precomputed domain), `fake` (tests) |
| Herold | each topography file serves its own task; no consolidation |
| Subbasins | built for every bathymetry by the NEMO domain pipeline; Eocene method to verify |

---

## Changes on `main` since the design (PR #15, `woa-pi-init`, 77d8522)

Renata's two commits landed before the refactor starts. The baseline is taken **after** them, so they are part of the reference behaviour. What they change for the plan:

| Change | Consequence for the refactor |
|---|---|
| `create_ocean_init(profile=...)` with `deepmip_cold` / `woa_pi`; CLI hardcodes `woa_pi`; output renamed `woa13-levitus-L31_woa-pi.nc` | Phase 4: `EoceneNEMO.run()` takes the profile from config (`eocene.nemo.ocean_init_profile`, default `woa_pi`), not hardcoded |
| New read: `{input}/nemo/domain/ORCA2/domain_cfg.nc` (present-day mask) | Added to `get_ece4_data.sh` and to `EoceneNEMO.reads` |
| New pure functions `present_day_ocean_mask`, `woa_zonal_mean` | Good first unit tests (phase 3) |
| `eocene_oifs.aerosols()` commented out in `run_oifs` | Off for now, code kept. Phase 4: `EoceneOIFS.run()` calls it only when `eocene.oifs.aerosols: true` (default `false`); the method stays in the class |
| CDO grids `N{gaussian}` → `F{gaussian}` | Output depends on the CDO version: record it with the baseline and pin it in `environment.yaml` (phase 1) |
| WOA no longer opened with dask chunks | none |

### Domain files read by `EoceneNEMO`

`create_ocean_init` opens two domain files, both from the **input (present-day) tree**:

1. `nemo/domain/PALEORCA2/domain_cfg.nc`: only `nav_lev` is used, to relabel the WOA depth axis.
2. `nemo/domain/ORCA2/domain_cfg.nc` (since PR #15): the present-day ocean mask for the `woa_pi` zonal mean. This one is intended.

None of the four NEMO methods use the **Eocene** domain. `run_nemo` only copies it into the output tree.

Read 1 is harmless today. `nav_lev` comes only from the vertical-grid coefficients in `namelist_cfg.j2` (`ppsur`, `ppa0`, `ppa1`, `ppkth`, `ppacr`), which are the same for the present-day and Eocene builds, so the two domains should have identical `nav_lev`. It is still a hidden coupling: if the Eocene domain ever gets another vertical grid (e.g. L75), the ocean init would silently keep present-day depths.

Decision (Paolo): `EoceneNEMO` reads **only the present-day domains**, by design. The present-day and Eocene domains **must share the same vertical grid**. That is a rule of the setup, and the tool should check it, not work around it.

Consequences:
- The refactor keeps both reads exactly as they are, so the output matches the baseline.
- In the pipeline, `nemo` does **not** depend on `domain`. The domain copy becomes its own `EoceneDomain` step.
- Phase 0 confirms the rule holds today: `nav_lev` (and `e3t_1d`) are equal in both domains.
- Phase 4: `EoceneDomain` checks after installing or building the domain that `nav_lev`/`e3t_1d` equal the present-day PALEORCA2 ones, and fails with a clear message otherwise. The `verify` step repeats the check (phase 6).

## Phase 0 — Baseline (tomorrow, morning, no PR)

Goal: a frozen reference output to compare every later phase against, on `main` at `77d8522` or later.

0. Re-run `ECE4_DATA_SRC=<host>:<path>/ECE4-DATA-V3 ./get_ece4_data.sh` (no default source any more) (it now also fetches `nemo/initial/{woa13-levitus-L31,zdfiwm_forcing_r720x360,Goutorbe_ghflux}.nc`, `nemo/domain/ORCA2/domain_cfg.nc`, `oasis/PALEORCA2/`). Without these the NEMO and OASIS steps fail.
1. Create the env: `mamba env create -f environment.yaml` (name `eocene`). Check it resolves on Python 3.11+. Write down the `cdo --version` and `python --version` used.
2. Fetch the Eocene domain:
   `rsync -avhL <host>:<path>/ECE4-DATA-EOCENE/nemo/domain/PALEORCA2/ ECE4-DATA-EOCENE/nemo/domain/PALEORCA2/`
3. `cp eocene/config-local.tmpl eocene/config.yml`, set `domain:` to `.../ECE4-DATA-EOCENE/nemo/domain/PALEORCA2`.
4. Run on the current `main`, unchanged:
   `./eocene/cli_eocene.py -c eocene/config.yml --run all --copy` → output in `EOCENE-TEST/`.
   Note runtime and any failures; a failure here is a pre-existing bug, log it as an issue, do not fix it inside the refactor.
4b. Check `nav_lev` is identical in `ECE4-DATA-V3/nemo/domain/PALEORCA2/domain_cfg.nc` and the Eocene domain (see "Domain files read by `EoceneNEMO`").
5. Freeze it: `mv EOCENE-TEST EOCENE-BASELINE` (gitignored, add the entry). Save `EOCENE-BASELINE/BASELINE.txt` with the git commit, CDO, Python and ecCodes versions.
6. Write `scripts/compare_outputs.py BASELINE NEW`:
   - same file list;
   - NetCDF: `xarray` compare of every data variable (`np.testing.assert_allclose`, rtol 1e-6), ignore `history`/date attrs;
   - GRIB: `cdo diffn` (or `grib_compare`) per file;
   - exit code 0/1 plus a short report.
   Sanity check: compare the baseline against itself.

Done when: baseline exists, compare script passes on baseline-vs-baseline.

## Phase 1 — Housekeeping and test harness (PR 1, tomorrow)

No code moves, no behaviour change.

- [ ] `git rm -r --cached` `__pycache__/`, `.ipynb_checkpoints/`; extend `.gitignore`.
- [ ] Move notebooks to `notebooks/` (`git mv`), `unsorted/add_lonlat.py` and `get_ece4_data.sh` to `scripts/`.
- [ ] `environment.yaml`: `python>=3.11`, pin `cdo` exactly to the version used for the baseline, i.e. the most recent conda-forge release at that time (grid names like `F32` and remapping results depend on it).
- [ ] `pyproject.toml`: `requires-python = ">=3.11"`, fix `hhttps` typo, add `[project.optional-dependencies] dev = [pytest, pytest-cov, ruff, import-linter]`.
- [ ] `pytest` config in `pyproject.toml` with markers `local_data`, `hpc`; default `-m "not local_data and not hpc"`.
- [ ] `tests/test_import.py`: import every current module (smoke test).
- [ ] `tests/local/test_regression.py` (`local_data` marker): runs the Eocene CLI on the real data into a tmp dir and calls `compare_outputs.py` against `EOCENE-BASELINE`. Paths from env `ECEFAST_TEST_DATA`, skip if unset.
- [ ] `.github/workflows/ci.yml`: Python 3.14, micromamba from `environment.yaml` (cached), `ruff check` (lenient rule set to start), `pytest`.
- [ ] Docs skeleton (reStructuredText + Sphinx, ready for Read the Docs): `docs/conf.py` (autodoc, napoleon, viewcode; `exclude_patterns` for the planning `.md` files), `docs/index.rst`, stub pages `installation`, `quickstart`, `configuration`, `workflow`, `external_tools`, `contributing`, `api`; port the README usage into `quickstart.rst`. Add `sphinx` + theme to a `docs` optional-dependency group, `.readthedocs.yaml`, `docs/_build/` to `.gitignore`, and a `sphinx-build -W` job in CI.
- [ ] `AGENTS.md` + `CLAUDE.md` (rules for humans and agents), `CHANGELOG.rst`.
- [ ] Notebooks: tutorials go to `notebooks/tutorials/`, the rest to `notebooks/analysis/`; clear outputs.
- [ ] Open the GitHub issue with the design for Renata (summary, layer diagram, decisions, plan link).

Done when: CI is green on the PR; local regression test passes.

## Phase 2 — `src/` layout and package skeleton (PR 2, freeze)

Pure moves and import fixes. Mapping table: section 7 of the design page.

- [ ] Create `src/ecefast/{core,tools,components/{oifs,nemo,oasis,rnfm},paleo/eocene,cli,diagnostics}` with `__init__.py`.
- [ ] `git mv` every file per the mapping; rename hyphenated scripts (`cli-domain-paleorca.py` → `components/nemo/domain/pipeline.py`, etc.).
- [ ] `EoceneBathymetry` → `paleo/eocene/bathymetry.py` (temporary direct import from the NEMO CLI is acceptable until phase 5).
- [ ] WEIGHTS namelists → `components/nemo/namelists/` unchanged. OIFS generator → `components/oifs/generator.py` unchanged.
- [ ] Package data in `pyproject.toml` (grids, yaml, j2, namelists). Retire `nemo-workflow.sh`.
- [ ] Entry points: `ecefast` (placeholder that dispatches to the old NEMO and Eocene mains) and `eocene` → current `main`.
- [ ] Fix `sys.path` hacks (`run_domain_cfg.sh` imports `config` via `sys.path.insert`) to package imports.

Done when: `pip install -e .` works; `eocene -c ... --run all --copy` matches baseline; CI green.

## Phase 3 — Merge duplicates into `core` (PR 3)

- [ ] `core/logging.py` (merge two loggers), `core/config.py` (merge YAML loaders).
- [ ] `core/grib.py`: merge `utils_oifs.py` and the grib half of `eocene/oifs/utils.py` (`unpack/repack_grib_file`, `extract_grid_info` exist twice); the non-grib half → `paleo/eocene/oifs/fields.py`.
- [ ] `components/nemo/domain/postprocess.py`: one `domain_cfg` + `maskutil` writer (today in `common/util.py` and `generate-mask-util.py`).
- [ ] Config schema v1 (`schema: 1`, sections `paths`, `tools`, `grids`, `nemo_domain`, `eocene`) as dataclasses with validation; reader still accepts the old `dirs:` format with a deprecation warning.
- [ ] `configs/laptop.tmpl`, `configs/atos.tmpl`.
- [ ] Unit tests: config validation (good/bad files), grib helpers on a cdo-generated tiny grib, postprocess on a tiny synthetic `domain_cfg`, `present_day_ocean_mask` and `woa_zonal_mean` (from PR #15) on tiny arrays.

Done when: unit tests green; regression matches baseline.

## Phase 4 — Workspace, ComponentStep, runner, CLI (PR 4)

- [ ] `core/workspace.py`: roots (`input` read-only, `work`, `output`), placeholder table (`{input}`, `{output}`, `{herold}`, `{nemo_grid}`, `{oifs_grid}`, `{nemo_domain}`, …), input/output guards, `stage()` (today's `run_copy`) with `--overwrite`.
- [ ] `core/steps.py`: `ComponentStep` base, `run_pipeline(PIPELINE, ctx, select, dry_run)`: order check of `needs`, preflight on `reads`, run, check `writes`, provenance (`provenance.yml`: step, config hash, git commit, time). Atomic writes helper in `core/netcdf.py`.
- [ ] Wrap classes: `EoceneOIFS`, `EoceneNEMO`, `EoceneOASIS` get `name/needs/reads`, `from_context()`, `run()` (body = today's `run_*`). New thin `EoceneRNFM` wraps `run_runoff`. `Stage` step.
- [ ] Config options replacing the hardcoded choices from PR #15, defaults equal to today's behaviour: `eocene.nemo.ocean_init_profile: woa_pi`, `eocene.oifs.aerosols: false`.
- [ ] `EoceneDomain` checks that the vertical grid (`nav_lev`, `e3t_1d`) of the Eocene domain equals the present-day PALEORCA2 one; on a mismatch it stops with a message naming both files.
- [ ] `EoceneNEMO.reads` lists the input domains it really uses (`{input}/nemo/domain/PALEORCA2/domain_cfg.nc`, `{input}/nemo/domain/ORCA2/domain_cfg.nc`) plus the three `nemo/initial` files. No change of which domain is read.
- [ ] `paleo/eocene/pipeline.py`: `PIPELINE = [Stage, EoceneDomain, EoceneOASIS, EoceneOIFS, EoceneNEMO, EoceneRNFM]` (`EoceneDomain` = install precomputed domain for now).
- [ ] CLI: `ecefast check`, `ecefast eocene run [--steps] [--dry-run] [--overwrite]`, `ecefast eocene steps`; `eocene -r X --copy` mapped onto it.
- [ ] Tests: runner with dummy steps (order, missing read, dry-run writes nothing, `--steps` subset), workspace guards, CLI via `subprocess`/`main(argv)`.

Done when: all of the above tested; regression matches baseline through the new CLI.

## Phase 5 — External tools and the domain pipeline (PR 5)

- [ ] `tools/ecearth.py`: `EcEarthTools` protocol (`domaincfg`, `available`); `AtosBackend` (wraps `run_domain_cfg.sh`, HPC profile and `LD_LIBRARY_PATH` extras from `tools/hpc_profiles.yaml`, nothing hardcoded); `LocalBackend` (installs `tools.precomputed.domain`); `FakeBackend` (writes a minimal valid `domain_cfg.nc` + `mesh_mask.nc` from bathymetry and coords).
- [ ] `components/nemo/bathymetry/registry.py`; `present_day` and `eocene` registered; the domain pipeline no longer imports `paleo`.
- [ ] `components/nemo/domain/pipeline.py`: `NEMOWorkflow` takes the backend; subbasins step runs for every bathymetry (verify the Eocene result by eye in a notebook).
- [ ] `EoceneDomain` step calls the domain pipeline with `bathymetry="eocene"` and the configured backend.
- [ ] `ecefast nemo domain -c ... --bathymetry present_day eocene`.
- [ ] Turn on the import-linter contract in CI.
- [ ] Remove all remaining hardcoded `/lus`, `/home`, `/ec` paths from code (grep must return nothing outside `configs/` and the OIFS generator, which is flagged for later).

Done when: import-linter green; laptop run (local backend) matches baseline.

## Phase 6 — Synthetic integration tests in CI (PR 6)

- [ ] `tests/conftest.py`: fixtures for a synthetic ECE4 tree (tiny NetCDF; TL63 GRIB made with cdo so formats are real) and a synthetic Herold folder.
- [ ] `tests/integration/test_eocene_pipeline.py`: full `ecefast eocene run` with `backend: fake`, then the `verify` checks.
- [ ] `verify` step: file list complete, no NaN in written fields, NEMO mask vs OIFS land-sea mask agree within tolerance.
- [ ] Integration test for `ecefast nemo domain` with the fake backend.
- [ ] Tutorial notebooks on the stable API: `01_quickstart`, then one per component (start from `eocene/oifs/modify_oifs.ipynb` and `eocene/nemo/modify_nemo.ipynb`); link from `docs/quickstart.rst`.

Done when: CI runs end to end in a few minutes.

## Phase 7 — Atos validation (manual)

- [ ] Recreate the env on Atos, `ecefast check -c configs/atos.yml`.
- [ ] `ecefast nemo domain` with `AtosBackend`; compare the new Eocene `domain_cfg.nc` with `ECE4-DATA-EOCENE/nemo/domain/PALEORCA2` (should match).
- [ ] `tests/hpc/test_domaincfg_contract.py`: real `domain_cfg.nc` has every variable/dimension the fake produces.
- [ ] Full `ecefast eocene run` with `AtosBackend`; compare with the baseline.

## Later

- WEIGHTS driver (`tools.ecearth.weights()`, templated namelists).
- OIFS generator: constants → config, pipeline, tests.
- Finer steps (single `create_*`), other HPC profiles, new palaeo periods under `paleo/`.

## Tomorrow, in order

1. Phase 0, steps 1–6 (env, domain fetch, baseline run, compare script).
2. Phase 1 PR.
3. Issue posted: https://github.com/renatacoppo/Eocene-creator/issues/16. No more work is incoming on `eocene/`, so the phase 2 freeze can start as soon as PR 1 is merged.
4. ~~Discuss the remaining design rules~~ Done 2026-11-12: rules written in `AGENTS.md` (+ `CLAUDE.md` importing it). Goes into PR 1; Renata to review the rules there.
