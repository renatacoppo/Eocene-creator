#!/bin/bash
# run_domain_cfg.sh <ecedir> <outputdir> <tgtgrid> <name1> [name2 ...]
#
# HPC-only block: module loading, compilation, and execution of the NEMO
# DOMAINcfg tool. Called from cli-domain-paleorca.py via subprocess.
# Module loading must live here — it cannot propagate back to a Python parent process.

set -euo pipefail

# Resolve directory of this script so helper scripts are found regardless of cwd
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ECEDIR=$1
OUTPUTDIR=$2
TGTGRID=$3
shift 3
NAMES=("$@")

# --- Load HPC modules ---
module reset
module load prgenv/intel intel/2021.4.0 intel-mkl/19.0.5 hpcx-openmpi/2.9.0
module load hdf5-parallel/1.12.2 netcdf4-parallel/4.9.1 ecmwf-toolbox/2023.04.1.0

export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:\
$NETCDF4_PARALLEL_DIR/lib:\
$ECCODES_DIR/lib:\
$HDF5_DIR/lib:\
$HPCPERM/ecearth4/revisions/main/sources/oasis3-mct-5.2/arch_ecearth/lib

# --- Compile DOMAINcfg tool ---
cd "$ECEDIR"
./maketools -m ecearth -n DOMAINcfg clean
cd "$ECEDIR/DOMAINcfg"

# --- Run domain configuration for each bathymetry ---
for name in "${NAMES[@]}"; do
    echo "Running domain configuration for: $name"

    cp "namelist_cfg_${name}" namelist_cfg
    ./make_domain_cfg.exe
    rm namelist_cfg

    mkdir -p "$OUTPUTDIR/$TGTGRID/$name"
    python3 "$SCRIPT_DIR/generate-mask-util.py" \
        --src_dir "$ECEDIR/DOMAINcfg" \
        --tgt_dir "$OUTPUTDIR/$TGTGRID/$name"

    echo "Domain configuration complete for: $name"
done
