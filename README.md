# Eocene Creator CLI

This repository provides a workflow to prepare Eocene boundary conditions for EC-Earth4 components from an existing input dataset.

The main entry point is:

```bash
./eocene/cli-eocene.py
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
python eocene/cli-eocene.py -c eocene/config.yml --copy
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
./eocene/cli-eocene.py -c eocene/config-paolo.yml --copy
./eocene/cli-eocene.py -c eocene/config-paolo.yml --run oifs -l DEBUG
./eocene/cli-eocene.py -c eocene/config-paolo.yml --run nemo -l INFO
./eocene/cli-eocene.py -c eocene/config-paolo.yml --run rnfm
./eocene/cli-eocene.py -c eocene/config-paolo.yml --run all --copy
```

## Configuration file

The CLI expects a YAML file with a top-level `dirs` section.

Minimal structure:

```yaml
dirs:
  input: /path/to/ECE4-DATA-V2
  output: /path/to/output
  herold: /path/to/herold-data
  domain: /path/to/nemo/domain/PALEORCA2
  tmpdir: /path/to/tmp
```

Field meaning:

- `input`: source EC-Earth data tree
- `output`: destination tree where copied and generated files are written
- `herold`: directory containing Herold paleo input datasets
- `domain`: directory containing `domain_cfg.nc` and `maskutil.nc`
- `tmpdir`: reserved temporary directory path (not used yet)

A real example is available in `eocene/config.tmpl`.

## What `--copy` copies

The copy step does not clone the full input tree. It copies only the subsets currently used by the workflow:

- `oifs`: `composition`, `ifsdata`, `vtables`, `rtables`, and `TL63L31`
- `nemo`: `cfc`, `climatology`, `initial`, and `weights`
- `oasis`: only the configured NEMO resolution subdirectory
- `cmip6-data`: linked as a symbolic link instead of copied

Everything else is skipped.

## Workflow notes

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

## Current limitations

- `oasis` is not yet exposed as a `--run` target in the CLI
- the `--copy` path contains a temporary hack that copies `rstos.nc` from `dirs.oasisdir`
- some workflows require external binaries and large input datasets that are not validated by the CLI before execution

## Troubleshooting

If imports fail when calling the script directly, prefer running it from the repository root:

```bash
python eocene/cli-eocene.py -c eocene/config-paolo.yml --run nemo
```

If OIFS or NEMO fail early, verify that `cdo` is available in the active environment:

```bash
cdo -V
```

If `--copy` fails, check that:

- the output directory is writable
- the paths in the YAML file exist
- `dirs.oasisdir` exists if you are relying on the current `rstos.nc` copy hack
