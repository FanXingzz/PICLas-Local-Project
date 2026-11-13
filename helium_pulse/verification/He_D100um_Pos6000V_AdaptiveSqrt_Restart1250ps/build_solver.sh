#!/usr/bin/env bash
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
project="$(cd "$here/../.." && pwd)"
source "$project/runtime-config.sh"
reference="$(dirname "$here")/He_D100um_Pos6000V_Optimized_Restart1250ps"
upstream="$PICLAS_UPSTREAM"
root="$PICLAS_JIA_ADAPTIVE_SOLVER_ROOT"
source="$root/source"
revision=514af4c6e5ec2a16f75db99295b34b08dfeced90

if ! git -C "$upstream" cat-file -e "$revision^{commit}" 2>/dev/null; then
    echo "Set PICLAS_UPSTREAM to a PICLas checkout containing $revision." >&2
    exit 2
fi
export PETSC_DIR="${PETSC_DIR:-$upstream/share/GNU-MPI/PETSc/linux-gnu-c}"
[[ -d "$PETSC_DIR/lib" ]] || {
    echo 'Set PETSC_DIR to the PETSc build with MPI, HYPRE and MUMPS.' >&2
    exit 2
}
mkdir -p "$root"
exec 9>"$root/build.lock"
flock 9
if [[ ! -d "$source/.git" ]]; then
    git clone --quiet --shared --no-checkout "$upstream" "$source"
    git -C "$source" checkout --quiet --detach "$revision"
fi
[[ "$(git -C "$source" rev-parse HEAD)" == "$revision" ]]
patch="$root/solver-source.patch"
if [[ ! -s "$patch" ]]; then
    if ! git -C "$source" diff --quiet -- HEAD; then
        echo "Unexpected source changes in $source. Use a fresh PICLAS_JIA_ADAPTIVE_SOLVER_ROOT." >&2
        exit 2
    fi
    git -C "$source" apply "$reference/optimized-source.patch"
    python3 -B "$here/patch_adaptive.py" "$source"
    git -C "$source" diff --binary HEAD > "$patch"
elif git -C "$source" apply --check "$patch" 2>/dev/null; then
    git -C "$source" apply "$patch"
fi
git -C "$source" diff --binary HEAD | cmp -s - "$patch" || {
    echo "Unexpected source changes in $source. Use a fresh PICLAS_JIA_ADAPTIVE_SOLVER_ROOT." >&2
    exit 2
}

rm -f -- "$here/solver-sha256.txt"
cmake -S "$source" -B "$root/build" -G Ninja -DCMAKE_BUILD_TYPE=Release \
    -DPICLAS_EQNSYSNAME=poisson -DPICLAS_TIMEDISCMETHOD=Leapfrog -DPICLAS_PARTICLES=ON -DPICLAS_LOADBALANCE=ON \
    -DHDF5_USE_STATIC_LIBRARIES=OFF -DHDF5_C_LIBRARY_hdf5=/usr/lib/x86_64-linux-gnu/hdf5/openmpi/libhdf5.so \
    -DHDF5_Fortran_LIBRARY_hdf5=/usr/lib/x86_64-linux-gnu/hdf5/openmpi/libhdf5.so \
    -DHDF5_Fortran_LIBRARY_hdf5_fortran=/usr/lib/x86_64-linux-gnu/hdf5/openmpi/libhdf5_fortran.so \
    -DLIBS_USE_MPI=ON -DLIBS_USE_PETSC=ON -DLIBS_BUILD_HDF5=OFF -DLIBS_BUILD_PETSC=OFF \
    -DPICLAS_IPO=OFF -DPICLAS_BUILD_POSTI=OFF -DPICLAS_CTAGS=OFF
cmake --build "$root/build" --parallel 6 --target piclas
cp "$patch" "$here/solver-source.patch"
sha256sum "$root/build/bin/piclas" "$root/build/lib/libpiclas.so" > "$here/solver-sha256.txt"
