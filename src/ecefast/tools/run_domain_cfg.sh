#!/bin/bash
# run_domain_cfg.sh <tools_dir> <name1> [name2 ...]
#
# HPC-only block: module loading, compilation, and execution of the NEMO
# DOMAINcfg tool. Called by ecefast.tools.ecearth.AtosBackend.
# Module loading must live here — it cannot propagate back to a Python parent process.

set -euo pipefail

DOMAINCFG_DIR=$1
shift 1
NAMES=("$@")

# --- Load HPC modules ---
# Module list of the HPC profile (ecefast/tools/hpc_profiles.yaml), read with the Python running ecefast.
# AtosBackend (ecefast.tools.ecearth) sets ECEFAST_PYTHON to its interpreter and ECEFAST_HPC_PROFILE to
# machine.atos.profile; the defaults serve direct calls from an activated environment.
MODULES=$("${ECEFAST_PYTHON:-python3}" -m ecefast.tools.ecearth "${ECEFAST_HPC_PROFILE:-atos}")

module reset
for module in $MODULES; do
    module load "$module" || {
        echo "WARNING: Failed to load module '$module'" >&2
    }
done

# Library directories set by the modules, plus the OASIS libraries of the EC-Earth build if given
# (ECEFAST_OASIS_LIB_DIR, from machine.atos.ecearth4_sources).
export LD_LIBRARY_PATH=${LD_LIBRARY_PATH:-}:$NETCDF4_PARALLEL_DIR/lib:$ECCODES_DIR/lib:$HDF5_DIR/lib
if [[ -n "${ECEFAST_OASIS_LIB_DIR:-}" ]]; then
    export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:$ECEFAST_OASIS_LIB_DIR
fi

# --- Compile DOMAINcfg tool ---
cd "$DOMAINCFG_DIR"
if [[ ! -f "DOMAINcfg/make_domain_cfg.exe" ]]; then
    echo "Compiling DOMAINcfg tool..."
    ./maketools -m ecearth -n DOMAINcfg
else
    echo "DOMAINcfg tool already compiled, skipping build."
fi
cd "$DOMAINCFG_DIR/DOMAINcfg"

# --- Run domain configuration for each bathymetry ---
for name in "${NAMES[@]}"; do
    echo "Running domain configuration for: $name"

    cp "namelist_cfg_${name}" namelist_cfg

    # make_domain_cfg.exe may segfault (exit 139) after writing a valid domain_cfg.nc.
    # Capture the exit code without letting set -e abort the script, then validate
    # the output with CDO before deciding whether to proceed or fail hard.
    set +e
    ./make_domain_cfg.exe
    exe_rc=$?
    set -e

    rm namelist_cfg

    if (( exe_rc != 0 )); then
        echo "WARNING: make_domain_cfg.exe exited with code ${exe_rc} (likely segfault)."
        echo "Checking whether domain_cfg.nc is readable by CDO..."
        if cdo -s sinfo domain_cfg.nc &>/dev/null; then
            echo "domain_cfg.nc is readable — continuing despite non-zero exit code."
        else
            echo "ERROR: domain_cfg.nc is missing or unreadable. Aborting." >&2
            exit "${exe_rc}"
        fi
    fi

    # Rename files immediately to prevent overwrite by next bathymetry
    echo "Renaming output files: domain_cfg_${name}.nc and mesh_mask_${name}.nc"
    mv domain_cfg.nc "domain_cfg_${name}.nc"
    mv mesh_mask.nc "mesh_mask_${name}.nc"

    echo "Domain configuration complete for: $name"
done
