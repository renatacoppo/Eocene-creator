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

- `input`: source EC-Earth data tree, the one retrieved from official repo
- `output`: destination tree where copied and generated files are written
- `herold`: directory containing Herold paleo input datasets
- `domain`: directory containing `domain_cfg.nc` and `maskutil.nc` modified for Eocene bathymetry
- `tmpdir`: reserved temporary directory path (not used yet)

A real example is available in `eocene/config.tmpl`.

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