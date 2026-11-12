#!/usr/bin/env bash
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
source "$here/runtime-config.sh"
vtk="${PICLAS_VTK_BIN:-$PICLAS_RUNTIME_DIR/vtk/bin/piclas2vtk}"
export LD_LIBRARY_PATH="$PICLAS_RUNTIME_DIR/vtk/lib:$PICLAS_RUNTIME_DIR/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
[[ -x "$vtk" ]] || { echo 'Extract the runtime bundle or set PICLAS_VTK_BIN.' >&2; exit 2; }
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 BLIS_NUM_THREADS=1
if [[ $# == 1 ]]; then cd "$1"; fi
shopt -s nullglob
for file in helium_pulse_State_*.h5; do
    stamp="${file#helium_pulse_State_}"
    if [[ ! -s "helium_pulse_Solution_${stamp%.h5}.vtu" || ! -s "helium_pulse_Solution_ElemData_${stamp%.h5}.vtu" ]]; then
        "$vtk" parameter.ini "$file"
    fi
done
