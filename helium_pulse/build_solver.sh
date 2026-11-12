#!/usr/bin/env bash
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
source "$here/runtime-config.sh"
upstream="$PICLAS_UPSTREAM"
root="$PICLAS_SOLVER_ROOT"
if [[ ! -d "$upstream/.git" ]]; then
    echo 'Clone https://github.com/piclas-framework/piclas.git and set PICLAS_UPSTREAM to the checkout.' >&2
    exit 2
fi
mkdir -p "$root"
exec 9>"$root/build.lock"
flock 9
revision="$(git -C "$upstream" rev-parse '514af4c^{commit}')"
if [[ ! -d "$root/source/.git" ]]; then
    git clone --quiet --shared --no-checkout "$upstream" "$root/source"
    git -C "$root/source" checkout --quiet --detach "$revision"
fi
[[ "$(git -C "$root/source" rev-parse HEAD)" == "$revision" ]]
git -C "$root/source" restore src/equations/poisson/equation.f90
python3 "$here/solver/patch_solver.py" "$root/source"
python3 "$here/solver/patch_electrode_reflection.py" "$root/source"
python3 "$here/solver/patch_quartz_return_tracking.py" "$root/source"
python3 "$here/solver/patch_helium_ion_conversion.py" "$root/source"
python3 "$here/solver/patch_jia_chemistry.py" "$root/source"
export PETSC_DIR="${PETSC_DIR:-$upstream/share/GNU-MPI/PETSc/linux-gnu-c}"
[[ -d "$PETSC_DIR/lib" ]] || {
    echo 'Set PETSC_DIR to the PETSc build with MPI, HYPRE and MUMPS.' >&2
    exit 2
}
cmake -S "$root/source" -B "$root/build" -G Ninja -DCMAKE_BUILD_TYPE=Release \
    -DPICLAS_EQNSYSNAME=poisson -DPICLAS_TIMEDISCMETHOD=Leapfrog -DPICLAS_PARTICLES=ON \
    -DHDF5_USE_STATIC_LIBRARIES=OFF -DHDF5_C_LIBRARY_hdf5=/usr/lib/x86_64-linux-gnu/hdf5/openmpi/libhdf5.so \
    -DHDF5_Fortran_LIBRARY_hdf5=/usr/lib/x86_64-linux-gnu/hdf5/openmpi/libhdf5.so \
    -DHDF5_Fortran_LIBRARY_hdf5_fortran=/usr/lib/x86_64-linux-gnu/hdf5/openmpi/libhdf5_fortran.so \
    -DLIBS_USE_MPI=ON -DLIBS_USE_PETSC=ON -DLIBS_BUILD_HDF5=OFF -DLIBS_BUILD_PETSC=OFF \
    -DPICLAS_IPO=OFF -DPICLAS_BUILD_POSTI=OFF -DPICLAS_CTAGS=OFF
cmake --build "$root/build" --parallel 6 --target piclas
