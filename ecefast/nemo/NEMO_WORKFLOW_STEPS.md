# NEMO Workflow Steps

## Overview
This workflow processes bathymetry and coordinate data to generate NEMO domain configuration files for both present-day and Eocene paleoenvironments on the PALEORCA2 grid.

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
- Define directory paths based on the system environment (local machine vs. HPC cluster)
- Set target grid parameters (PALEORCA2) and source grid parameters (eORCA1)
- Configure processing flags to enable/disable specific workflow stages

---

## Step 2: Coordinate and Bounds Generation (Optional)
- Remove halo from original source grid coordinates
- Generate coordinate bounds for both T and F staggering configurations
- Process bounds for source and target grids independently
- Output: Bounded coordinate files for T and F staggering

---

## Step 3: Present-Day Bathymetry Processing

### 3a. Extract Bathymetry
- Extract bathymetry data from source grid domain configuration
- Retain navigation variables (coordinates)
- Source: NEMO eORCA1 domain_cfg.nc file (contains pre-configured bathymetry)

### 3b. Generate Land-Sea Mask
- Convert bathymetry to binary land-sea mask using conservative remapping
- Set all land values (bathy ≤ 0) to 1, ocean values (bathy > 0) to 0
- Apply threshold: Values < 0.5 → 0 (land); values > 0.5 → 1 (sea)
  
### 3c. Remap Bathymetry
- Remap bathymetry from source to target grid using nearest-neighbor interpolation
- Apply land-sea mask via multiplication (ocean values preserved, land masked to 0)
- Apply minimum depth threshold: any value between 0.00001m and 30m → 30m
  - *Purpose*: Eliminates unrealistically shallow water that could cause numerical issues
- Output: Corrected bathymetry preserving coastal accuracy

---

## Step 4: Eocene Paleobathymetry Processing

### 4a. Extract Paleobathymetry
- Extract Eocene topography data from Herold paleobathymetry dataset
- Variable name: `paleotopo` (renamed to `bathy_metry` for consistency)
- Source: Herold paleobathymetry at 1×1° resolution

### 4b. Generate Land-Sea Mask
- Create binary land-sea mask from paleobathymetry using conservative remapping
- Threshold values: 
  - Paleotopography < -0.0001m (ocean floor) → 1 (sea)
  - Paleotopography 0 to 10,000m (land/mountains) → 0 (land)
- Apply threshold to mask: values < 0.5 → 0 (land); values > 0.5 → 1 (sea)

### 4c. Remap Paleobathymetry
- Convert Herold values from positive (elevation) to negative (depth convention)
  - *Rationale*: Herold dataset uses positive elevations; NEMO uses negative bathymetric depths
  - *Conversion*: Multiply by -1
- Remap using bilinear interpolation from source to target grid
  - *Rationale*: Smoother paleotopography preferred over present-day due to different coastal dynamics
- Apply land-sea mask to ocean regions
- Apply minimum depth threshold: any positive value between 0.00001m and 30m → 30m
  - *Purpose*: Ensures paleocean depths also respect NEMO numerical stability requirements

---

## Step 5: Fix Present-Day Bathymetry (Custom Adjustments)
- Apply custom script to manually adjust specific regions
- Open/close straits as needed for oceanographic accuracy
- Regions typically modified: Gibraltar, Red Sea, Adriatic, Baltic, Arctic passages
  - *Rationale*: Automated remapping may incorrectly close/open shallow straits
  - *Approach*: Average neighboring ocean depths or set specific values based on oceanographic knowledge
- Verify and correct land points configuration

---

## Step 6: Configure Domain Namelist
- Read bathymetry files and automatically extract grid dimensions
- Identify bathymetry variable and coordinate variables by name patterns
- Generate NEMO DOMAINcfg namelists for both present-day and Eocene scenarios
- Configuration includes:
  - Bathymetry file path and variable name
  - Coordinate file path and variable names (lon, lat)
  - Grid dimensions (extracted from data)
  - Target configuration: PALEORCA2, 31 vertical levels
- Output: Namelist files ready for NEMO domain tool execution

---

## Step 7: Execute NEMO Domain Tool
- Load required software modules and libraries (HDF5, NetCDF, Intel compiler, OpenMPI, ECMWF toolbox)
- Compile NEMO DOMAINcfg tool with ECE4 configuration
- Execute domain configuration for present-day bathymetry
  - Generates `domain_cfg.nc` and mesh mask file
  - Contains all necessary grid information and masks for NEMO simulation
- Execute domain configuration for Eocene paleobathymetry
  - Separate execution with Eocene bathymetry namelist
  - Generates paleoclimate domain configuration files
- Generate mask utility files for both scenarios
  - These contain binary masks (land=0, ocean=1) used throughout NEMO simulation

---

## Output Files

### Coordinate Files
- `coords_bounds_T.nc`, `coords_bounds_F.nc` (for each grid)
  - Contains: Grid cell corners and center points for both T and F staggering
  - Purpose: Used as reference grids for all subsequent remapping operations

### Bathymetry Files (Intermediate)
- `eORCA1_T_bathy_metry_remapnn_to_PALEORCA2_T.nc` (pre-correction)
  - Contains: Remapped present-day bathymetry before manual adjustments
  
- `eORCA1_T_bathy_metry_remapnn_to_PALEORCA2_T_corrected.nc` (final present-day)
  - Contains: Present-day bathymetry with strait corrections applied
  - Used for: Present-day domain configuration
  
- `HEROLD_bathy_metry_remapbil_to_PALEORCA2_T.nc` (final Eocene)
  - Contains: Paleobathymetry remapped and corrected
  - Used for: Eocene domain configuration

### Configuration Files
- `namelist_cfg_present`
  - Contains: NEMO namelist parameters for present-day domain configuration
  - References: Present-day bathymetry, coordinates, grid dimensions
  
- `namelist_cfg_eocene`
  - Contains: NEMO namelist parameters for Eocene domain configuration
  - References: Eocene bathymetry, coordinates, grid dimensions

### Final Domain Output
- `domain_cfg.nc` and `maskutil.nc` for present-day and eocene
  - Contains: Complete NEMO domain configuration (coordinates, masks, metrics, weights)
  - Purpose: Primary input for NEMO ocean model simulations
