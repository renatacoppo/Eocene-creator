# NEMO Workflow Steps

## Overview
This workflow processes bathymetry and coordinate data to generate NEMO domain configuration files for both present-day and Eocene paleoenvironments on the PALEORCA2 grid.

**Main Entry Point**: `cli-domain-paleorca.py --config nemo_workflow.yaml`

**Configuration**: Controlled via `nemo_workflow.yaml` with profile-based paths:
- `output_dir`: Base output directory (coordinates/, bathymetry/, domain/)
- `domaincfg_dir`: NEMO tools directory (for HPC compilation)
- `coords_ori`: Pre-existing target grid coordinates (input)
- `mesh_mask`: Pre-existing source grid mesh mask (input)

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
**YAML Key**: `profile` (altai/atos)

Directory structure derived from `output_dir`:
- `{output_dir}/coordinates/{grid}/` - coordinate bounds files
- `{output_dir}/bathymetry/{grid}/` - processed bathymetry files
- `{output_dir}/domain/{grid}/{name}/` - final domain_cfg and maskutil files
- `{domaincfg_dir}/DOMAINcfg/` - NEMO tool workspace (HPC only)

Workflow steps controlled via `steps` flags in YAML:
- `coordinates`, `bathymetry`, `configure_domain`, `domain_cfg`, `generate_mask`, `generate_subbasins`

---

## Step 2: Coordinate and Bounds Generation
**YAML Key**: `steps.coordinates`
**Method**: `NEMOWorkflow.generate_coordinates()`

- Remove halo from target grid coordinates (`coords_ori`) using CDO `sethalo(-1,-1)`
  - Output: `{output_dir}/coordinates/PALEORCA2/coords_halo.nc`
- Generate coordinate bounds for both T and F staggering via `generate-orca-bounds.py`
  - Target grid: `coords_bounds_T.nc`, `coords_bounds_F.nc` (from coords_halo.nc)
  - Source grid: `coords_bounds_T.nc`, `coords_bounds_F.nc` (from mesh_mask)
- Staggering selection controlled by `grids.staggering_target` and `grids.staggering_source`

---

## Step 3: Present-Day Bathymetry Processing
**YAML Key**: `steps.bathymetry`, `bathymetries[name=present_day]`
**Processor**: `PresentDayBathymetry` (processors/present_day.py)
**Method**: `NEMOWorkflow.process_bathymetry(cfg)`

### 3a. Extract and Remap Bathymetry
- Extract `bathy_metry` from source domain_cfg (eORCA1)
- Apply CDO chain: `remapnn` → `sethalo(-1,-1)` → `setgrid(coords_bounds_T.nc)`
- Output: `{output_dir}/bathymetry/PALEORCA2/eORCA1_T_bathy_metry_remapnn_to_PALEORCA2_T.nc`

### 3b. Apply Strait Corrections (postprocess)
- Load corrections from `config/bathymetry_corrections.yaml` (key: `PALEORCA2_remapnn`)
- **Open regions**: average neighboring ocean depths for narrow straits
- **Close regions**: set depth to 0 (land) for regions that should be closed
- Apply minimum depth threshold: `0 < depth < 30m` → `30m`
- Output: `eORCA1_T_bathy_metry_remapnn_to_PALEORCA2_T_corrected.nc`

*Rationale*: Nearest-neighbor prevents coastal interpolation artifacts but may incorrectly close/open straits

---

## Step 4: Eocene Paleobathymetry Processing
**YAML Key**: `steps.bathymetry`, `bathymetries[name=eocene]`
**Processor**: `EoceneBathymetry` (processors/eocene.py)
**Method**: `NEMOWorkflow.process_bathymetry(cfg)`

### 4a. Extract and Remap Paleobathymetry
- Extract `paleotopo` from Herold dataset, rename to `bathy_metry`
- Generate land-sea mask: paleotopo < 0 (ocean) → 1, paleotopo ≥ 0 (land) → 0
- Apply CDO chain: 
  - Invert sign (elevation → depth): `expr,'bathy_metry=-1*paleotopo'`
  - Remap with bilinear interpolation: `remapbil`
  - Remove halo: `sethalo(-1,-1)`
  - Set grid: `setgrid(coords_bounds_T.nc)` (no setgrid file needed for Eocene)
- Apply minimum depth: `0 < depth < 30m` → `30m`
- Output: `{output_dir}/bathymetry/PALEORCA2/HEROLD_bathy_metry_remapbil_to_PALEORCA2_T.nc`

*No postprocessing*: Eocene processor does not apply strait corrections

*Rationale*: Bilinear interpolation provides smoother paleotopography; no strait corrections needed for paleoclimate

---

## Step 5: Configure Domain Namelists
**YAML Key**: `steps.configure_domain`
**Method**: `NEMOWorkflow.configure_domain_namelists()`
**Script**: `domain-tools/config-namelist-domain.py`

- Read bathymetry files and extract grid dimensions automatically
- Generate NEMO DOMAINcfg namelists via Jinja2 template (`namelist_cfg.j2`)
- Write namelists to:
  - HPC: `{domaincfg_dir}/DOMAINcfg/namelist_cfg_{name}`
  - Local: `{output_dir}/domain/namelist_cfg_{name}`
- Configuration includes:
  - Bathymetry file path and variable name (`bathy_metry`)
  - Coordinates file path (`coords_halo.nc`)
  - Grid dimensions (jpiglo, jpjglo from data)
  - Minimum depth: from `parameters.minimum_depth`

---

## Step 6: Run NEMO Domain Configuration Tool (HPC)
**YAML Key**: `steps.domain_cfg`
**Method**: `NEMOWorkflow.run_domain_cfg()`
**Script**: `domain-tools/run_domain_cfg.sh`

- Load HPC modules from `config/hpc_modules.yaml` (environment: atos)
  - Modules: prgenv/intel, intel/2021.4.0, hdf5-parallel/1.12.2, netcdf4-parallel/4.9.1, etc.
- Compile DOMAINcfg tool: `maketools -m ecearth -n DOMAINcfg`
  - Skips compilation if executable already exists
- Execute `make_domain_cfg.exe` for each bathymetry name
  - Uses `namelist_cfg_{name}` from Step 5
  - Generates: `domain_cfg_{name}.nc`, `mesh_mask_{name}.nc`
  - Renames files immediately to prevent overwriting
- Error handling: captures segfault (exit 139), validates output with CDO
- Working directory: `{domaincfg_dir}/DOMAINcfg/`

---

## Step 7: Post-Process Domain Files and Extract Maskutil
**YAML Key**: `steps.generate_mask`
**Method**: `NEMOWorkflow.generate_mask_util()`
**Functions**: `common.util.process_domain_cfg()`, `common.util.extract_maskutil()`

### 7a. Process domain_cfg.nc
- Read `domain_cfg_{name}.nc` from `{domaincfg_dir}/DOMAINcfg/`
- Rename vertical dimension: `nav_lev` → `z`
- Add PALEORCA attributes: `cn_cfg='PALEORCA'`, `nn_cfg=2`
- Write to: `{output_dir}/domain/{grid}/{name}/domain_cfg.nc`

### 7b. Extract maskutil.nc
- Read `mesh_mask_{name}.nc` from `{domaincfg_dir}/DOMAINcfg/`
- Extract mask variables: `tmaskutil`, `umaskutil`, `vmaskutil`
- Rename time dimension: `time_counter` → `t`
- Write to: `{output_dir}/domain/{grid}/{name}/maskutil.nc`

**Dependency check**: Verifies domain_cfg and mesh_mask files exist before running

---

## Step 8: Generate Ocean Subbasin Masks (Present-Day Only)
**YAML Key**: `steps.generate_subbasins`
**Method**: `NEMOWorkflow.generate_subbasins()`
**Script**: `domain-tools/generate-subbasins.py`

- Only runs for `PresentDayBathymetry` processor (skips Eocene)
- Read `mesh_mask_{name}.nc` from `{domaincfg_dir}/DOMAINcfg/`
- Extract surface mask (`tmask[0,0,:,:]`) and coordinates (`glamt`, `gphit`)
- Classify ocean points into basins using shapely polygons:
  - Atlantic Ocean (includes Mediterranean, Arctic connections)
  - Pacific Ocean (MultiPolygon: eastern + western parts split at dateline)
  - Indian Ocean
  - Indo-Pacific (Pacific + Indian combined)
  - Global ocean
- Write to: `{output_dir}/domain/{grid}/{name}/subbasins.nc`
  - Variables: `atlmsk`, `pacmsk`, `indmsk`, `indpacmsk`, `glomsk`

**Dependency check**: Verifies mesh_mask files exist before running

---

## Output Files

### Coordinate Files
- `{output_dir}/coordinates/PALEORCA2/coords_halo.nc`
- `{output_dir}/coordinates/PALEORCA2/coords_bounds_{T,F}.nc`
- `{output_dir}/coordinates/eORCA1/coords_bounds_{T,F}.nc`
  - Contains: Grid cell corners and center points
  - Purpose: Reference grids for all remapping operations

### Bathymetry Files (Intermediate)
- `{output_dir}/bathymetry/PALEORCA2/eORCA1_T_bathy_metry_remapnn_to_PALEORCA2_T.nc` (pre-correction)
  - Contains: Remapped present-day bathymetry before manual adjustments
  
- `{output_dir}/bathymetry/PALEORCA2/eORCA1_T_bathy_metry_remapnn_to_PALEORCA2_T_corrected.nc` (final present-day)
  - Contains: Present-day bathymetry with strait corrections applied
  - Used for: Present-day domain configuration
  
- `{output_dir}/bathymetry/PALEORCA2/HEROLD_bathy_metry_remapbil_to_PALEORCA2_T.nc` (final Eocene)
  - Contains: Paleobathymetry remapped and processed
  - Used for: Eocene domain configuration

### Configuration Files (HPC)
- `{domaincfg_dir}/DOMAINcfg/namelist_cfg_{name}`
  - Contains: NEMO namelist parameters for domain configuration
  - Generated via Jinja2 template from bathymetry/coordinates metadata
  - References: Bathymetry path, coordinates path, grid dimensions, vertical levels

### Domain Files (Intermediate - HPC)
- `{domaincfg_dir}/DOMAINcfg/domain_cfg_{name}.nc`
- `{domaincfg_dir}/DOMAINcfg/mesh_mask_{name}.nc`
  - Generated by NEMO DOMAINcfg tool
  - Processed and moved to final location in Step 7

### Final Domain Output
- `{output_dir}/domain/PALEORCA2/{name}/domain_cfg.nc`
  - Complete NEMO domain configuration (coordinates, scales, metrics)
  - Modified: vertical dimension renamed, PALEORCA attributes added
- `{output_dir}/domain/PALEORCA2/{name}/maskutil.nc`
  - Binary masks: tmaskutil, umaskutil, vmaskutil
  - Purpose: Used throughout NEMO simulation for masking operations
- `{output_dir}/domain/PALEORCA2/{name}/subbasins.nc` (present-day only)
  - Ocean basin masks: Atlantic, Pacific, Indian, Indo-Pacific, Global
  - Purpose: Regional diagnostics and analysis
