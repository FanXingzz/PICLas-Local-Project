# Shared by the WSL build and run entry points.
PICLAS_UPSTREAM=${PICLAS_UPSTREAM:-$HOME/piclas}
PICLAS_SOLVER_ROOT=${PICLAS_SOLVER_ROOT:-$HOME/piclas_projects/helium_pulse_workspace}
PICLAS_JIA_INITIAL_SOLVER_ROOT=${PICLAS_JIA_INITIAL_SOLVER_ROOT:-$HOME/piclas_projects/helium_jia_initial_state_workspace}
PICLAS_JIA_DYNAMIC_SOLVER_ROOT=${PICLAS_JIA_DYNAMIC_SOLVER_ROOT:-$HOME/piclas_projects/helium_jia_dynamic_workspace}
PICLAS_JIA_ADAPTIVE_SOLVER_ROOT=${PICLAS_JIA_ADAPTIVE_SOLVER_ROOT:-$HOME/piclas_projects/helium_jia_adaptive_vmpf}
PICLAS_RUNTIME_DIR=${PICLAS_RUNTIME_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/runtime/linux-x86_64}
PICLAS_MESH_ENV=${PICLAS_MESH_ENV:-$HOME/.local/share/piclas-project/pyhope}
