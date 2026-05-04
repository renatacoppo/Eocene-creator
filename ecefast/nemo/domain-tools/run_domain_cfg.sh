#!/bin/bash
# run_domain_cfg.sh <ecedir> <clean> <name1> [name2 ...]
#
# HPC-only block: module loading, compilation, and execution of the NEMO
# DOMAINcfg tool. Called from cli-domain-paleorca.py via subprocess.
# Module loading must live here — it cannot propagate back to a Python parent process.

set -euo pipefail

# Resolve directory of this script so helper scripts are found regardless of cwd
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ECEDIR=$1
CLEAN=$2   # '1' = force clean recompilation, '0' = skip if binary exists
shift 2
NAMES=("$@")

# --- Load HPC modules from config ---
module reset

# Get modules from config/hpc_modules.yaml using Python
NEMO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
MODULES=$(python3 <<PYTHON_EOF
import sys
sys.path.insert(0, "$NEMO_DIR")
from config import get_hpc_modules
try:
    modules = get_hpc_modules('atos')
    print(' '.join(modules))
except Exception as e:
    print(f"ERROR: {e}", file=sys.stderr)
    sys.exit(1)
PYTHON_EOF
)

for module in $MODULES; do
    module load "$module" || {
        echo "WARNING: Failed to load module '$module'" >&2
    }
done

export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:\
$NETCDF4_PARALLEL_DIR/lib:\
$ECCODES_DIR/lib:\
$HDF5_DIR/lib:\
$HPCPERM/ecearth4/revisions/main/sources/oasis3-mct-5.2/arch_ecearth/lib

# --- Compile DOMAINcfg tool ---
cd "$ECEDIR"
if [[ "$CLEAN" == "1" || ! -f "DOMAINcfg/make_domain_cfg.exe" ]]; then
    ./maketools -m ecearth -n DOMAINcfg clean
else
    ./maketools -m ecearth -n DOMAINcfg
fi
cd "$ECEDIR/DOMAINcfg"

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

    echo "Domain configuration complete for: $name"
done
