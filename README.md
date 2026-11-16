# Eocene-creator (`ecefast`)

`ecefast` builds EC-Earth4 input data for a time period, on ECMWF Atos:

- `present`: the present-day NEMO PALEORCA2 domain (`domain_cfg.nc`, `maskutil.nc`, `subbasins.nc`,
  `section_ijglobal.diadct`), built with DOMAINcfg from the eORCA1 bathymetry of an ECE4-DATA tree;
- `eocene`: Eocene (DeepMIP) boundary conditions for OIFS TL63L31, NEMO PALEORCA2, OASIS and the runoff-mapper,
  from Herold et al. (2014), with the Eocene NEMO domain.

Each period writes a tree laid out as an EC-Earth4 input tree.

## Quickstart on Atos

```bash
git clone https://github.com/renatacoppo/Eocene-creator.git && cd Eocene-creator
module load conda
mamba env create -f environment.yaml           # once
conda activate eocene
module load cdo/2.5.3                          # data_version v1 needs CDO 2.5.x

cp configs/atos.tmpl configs/atos.yml          # set the /path/to/... values
ecefast present run -c configs/atos.yml --dry-run
ecefast present run -c configs/atos.yml        # present-day tree
ecefast eocene run -c configs/atos.yml         # Eocene tree, starting from the present-day one
```

Run on an interactive node (`ecinteractive`) or in a batch job. Each tree ends with `provenance.yml` (steps,
configuration, git commit, data version, CDO and ecCodes versions).

## Documentation

The documentation is in `docs/` (Sphinx: `pip install -e ".[docs]" && sphinx-build -b html docs docs/_build/html`):

- `docs/quickstart.rst`: setup, running, what each step makes, checking the result;
- `docs/configuration.rst`: every configuration key;
- `docs/bathymetry.rst`: how a NEMO bathymetry is made, and how to add a new one;
- the API reference, generated from the docstrings.

Rules for contributors and coding agents: [AGENTS.md](AGENTS.md). Changes: [CHANGELOG.rst](CHANGELOG.rst).
