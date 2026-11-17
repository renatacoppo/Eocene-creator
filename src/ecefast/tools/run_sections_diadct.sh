#!/bin/bash
# run_sections_diadct.sh <tools_dir> <workdir> <sections_list>
#
# HPC-only block: module loading (hpc_env.sh), compilation, and execution of the NEMO SECTIONS_DIADCT tool,
# which writes section_ijglobal.diadct, the transport sections read by the NEMO diagnostic diadct.
# Called by ecefast.tools.ecearth.AtosBackend.
#
# <tools_dir>      NEMO tools directory (holds maketools and SECTIONS_DIADCT/); the tool is compiled there if needed
# <workdir>        run directory: must hold coordinates.nc (glamt, gphit, glamf, gphif, e1t, dimension x before y);
#                  section_ijglobal.diadct is written here
# <sections_list>  list of sections in lon/lat (list_sections.ascii format of SECTIONS_DIADCT)

set -euo pipefail

TOOLS_DIR=$1
WORKDIR=$2
SECTIONS_LIST=$3
EXE="$TOOLS_DIR/SECTIONS_DIADCT/diadct_sections.exe"

# --- Load HPC modules ---
source "$(dirname "${BASH_SOURCE[0]}")/hpc_env.sh"

# --- Compile SECTIONS_DIADCT tool ---
# maketools links BLD/bin/diadct_sections.exe into SECTIONS_DIADCT/
if [[ ! -f "$EXE" ]]; then
    echo "Compiling SECTIONS_DIADCT tool..."
    (cd "$TOOLS_DIR" && ./maketools -m ecearth -n SECTIONS_DIADCT)
else
    echo "SECTIONS_DIADCT tool already compiled, skipping build."
fi
if [[ ! -f "$EXE" ]]; then
    echo "ERROR: compiling SECTIONS_DIADCT did not produce $EXE" >&2
    exit 1
fi

# --- Run it in the work directory ---
# The program reads ./coordinates.nc, ./list_sections.ascii and ./namelist (nsecdebug = 0: no debug files)
cd "$WORKDIR"
ln -sf "$SECTIONS_LIST" list_sections.ascii
cat > namelist <<'NAMELIST'
&namdct
nsecdebug = 0
/
NAMELIST
rm -f section_ijglobal.diadct
"$EXE"

if [[ ! -s section_ijglobal.diadct ]]; then
    echo "ERROR: SECTIONS_DIADCT did not write section_ijglobal.diadct in $WORKDIR" >&2
    exit 1
fi
echo "SECTIONS_DIADCT complete: $WORKDIR/section_ijglobal.diadct"
