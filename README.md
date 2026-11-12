# Eocene Creator CLI

This repository provides a workflow to prepare Eocene boundary conditions for EC-Earth4 components from an existing input dataset.

The main entry point is:

```bash
ecefast eocene ...
```

(the old `eocene` command does the same; it is removed in phase 4b of the refactor).

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
ecefast eocene -c configs/laptop.yml --copy
```

## Command-line options

```text
-c, --config   Path to the YAML configuration file. Required.
-l, --log      Logging level. Default: INFO.
-r, --run      Workflow section to run: oifs, nemo, oasis, rnfm, all. Default: all.
--copy         Copy the required input subtree to the output directory before running.
```

Examples:

```bash
ecefast eocene -c configs/laptop.yml --copy
ecefast eocene -c configs/laptop.yml --run oifs -l DEBUG
ecefast eocene -c configs/laptop.yml --run nemo -l INFO
ecefast eocene -c configs/laptop.yml --run rnfm
ecefast eocene -c configs/laptop.yml --run all --copy
```

## Configuration file

One YAML file per machine (schema 1). Start from `configs/laptop.tmpl` (or `configs/atos.tmpl` on ECMWF Atos).
Minimal structure for `ecefast eocene`:

```yaml
schema: 1
paths:
  input: /path/to/ECE4-DATA-V3              # EC-Earth input tree, read-only
  output: /path/to/EOCENE-TEST              # destination tree for copied and generated files
  herold: /path/to/herold-et-al-2014/Supp   # Herold paleo datasets, read-only
tools:
  precomputed:
    domain: /path/to/domain/PALEORCA2/eocene  # domain_cfg.nc and maskutil.nc for the Eocene bathymetry
```

Optional sections: `grids` (`oifs: TL63L31`, `nemo: PALEORCA2`), `eocene` (`oifs.aerosols: false`,
`oasis.constant_sst: 290.0`) and `nemo_domain` (the NEMO domain pipeline, `ecefast nemo-domain -c <file>`).
Every key is described in `docs/configuration.rst`. The old `dirs:` format is no longer read.

## What `--copy` copies

The copy step does not clone the full input tree. It copies only the subsets currently used by the workflow:

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

- copies `domain_cfg.nc` and `maskutil.nc` into the output tree
- creates tidal mixing forcing
- creates geothermal heat flux forcing
- creates ocean initial conditions

### RNFM

The runoff workflow:

- reads the Herold runoff slope dataset
- computes drainage basins and arrival points
- writes a new `runoff_maps.nc`