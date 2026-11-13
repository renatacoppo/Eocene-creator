# Eocene Creator CLI

This repository builds EC-Earth4 input data for a time period: the present-day base data of the model grids
(`present`), and Eocene boundary conditions for EC-Earth4 components from an existing input dataset (`eocene`).

The main entry point is:

```bash
ecefast eocene run -c configs/laptop.yml
```

## What the CLI does

`ecefast <period> run` runs the whole pipeline of a period:

- `ecefast eocene run`: copy a filtered subset of the original input tree into a new output directory, install
  the Eocene NEMO domain, then generate the OASIS, OIFS, NEMO and runoff-mapper modifications
- `ecefast present run`: build the OIFS base data of a resolution from a finer one (inputs on ECMWF Atos only)
  and the present-day NEMO domain of the ocean grid (DOMAINcfg on ECMWF Atos only)

`ecefast <component> run [--period present|eocene]` runs only the steps of one component (`oifs`, `nemo`,
`oasis`, `rnfm`) in one period, `present` by default: `ecefast nemo run` builds the present-day NEMO domain.


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
ecefast <period> run -c CONFIG [--steps a,b] [--oifs a,b] [--nemo a,b] [--dry-run] [--overwrite] [-l LEVEL]
ecefast <component> run -c CONFIG [--period present|eocene] [--<component> a,b] [--dry-run] [--overwrite] [-l LEVEL]

<period>          present or eocene (the section of the config file it reads)
<component>       oifs, nemo, oasis or rnfm; --period defaults to present
-c, --config      YAML configuration file (schema 2). Required.
--steps a,b       Comma-separated steps. eocene: stage, domain, oasis, oifs, nemo, rnfm; present: oifs, nemo.
                  Default: all.
--oifs a,b        Run only these steps of <period>.oifs.steps instead of the configured ones.
--nemo a,b        Run only these steps of <period>.nemo.steps instead of the configured ones.
--dry-run         Check all inputs and show the plan; write nothing.
--overwrite       Replace existing outputs, after a warning and a 5 s pause (Ctrl-C to stop).
                  'stage' removes the whole Eocene tree.
-l, --loglevel    Logging level. Default: INFO.

ecefast <period> steps   List the steps: what each needs, reads and writes.
```

Examples:

```bash
ecefast eocene run -c configs/laptop.yml --overwrite           # rebuild everything in an existing output
ecefast eocene run -c configs/laptop.yml --steps oifs -l DEBUG  # rerun one step on an existing output
ecefast eocene run -c configs/laptop.yml --steps oasis,nemo
ecefast nemo run -c configs/laptop.yml                          # present-day NEMO domain (laptop part)
ecefast oasis run -c configs/laptop.yml --period eocene          # the Eocene oasis step only
```

A missing input stops the run before anything is written, with one error listing every missing
file. A successful run writes `provenance.yml` into the output directory of the period (steps, config hash,
git commit, tool versions, times). Details in `docs/workflow.rst`.

## Configuration file

One YAML file per machine (schema 2). Start from `configs/laptop.tmpl` (or `configs/atos.tmpl` on ECMWF Atos).
Sections follow the time periods: `machine` (where: `name: local | atos | fake`, the required `tmpdir` for
intermediate files, and on Atos `atos.ecearth4_sources`), `grids` (the model resolution, shared by every period),
then one section per period, `present` and `eocene`. A period has `input` (the EC-Earth tree it starts from,
read-only), `output` (the tree it makes; every command writes only there and in `<tmpdir>/<period>/<component>/`)
and one subsection per component. Minimal structure for `ecefast eocene run`:

```yaml
schema: 2
machine:
  tmpdir: /path/to/tmp/ecefast          # intermediate files of every command
present:
  input: /path/to/ECE4-DATA-V3              # EC-Earth input tree, read-only
  output: /path/to/OUTPUT/present
eocene:
  input: "{present.input}"                  # the EC-Earth tree the Eocene starts from
  herold: /path/to/herold-et-al-2014/Supp   # Herold paleo datasets, read-only
  output: /path/to/OUTPUT/eocene            # destination tree for copied and generated files
  nemo:
    domain: /path/to/data/domain/PALEORCA2/eocene  # domain_cfg.nc and maskutil.nc of the Eocene domain, or build
    minimum_depth: 30
```

Any string may refer to another value with a `{section.key}` placeholder, e.g. `"{present.input}"`. Optional
keys: `grids.oifs` (`name: TL63L31`, `startdate`, `climate_version`), `grids.nemo` (`name: PALEORCA2`,
`coords_ori`, needed to build a domain), `present.oifs` (the OIFS generator, inputs on Atos only),
`present.nemo` (the present-day NEMO domain, `ecefast nemo run -c <file>`), and in `eocene`:
`oifs.aerosols: false`, `oasis.constant_sst: 290.0`. With `eocene.nemo.domain: build` the `domain` step builds
the Eocene domain itself (Atos only). Every key, and the table of old keys and their new names, is in
`docs/configuration.rst`. Files in an older layout are no longer read: the error lists each old key with its
new name.

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

- installs the Eocene `domain_cfg.nc` and `maskutil.nc` into the output tree (`domain` step), from the
  directory of `eocene.nemo.domain` (e.g. the domain built on Atos); with `eocene.nemo.domain: build` it first
  builds them in `<machine.tmpdir>/eocene/nemo/` with the NEMO domain pipeline (needs `machine.name: atos`, or
  `fake` in tests)
- creates tidal mixing forcing
- creates geothermal heat flux forcing
- creates ocean initial conditions

### RNFM

The runoff workflow:

- reads the Herold runoff slope dataset
- computes drainage basins and arrival points
- writes a new `runoff_maps.nc`