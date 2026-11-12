#!/usr/bin/env bash
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
case_dir="${1:-$here}"
cd "$case_dir"
exec 8>mesh.lock
flock -n 8 || { echo "This case is already meshing or running."; exit 2; }
if [[ "$case_dir" != "$here" && -f mesh-geometry.json ]]; then
    echo "This case already has a mesh. Create a new case to change its geometry."
    exit 2
fi
source "$here/runtime-config.sh"
envdir="$PICLAS_MESH_ENV/bin"
[[ -x "$envdir/pyhope" ]] || { echo 'Set up the mesh environment with bash Setup-WSL.sh --mesh.' >&2; exit 2; }
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export PYTHONPATH="$here${PYTHONPATH:+:$PYTHONPATH}"
mesh_method=$("$envdir/python" -c 'import json; print(json.load(open("geometry.json")).get("mesh_method", "tetrahedral"))')
if [[ "$mesh_method" == swept || "$mesh_method" == axisymmetric ]]; then
    if [[ "$mesh_method" == axisymmetric ]]; then
        "$envdir/python" "$here/meshing/make_axisymmetric_mesh.py"
    else
        "$envdir/python" "$here/meshing/make_swept_mesh.py"
    fi
    sed 's/^doSplitToHex = T/doSplitToHex = F/' "$here/mesh.ini" > mesh.ini
    if [[ "$mesh_method" == axisymmetric ]]; then
        cat >> mesh.ini <<'EOF'
MeshSortingSFC = mortonZ
BoundaryName = BC_Axis
BoundaryType = (/10,0,0,0/)
BoundaryName = BC_Sym
BoundaryType = (/10,0,0,0/)
EOF
    fi
    "$envdir/pyhope" mesh.ini
    "$envdir/python" "$here/meshing/swept_mesh_materials.py"
else
    "$envdir/python" "$here/meshing/make_mesh.py"
    if [[ "$case_dir" != "$here" ]]; then cp "$here/mesh.ini" mesh.ini; fi
    "$envdir/pyhope" mesh.ini
    "$envdir/python" "$here/meshing/mesh_materials.py"
fi
"$envdir/python" "$here/meshing/export_geometry.py"
cp geometry.json mesh-geometry.json
