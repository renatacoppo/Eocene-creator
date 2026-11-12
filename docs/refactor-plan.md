# ecefast refactor plan

Working notes for issue [#16](https://github.com/renatacoppo/Eocene-creator/issues/16). The issue is the
version for discussion; this file is the checklist. Rules are in [AGENTS.md](../AGENTS.md).

## Ground rules

- **Output must not change.** Every refactor PR reproduces the baseline from phase 0 (`compare_outputs.py`
  reports 0 differences). Exception, agreed in advance: **phase 5** adds the Eocene subbasins file; it is declared
  under *Output* and the baseline is regenerated after it is merged.
- **One PR per phase** (phases 1 and 4 are split in two), reviewed by the other author. Moves use `git mv`.
- **Freeze** during phase 2: no other PR on `eocene/` or `ecefast/` open at the same time.
- **Out of scope**: WEIGHTS driver (namelists move as data, untouched), OIFS generator rework (moved as-is,
  constants stay), finer-grained steps, HPC targets other than Atos.

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
| `ECE4-DATA-EOCENE/nemo/domain/PALEORCA2/` | Eocene domain built on Atos | rsync from HPC |
| `NEMO-COORDINATES/` (name to confirm) | `PALEORCA2/coords_ori.nc`, `eORCA1/mesh_mask.nc` | copied by hand from the HPC |
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
   `mesh_mask_*.nc` if available. Save as `EOCENE-BASELINE/domain/`.
6. Check `nav_lev` and `e3t_1d` are identical in the present-day and Eocene PALEORCA2 domains.
7. `mv EOCENE-TEST EOCENE-BASELINE`; write `BASELINE.txt` (git commit, CDO, Python, ecCodes versions).
8. `scripts/compare_outputs.py BASELINE NEW`:
   - same file list;
   - NetCDF: every data variable with `np.testing.assert_allclose(rtol=1e-6)`; variable/dimension names, order,
     dtypes and attributes compared too; `history` and date attributes ignored;
   - GRIB: `grib_compare` per file (values, keys and message order), not only `cdo diffn`;
   - exit code 0/1 and a short report. Sanity check: baseline against itself.

Note: `repack_grib_file` already regroups messages (GRIB2 then GRIB1), so the output message order differs from
the original files. That is existing behaviour, frozen in the baseline; the AGENTS.md GRIB rule applies to new code.

## Phase 1a: housekeeping, env, tests, CI (PR)

No behaviour change.

- [ ] `git rm -r --cached` `__pycache__/`, `.ipynb_checkpoints/`; extend `.gitignore` (`EOCENE-*`, `NEMO-COORDINATES/`, `docs/_build/`).
- [ ] Remove `modify_oifs.ipynb`, `modify_nemo.ipynb`; other notebooks to `notebooks/analysis/` with outputs cleared.
- [ ] `get_ece4_data.sh`, `unsorted/add_lonlat.py` to `scripts/`.
- [ ] Placeholder paths in `eocene/config.tmpl`.
- [ ] `environment.yaml`: `python>=3.11`, CDO pinned exactly to the baseline version.
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
- [ ] WEIGHTS namelists → `components/nemo/namelists/`; OIFS generator → `components/oifs/generator.py`, unchanged.
- [ ] Package data in `pyproject.toml` (grids, yaml, j2, namelists). Retire `nemo-workflow.sh`.
- [ ] Entry point `ecefast` dispatching to the existing Eocene and NEMO mains (the old `eocene` entry point stays until 4b).
- [ ] Extend the import smoke test to every module.

Done when: `pip install -e .` works; both baselines match; CI green.

## Phase 3: shared helpers and config (PR)

- [ ] `core/logging.py` (one `ecefast` logger), `core/config.py` (one YAML loader).
- [ ] `core/cdo.py`: one shared `Cdo` instance/accessor; replace the 8 module-level `Cdo()`.
- [ ] `core/grib.py`: merge `utils_oifs.py` and the GRIB half of `eocene/oifs/utils.py` (`unpack/repack_grib_file`,
      `extract_grid_info`); the rest → `paleo/eocene/oifs/fields.py`.
- [ ] `components/nemo/domain/postprocess.py`: one `domain_cfg` + `maskutil` writer (keep `common/util.py`; delete
      `generate-mask-util.py` if the domain baseline matches).
- [ ] Config schema v1 (`schema: 1`; `paths`, `tools`, `grids`, `nemo_domain`, `eocene`) as dataclasses with validation.
      The old `dirs:` format is no longer read; migrate both personal configs. `configs/laptop.tmpl`, `configs/atos.tmpl`.
- [ ] Unit tests: config (good/bad), GRIB helpers on a CDO-made tiny GRIB, postprocess on a tiny synthetic `domain_cfg`.
- [ ] `docs/configuration.rst`.

## Phase 4a: steps, runner, preflight, atomic writes (PR)

- [ ] `core/workspace.py`: roots (`input` read-only, `tmpdir`, `output`), placeholders (`{input}`, `{output}`, `{herold}`, ...),
      guards, `Stage` (today's `run_copy`).
- [ ] `core/steps.py`: `ComponentStep`, `run_pipeline(PIPELINE, ctx, select, dry_run)`: `needs` order, preflight on `reads`, run, check `writes`.
- [ ] `core/io.py`: atomic write helper (write to a temporary file in the same directory, then `os.replace`); every
      `create_*` writes through it. Baseline must match.
- [ ] Wrap `EoceneOIFS`, `EoceneNEMO`, `EoceneOASIS`; new thin `EoceneRNFM` around `run_runoff`; `EoceneDomain`
      (install precomputed domain + vertical grid check).
- [ ] `eocene.oifs.aerosols: false` option.
- [ ] `paleo/eocene/pipeline.py`: `PIPELINE = [Stage, EoceneDomain, EoceneOASIS, EoceneOIFS, EoceneNEMO, EoceneRNFM]`.
- [ ] Tests: runner with dummy steps (order, missing read, dry-run writes nothing, `--steps` subset), atomic helper
      (no partial file on exception), workspace guards.
- [ ] `docs/workflow.rst`.

## Phase 4b: CLI and provenance (PR)

- [ ] `ecefast eocene run -c ... [--steps] [--dry-run] [--overwrite]`.
- [ ] Remove the `eocene` entry point and `cli_eocene.py`.
- [ ] `provenance.yml` per run: steps, config hash, git commit, tool versions, time.
- [ ] Tests: CLI via `main(argv)`.

## Phase 5: external tools and domain pipeline (PR, output change)

- [ ] `tools/ecearth.py`: `AtosBackend` (wraps `run_domain_cfg.sh`, HPC profile from `tools/hpc_profiles.yaml`),
      `LocalBackend` (installs `tools.precomputed.domain`), `FakeBackend` (minimal valid `domain_cfg.nc` + `mesh_mask.nc`).
- [ ] Bathymetry registry; `present_day` and `eocene` registered; the domain pipeline no longer imports `paleo`.
- [ ] `NEMOWorkflow` takes the backend; `EoceneDomain` calls it with `bathymetry="eocene"`.
- [ ] Subbasins for every bathymetry. **Output change**: Eocene subbasins file added. Checked by eye in a notebook,
      listed in the PR and under *Output*; baseline regenerated after merge.
- [ ] `ecefast nemo domain -c ... --bathymetry present_day eocene`.
- [ ] import-linter contract in CI.
- [ ] No hardcoded `/lus`, `/home`, `/ec`, `/Users` paths left outside the OIFS generator (flagged for later).

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
- [ ] `ecefast nemo domain` with `AtosBackend`; compare the new Eocene `domain_cfg.nc` with `ECE4-DATA-EOCENE`.
- [ ] `tests/hpc/test_domaincfg_contract.py`: the real `domain_cfg.nc` has every variable/dimension the fake produces.
- [ ] Full run with `AtosBackend`; compare with the baseline.

## Later

- WEIGHTS driver (`tools.ecearth.weights()`, templated namelists).
- OIFS generator: constants → config, pipeline, tests.
- Finer steps, other HPC profiles, new palaeo periods under `paleo/`.
