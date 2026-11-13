# NEMO Workflow Steps

## Overview
This workflow processes bathymetry and coordinate data to generate NEMO domain configuration files for both present-day and Eocene paleoenvironments on the PALEORCA2 grid.

`NEMOWorkflow` builds the NEMO domain of **one** bathymetry. Each time period runs it with its own bathymetry:

- present day: the `nemo` step, `ecefast present run` or `ecefast nemo run -c configs/laptop.yml [--nemo a,b]`
- Eocene: inside the `domain` step with `eocene.nemo.domain: build`,
  `ecefast eocene run -c configs/atos.yml` or `ecefast nemo run -c configs/atos.yml --period eocene`

**Bathymetry processors**: not configured. Each period passes its own `BathymetryProcessor` subclass to
`NEMOWorkflow`: `ecefast.periods.present.bathymetry.PresentDayBathymetry` (present day) or
`ecefast.periods.eocene.bathymetry.EoceneBathymetry` (Eocene). This package never imports `periods`. The processor
declares its source file as a path template (`source_file`) and holds every algorithm choice.

**DOMAINcfg backend**: `NEMOWorkflow` also gets the backend of `machine.name` (`ecefast.tools.ecearth`: `atos`,
`local`, `fake`), used by the `domain_cfg` step.

**Configuration** (one file per machine, see `docs/configuration.rst`):
- `grids.nemo.name`: target grid (`PALEORCA2`)
- `grids.nemo.coords_ori`: pre-existing target grid coordinates with halo (input)
- `grids.nemo.staggering`: staggering of the target-grid bounds used in remapping (`T`)
- `<period>.nemo.minimum_depth`, `<period>.nemo.steps`
- present day only: `present.nemo.source_grid` (`eORCA1`) and `present.nemo.source_staggering` (`T`); the source
  grid is `{input}/nemo/domain/<source_grid>/domain_cfg.nc` (input tree; its horizontal grid and bathymetry)
- `machine.tmpdir`: intermediate files in `<machine.tmpdir>/<period>/nemo/`
- `machine.atos.ecearth4_sources` (Atos): DOMAINcfg runs in its `nemo-4.2/tools/DOMAINcfg/`

## Key Parameters and Decisions

### Grid Configuration
- **Target Grid**: PALEORCA2 (Paleoclimate ORCA at ~2° resolution)
- **Source Grid (Present-day)**: eORCA1 (extended ORCA at ~1° resolution)
- **Source Grid (Paleoclimate)**: Herold paleobathymetry dataset (~1° resolution)
- **Staggering**: T-grid (scalar points)
  - *Decision*: T-grid chosen based on comparison with existing Eocene domain configurations from literature

### Remapping Methods
The workflow uses different remapping strategies based on data characteristics:
- **Land-Sea Mask**: Conservative remapping (`remapcon`)
  - *Rationale*: Preserves exact area coverage, essential for creating sharp land-sea boundaries
  - *Threshold*: Values < 0.5 → land (set to 0); values > 0.5 → sea (set to 1)
  
- **Present-Day Bathymetry**: Nearest-neighbor (`remapnn`)
  - *Rationale*: Prevents coastal erosion by avoiding interpolation of bathymetry into adjacent land cells. Cannot use ETOPO due to lack of proper smoothing approach
  - *Advantage*: Land values (zeros) don't propagate into ocean cells
  
- **Eocene Paleobathymetry**: Bilinear interpolation (`remapbil`)
  - *Rationale*: More accurate for paleotopography where coastal erosion isn't a concern, aligned with output produced by Sepulchre et al. 
  - *Advantage*: Smoother transitions across paleographic boundaries

### Bathymetry Processing Parameters
- **Minimum Depth**: 30 meters
  - *Rationale*: Ensures physical realism and numerical stability in NEMO, as done in ORCA2.
  - *Implementation*: All positive depth values ≤ 30m are set to exactly 30m
  
### Paleobathymetry Specific Conversions
- **Sign Convention**: Herold bathymetry is positive; NEMO requires negative values
  - *Conversion*: Multiply by -1
  - *Land Masking*: All zero values (land) are masked out after conversion

---

## Step 1: Environment Setup
**YAML Key**: `<period>.nemo`, `grids.nemo` (one config file per machine: `configs/laptop.tmpl`, `configs/atos.tmpl`)

Directory structure (`{workdir}` = `<machine.tmpdir>/<period>/nemo`; `{name}` = the processor's `name`,
`present_day` or `eocene`, suffix of the namelist and raw DOMAINcfg files):
- `{domain_dir}` - final domain_cfg, maskutil and subbasins files: `<present.output>/nemo/domain/{grid}/` (present
  day, as in ECE4-DATA), `<machine.tmpdir>/eocene/nemo/domain/{grid}/` (Eocene build; the `domain` step installs
  domain_cfg.nc and maskutil.nc into `<eocene.output>/nemo/domain/{grid}/`)
- `{workdir}/coordinates/{grid}/` - coordinate bounds files
- `{workdir}/bathymetry/{grid}/` - processed bathymetry files
- `{namelist_dir}` - DOMAINcfg namelists and raw DOMAINcfg output: `<machine.atos.ecearth4_sources>/nemo-4.2/tools/DOMAINcfg/`
  with `machine.name: atos`, else `{workdir}/domaincfg/`

Workflow steps controlled via `<period>.nemo.steps` flags in YAML, or `--nemo a,b` for one run:
- `coordinates`, `bathymetry`, `configure_domain`, `domain_cfg`, `generate_mask`, `generate_subbasins`

---

## Step 2: Coordinate and Bounds Generation
**YAML Key**: `steps.coordinates`
**Method**: `NEMOWorkflow.generate_coordinates()`

- Remove halo from target grid coordinates (`coords_ori`) using CDO `sethalo(-1,-1)`
  - Output: `{workdir}/coordinates/PALEORCA2/coords_halo.nc`
- Generate coordinate bounds for both T and F staggering via `orca_bounds.py`
  - Target grid: `coords_bounds_T.nc`, `coords_bounds_F.nc` (from coords_halo.nc)
  - Source grid (present day only): `coords_bounds_T.nc`, `coords_bounds_F.nc` (from the source `domain_cfg.nc` of
    the input tree)
- Staggering selection controlled by `grids.nemo.staggering` and `present.nemo.source_staggering`

---

## Step 3: Present-Day Bathymetry Processing
**YAML Key**: `present.nemo.steps.bathymetry`, `present.nemo.source_grid`
**Processor**: `PresentDayBathymetry` (ecefast/periods/present/bathymetry.py)
**Method**: `NEMOWorkflow.process_bathymetry(cfg)`

### 3a. Extract and Remap Bathymetry
- Extract `bathy_metry` from source domain_cfg (`{input}/nemo/domain/eORCA1/domain_cfg.nc`)
- Apply CDO chain: `remapnn` → `sethalo(-1,-1)` → `setgrid(coords_bounds_T.nc)`
- Output: `{workdir}/bathymetry/PALEORCA2/eORCA1_T_bathy_metry_remapnn_to_PALEORCA2_T.nc`

### 3b. Apply Strait Corrections (postprocess)
- Load corrections from `config/bathymetry_corrections.yaml`, by source grid, target grid and remap method
  (key: `eORCA1_to_PALEORCA2_remapnn`); a source grid without corrections is a configuration error
- **Open regions**: average neighboring ocean depths for narrow straits
- **Close regions**: set depth to 0 (land) for regions that should be closed
- Apply minimum depth threshold: `0 < depth < 30m` → `30m`
- Output: `eORCA1_T_bathy_metry_remapnn_to_PALEORCA2_T_corrected.nc`
- Plot: `landsea_mask_comparison.png` next to it, the land-sea mask of the result and of every
  `{input}/nemo/domain/*/domain_cfg.nc`, one panel each

*Rationale*: Nearest-neighbor prevents coastal interpolation artifacts but may incorrectly close/open straits

---

## Step 4: Eocene Paleobathymetry Processing
**YAML Key**: `eocene.nemo.steps.bathymetry` (with `eocene.nemo.domain: build`)
**Processor**: `EoceneBathymetry` (ecefast/periods/eocene/bathymetry.py)
**Method**: `NEMOWorkflow.process_bathymetry(cfg)`

### 4a. Extract and Remap Paleobathymetry
- Extract `paleotopo` from Herold dataset (`{herold}/herold_etal_stddev_subgrid_etopo1_to_eocene_1x1.nc`), rename to `bathy_metry`
- Generate land-sea mask: paleotopo < 0 (ocean) → 1, paleotopo ≥ 0 (land) → 0
- Apply CDO chain: 
  - Invert sign (elevation → depth): `expr,'bathy_metry=-1*paleotopo'`
  - Remap with bilinear interpolation: `remapbil`
  - Remove halo: `sethalo(-1,-1)`
  - Set grid: `setgrid(coords_bounds_T.nc)` (no setgrid file needed for Eocene)
- Apply minimum depth: `0 < depth < 30m` → `30m`
- Output: `{workdir}/bathymetry/PALEORCA2/HEROLD_bathy_metry_remapbil_to_PALEORCA2_T.nc`

*No postprocessing*: Eocene processor does not apply strait corrections

*Rationale*: Bilinear interpolation provides smoother paleotopography; no strait corrections needed for paleoclimate

---

## Step 5: Configure Domain Namelists
**YAML Key**: `steps.configure_domain`
**Method**: `NEMOWorkflow.configure_domain_namelists()`
**Script**: `domain/namelist.py`

- Read bathymetry files and extract grid dimensions automatically
- Generate the NEMO DOMAINcfg namelist via Jinja2 template (`namelist_cfg.j2`)
- Write the namelist to:
  - Atos: `<machine.atos.ecearth4_sources>/nemo-4.2/tools/DOMAINcfg/namelist_cfg_{name}`
  - Local: `{workdir}/domaincfg/namelist_cfg_{name}`
- Configuration includes:
  - Bathymetry file path and variable name (`bathy_metry`)
  - Coordinates file path (`coords_halo.nc`)
  - Grid dimensions (jpiglo, jpjglo from data)
  - Minimum depth: from `<period>.nemo.minimum_depth`

---

## Step 6: Run NEMO Domain Configuration Tool (backend)
**YAML Key**: `steps.domain_cfg`
**Method**: `NEMOWorkflow.run_domain_cfg()` → `backend.domaincfg(namelist_dir, names)`

The backend comes from `machine.name` (see `docs/external_tools.rst`). If the step is on and the backend is not
available (`local`, or `atos` off Atos), the pipeline stops before its first step. `fake` writes small files with
the structure of the DOMAINcfg output (tests). `atos` runs `ecefast/tools/run_domain_cfg.sh`, which does:

- Load HPC modules from `ecefast/tools/hpc_profiles.yaml` (profile: atos)
  - Modules: prgenv/intel, intel/2021.4.0, hdf5-parallel/1.12.2, netcdf4-parallel/4.9.1, etc.
- Compile DOMAINcfg tool: `maketools -m ecearth -n DOMAINcfg`
  - Skips compilation if executable already exists
- Execute `make_domain_cfg.exe` for each bathymetry name
  - Uses `namelist_cfg_{name}` from Step 5
  - Generates: `domain_cfg_{name}.nc`, `mesh_mask_{name}.nc`
  - Renames files immediately to prevent overwriting
- Error handling: captures segfault (exit 139), validates output with CDO
- Working directory: `<machine.atos.ecearth4_sources>/nemo-4.2/tools/DOMAINcfg/` (the `atos` backend needs
  `ecearth4_sources`; it also adds `oasis3-mct-5.2/arch_ecearth/lib` of it to `LD_LIBRARY_PATH`)

---

## Step 7: Post-Process Domain Files and Extract Maskutil
**YAML Key**: `steps.generate_mask`
**Method**: `NEMOWorkflow.generate_mask_util()`
**Functions**: `common.util.process_domain_cfg()`, `common.util.extract_maskutil()`

### 7a. Process domain_cfg.nc
- Read `domain_cfg_{name}.nc` from `{namelist_dir}`
- Rename vertical dimension: `nav_lev` → `z`; `nav_lev` stays as a plain variable on `z`
- Add PALEORCA attributes: `cn_cfg='PALEORCA'`, `nn_cfg=2`
- Write with no `_FillValue` on any variable and `time_counter` as the unlimited dimension
- Write to: `{domain_dir}/domain_cfg.nc`

### 7b. Extract maskutil.nc
- Read `mesh_mask_{name}.nc` from `{namelist_dir}`
- Extract mask variables: `tmaskutil`, `umaskutil`, `vmaskutil`
- Rename time dimension: `time_counter` → `t` (unlimited) and drop the `time_counter` variable
- Replace the global attributes with `Conventions='CF-1.1'`
- Write to: `{domain_dir}/maskutil.nc`

These two functions are the only writer of `domain_cfg.nc` and `maskutil.nc` (the old standalone
`domain/mask_util.py` script, a copy of them, was removed). Tests: `tests/unit/test_nemo_postprocess.py`.

**Dependency check**: Verifies domain_cfg and mesh_mask files exist before running

---

## Step 8: Generate Ocean Subbasin Masks
**YAML Key**: `steps.generate_subbasins`
**Method**: `NEMOWorkflow.generate_subbasins()`
**Script**: `domain/subbasins.py`

- Runs for both periods. The polygons follow present-day geography, so a processor with
  `regional_subbasins = False` (`EoceneBathymetry`) gets the global mask only (`--global-only`, only
  `glomsk` in `subbasins.nc`); assessment and options in `notebooks/analysis/eocene-subbasins.ipynb`
- Read `mesh_mask_{name}.nc` from `{namelist_dir}`
- Extract surface mask (`tmask[0,0,:,:]`) and coordinates (`glamt`, `gphit`)
- Classify ocean points into basins using shapely polygons:
  - Atlantic Ocean (includes Mediterranean, Arctic connections)
  - Pacific Ocean (MultiPolygon: eastern + western parts split at dateline)
  - Indian Ocean
  - Indo-Pacific (Pacific + Indian combined)
  - Global ocean
- Write to: `{domain_dir}/subbasins.nc`
  - Variables: `atlmsk`, `pacmsk`, `indmsk`, `indpacmsk`, `glomsk` (`glomsk` only with `--global-only`)

**Dependency check**: Verifies mesh_mask files exist before running

---

## Output Files

### Coordinate Files
- `{workdir}/coordinates/PALEORCA2/coords_halo.nc`
- `{workdir}/coordinates/PALEORCA2/coords_bounds_{T,F}.nc`
- `{workdir}/coordinates/eORCA1/coords_bounds_{T,F}.nc`
  - Contains: Grid cell corners and center points
  - Purpose: Reference grids for all remapping operations

### Bathymetry Files (Intermediate)
- `{workdir}/bathymetry/PALEORCA2/eORCA1_T_bathy_metry_remapnn_to_PALEORCA2_T.nc` (pre-correction)
  - Contains: Remapped present-day bathymetry before manual adjustments
  
- `{workdir}/bathymetry/PALEORCA2/eORCA1_T_bathy_metry_remapnn_to_PALEORCA2_T_corrected.nc` (final present-day)
  - Contains: Present-day bathymetry with strait corrections applied
  - Used for: Present-day domain configuration
  
- `{workdir}/bathymetry/PALEORCA2/HEROLD_bathy_metry_remapbil_to_PALEORCA2_T.nc` (final Eocene)
  - Contains: Paleobathymetry remapped and processed
  - Used for: Eocene domain configuration

### Configuration Files
- `{namelist_dir}/namelist_cfg_{name}`
  - Contains: NEMO namelist parameters for domain configuration
  - Generated via Jinja2 template from bathymetry/coordinates metadata
  - References: Bathymetry path, coordinates path, grid dimensions, vertical levels

### Domain Files (Intermediate)
- `{namelist_dir}/domain_cfg_{name}.nc`
- `{namelist_dir}/mesh_mask_{name}.nc`
  - Generated by NEMO DOMAINcfg tool (through the backend)
  - Processed and moved to final location in Step 7

### Final Domain Output
- `{domain_dir}/domain_cfg.nc`
  - Complete NEMO domain configuration (coordinates, scales, metrics)
  - Modified: vertical dimension renamed, PALEORCA attributes added
- `{domain_dir}/maskutil.nc`
  - Binary masks: tmaskutil, umaskutil, vmaskutil
  - Purpose: Used throughout NEMO simulation for masking operations
- `{domain_dir}/subbasins.nc`
  - Ocean basin masks: Atlantic, Pacific, Indian, Indo-Pacific, Global (Global only for paleo bathymetries)
  - Purpose: Regional diagnostics and analysis
