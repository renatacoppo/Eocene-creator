# hpc_env.sh: sourced by run_domain_cfg.sh and run_sections_diadct.sh (not run on its own).
#
# Loads the HPC modules needed to compile and run the NEMO tools, and sets LD_LIBRARY_PATH.
# Module loading must live in the shell scripts: it cannot propagate back to a Python parent process.

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
