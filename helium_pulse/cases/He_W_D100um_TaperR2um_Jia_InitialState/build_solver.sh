#!/usr/bin/env bash
set -euo pipefail

case_dir="$(cd "$(dirname "$0")" && pwd)"
upstream=${PICLAS_UPSTREAM:-$HOME/piclas}
root=${PICLAS_JIA_INITIAL_SOLVER_ROOT:-$HOME/piclas_projects/helium_jia_initial_state_workspace}
source="$root/source"
revision=514af4c6e5ec2a16f75db99295b34b08dfeced90
patch="$case_dir/solver-source.patch"

mkdir -p "$root"
exec 9>"$root/build.lock"
flock 9
if [[ ! -d "$source/.git" ]]; then
    git clone --quiet --shared --no-checkout "$upstream" "$source"
    git -C "$source" checkout --quiet --detach "$revision"
fi
[[ "$(git -C "$source" rev-parse HEAD)" == "$revision" ]] || {
    echo "Unexpected PICLas source revision in $source" >&2
    exit 2
}
if git -C "$source" apply --check "$patch" 2>/dev/null; then
    git -C "$source" apply "$patch"
else
    git -C "$source" apply --reverse --check "$patch"
fi

export PETSC_DIR="${PETSC_DIR:-$upstream/share/GNU-MPI/PETSc/linux-gnu-c}"
cmake -S "$source" -B "$root/build" -G Ninja -DCMAKE_BUILD_TYPE=Release \
    -DPICLAS_EQNSYSNAME=poisson -DPICLAS_TIMEDISCMETHOD=Leapfrog -DPICLAS_PARTICLES=ON \
    -DHDF5_USE_STATIC_LIBRARIES=OFF -DHDF5_C_LIBRARY_hdf5=/usr/lib/x86_64-linux-gnu/hdf5/openmpi/libhdf5.so \
    -DHDF5_Fortran_LIBRARY_hdf5=/usr/lib/x86_64-linux-gnu/hdf5/openmpi/libhdf5.so \
    -DHDF5_Fortran_LIBRARY_hdf5_fortran=/usr/lib/x86_64-linux-gnu/hdf5/openmpi/libhdf5_fortran.so \
    -DLIBS_USE_MPI=ON -DLIBS_USE_PETSC=ON -DLIBS_BUILD_HDF5=OFF -DLIBS_BUILD_PETSC=OFF \
    -DPICLAS_IPO=OFF -DPICLAS_BUILD_POSTI=OFF -DPICLAS_CTAGS=OFF
cmake --build "$root/build" --parallel 6 --target piclas
printf 'Solver: %s\n' "$root/build/bin/piclas"
