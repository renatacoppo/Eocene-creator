#!/usr/bin/env bash
# Pull a subset of ECE4-DATA-V3 from a remote: OIFS TL63L31, NEMO PALEORCA2 (+ grid-independent
# initial files and the ORCA2 domain read by the Eocene workflow, eORCA1 domain read by the present-day
# bathymetry of the NEMO domain pipeline), OASIS PALEORCA2, runoff-mapper.
# Usage: ./get_ece4_data.sh user@host:/path/to/ECE4-DATA-V3 [/local/dest] [-n]
#        ECE4_DATA_SRC=user@host:/path/to/ECE4-DATA-V3 ./get_ece4_data.sh
#   -n  dry run (list what would be transferred)
set -euo pipefail

SRC="${1:-${ECE4_DATA_SRC:-}}"
DST="${2:-}"
DRY="${3:-}"

if [[ -z $SRC ]]; then
  echo "Usage: $0 user@host:/path/to/ECE4-DATA-V3 [dest] [-n]  (or set ECE4_DATA_SRC)" >&2
  exit 1
fi

if [[ -z $DST ]]; then
  DST="ECE4-DATA-V3"
  echo "No destination specified, defaulting to $DST"
fi

# -L: top-level dirs are symlinks to /lus/.../gdjk, copy their contents
# -m: drop empty dirs left by the directory-walking includes
rsync -avhL -m --partial --progress ${DRY:+--dry-run} \
  --include='/oifs/' \
  --include='/oifs/TL63L31/***' \
  --include='/oifs/ifsdata/***' \
  --include='/oifs/composition/***' \
  --include='/oifs/rtables/***' \
  --include='/oifs/vtables/***' \
  --exclude='/nemo/restart*/' \
  --include='/nemo/' \
  --include='/nemo/initial/woa13-levitus-L31.nc' \
  --include='/nemo/initial/zdfiwm_forcing_r720x360.nc' \
  --include='/nemo/initial/Goutorbe_ghflux.nc' \
  --include='/nemo/domain/ORCA2/domain_cfg.nc' \
  --include='/nemo/domain/eORCA1/domain_cfg.nc' \
  --include='/nemo/**/PALEORCA2/***' \
  --include='/nemo/**PALEORCA2*' \
  --include='/nemo/**/' \
  --include='/oasis/' \
  --include='/oasis/PALEORCA2/***' \
  --include='/runoff-mapper/***' \
  --exclude='*' \
  "${SRC%/}/" "$DST/"
