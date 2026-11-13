# Eocene Creator CLI

This repository provides a workflow to prepare Eocene boundary conditions for EC-Earth4 components from an existing input dataset.

The main entry point is:

```bash
ecefast eocene run -c configs/laptop.yml
```

## What the CLI does

The CLI can:

- copy a filtered subset of the original input tree into a new output directory
- generate OASIS modifications
- generate OIFS modifications
- generate NEMO modifications
- generate runoff-mapper products


## Requirements

You need:

- a Python environment with the project dependencies installed
- access to the EC-Earth4 input data tree
- access to the Herold et al. (2013) paleo datasets
- external tools required by the selected workflow, especially `cdo` for several OIFS/NEMO operations

Typical setup:

```bash
conda env create -f environment.yaml
conda activate eocene
pip install -e .
```

## Running the CLI

From the repository root:

```bash
cp configs/laptop.tmpl configs/laptop.yml   # then set the paths; configs/*.yml is gitignored
ecefast eocene run -c configs/laptop.yml --dry-run     # check all inputs, show the plan, write nothing
ecefast eocene run -c configs/laptop.yml               # run every step
```

## Command-line options

```text
ecefast eocene run -c CONFIG [--steps a,b] [--dry-run] [--overwrite] [-l LEVEL]

-c, --config      YAML configuration file (schema 2), section 'eocene'. Required.
--steps a,b       Comma-separated steps: stage, domain, oasis, oifs, nemo, rnfm. Default: all.
--dry-run         Check all inputs and show the plan; write nothing.
--overwrite       Let 'stage' replace an output directory that is not empty.
-l, --loglevel    Logging level. Default: INFO.

ecefast eocene steps   List the steps: what each needs, reads and writes.
```

Examples:

```bash
ecefast eocene run -c configs/laptop.yml --overwrite           # rebuild everything in an existing output
ecefast eocene run -c configs/laptop.yml --steps oifs -l DEBUG  # rerun one step on an existing output
ecefast eocene run -c configs/laptop.yml --steps oasis,nemo
```

A missing input stops the run before anything is written, with one error listing every missing
file. A successful run writes `provenance.yml` into the output directory (steps, config hash,
git commit, tool versions, times). Details in `docs/workflow.rst`.

## Configuration file

One YAML file per machine (schema 2). Start from `configs/laptop.tmpl` (or `configs/atos.tmpl` on ECMWF Atos).
Sections follow the components: `ecefast <component> <command>` reads section `<component>.<command>`
(`ecefast nemo domain` reads `nemo.domain`), `ecefast eocene run` reads `eocene`. Every command writes only to
its own `output_dir`. Minimal structure for `ecefast eocene run`:

```yaml
schema: 2
inputs:                                     # read-only, shared by every command
  ece4_data: /path/to/ECE4-DATA-V3          # EC-Earth input tree
  herold: /path/to/herold-et-al-2014/Supp   # Herold paleo datasets
eocene:
  output_dir: /path/to/OUTPUT/eocene        # destination tree for copied and generated files
  domain:
    from: /path/to/data/domain/PALEORCA2/eocene  # domain_cfg.nc and maskutil.nc of the Eocene bathymetry
```

Any string may refer to another value with a `{section.key}` placeholder, e.g.
`from: "{nemo.domain.output_dir}/nemo/domain/{nemo.grid}/eocene"` (the output of an earlier
`ecefast nemo domain`). Optional sections: `tmpdir`, `machine` (`name: local | atos | fake`), `oifs`
(`grid: TL63L31`), `nemo` (`grid: PALEORCA2`, and `domain`: the NEMO domain pipeline,
`ecefast nemo domain -c <file>`), and in `eocene`: `oifs.aerosols: false`, `oasis.constant_sst: 290.0`.
Every key, and the schema 1 → 2 key table, is in `docs/configuration.rst`. Schema 1 files are no longer read:
the error lists each old key with its new name.

## What `stage` copies

The `stage` step does not clone the full input tree. It copies only the subsets currently used by the workflow:

- `oifs/`: `composition`, `ifsdata`, `vtables`, `rtables` and the OIFS grid (`TL63L31`)
- `nemo/`: `cfc`, `climatology`, `initial`, `weights`
- `oasis/<nemo grid>`
- `cmip6-data` is symlinked, not copied

## Workflow notes

### OASIS

The OASIS workflow:

- modifies the `rstos.nc` so that it can be used with a different land-sea mask

### OIFS

The OIFS workflow:

- prepares Herold-derived land-sea mask, orography, and subgrid orography
- updates climate and initialization files
- writes aerosol climatology products

### NEMO

The NEMO workflow:

- installs the Eocene `domain_cfg.nc` and `maskutil.nc` into the output tree (`domain` step), from
  `eocene.domain.from` (e.g. the domain built on Atos); with `eocene.domain.build: true` it first builds them
  there with the NEMO domain pipeline (needs `machine.name: atos`, or `fake` in tests)
- creates tidal mixing forcing
- creates geothermal heat flux forcing
- creates ocean initial conditions

### RNFM

The runoff workflow:

- reads the Herold runoff slope dataset
- computes drainage basins and arrival points
- writes a new `runoff_maps.nc`