#!/usr/bin/env bash
set -euo pipefail
sudo apt-get update
sudo apt-get install -y openmpi-bin libhdf5-openmpi-dev libopenblas0-pthread libgfortran5 python3
if [[ "${1:-}" == "--mesh" ]]; then
    sudo apt-get install -y python3-venv libglu1-mesa
    mesh_env="${PICLAS_MESH_ENV:-$HOME/.local/share/piclas-project/pyhope}"
    python3 -m venv "$mesh_env"
    "$mesh_env/bin/python" -m pip install 'PyHOPE==1.1.0' gmsh meshio h5py scipy
fi
