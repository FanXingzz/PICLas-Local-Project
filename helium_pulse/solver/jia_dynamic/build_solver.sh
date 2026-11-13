#!/usr/bin/env bash
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
project="$(cd "$here/../.." && pwd)"
source "$project/runtime-config.sh"
reference=verification/He_D100um_Pos6000V_Optimized_Restart1250ps/inputs/baseline-source.patch
adaptive=verification/He_D100um_Pos6000V_AdaptiveSqrt_Restart1250ps/patch_adaptive.py
full_run=solver/jia_dynamic/patch_full_run.py
inputs=(solver/jia_dynamic/build_solver.sh "$reference" "$adaptive" "${adaptive%/*}/adaptive_vmpf.f90" "$full_run")
upstream="$PICLAS_UPSTREAM"
root="$PICLAS_JIA_DYNAMIC_SOLVER_ROOT"
source="$root/source"
revision=514af4c6e5ec2a16f75db99295b34b08dfeced90
build_inputs="$root/solver-build-inputs.txt"
source_patch="$root/solver-source.patch"
artifacts="$root/solver-sha256.txt"
binary="$root/build/bin/piclas"
library="$root/build/lib/libpiclas.so"

input_manifest() (
    cd "$1"
    printf 'revision=%s\n' "$revision"
    sha256sum -- "${inputs[@]}"
)

source_diff() {
    git -C "$1" diff --no-ext-diff --no-textconv --no-color --binary HEAD
}

source_matches() {
    local head untracked
    head="$(git -C "$source" rev-parse HEAD)" || return
    untracked="$(git -C "$source" ls-files --others --exclude-standard)" || return
    [[ "$head" == "$revision" && -z "$untracked" ]] && source_diff "$source" | cmp -s - "$1"
}

artifacts_match() {
    [[ -x "$binary" && -f "$library" && -f "$artifacts" ]] &&
        sha256sum -- "$binary" "$library" | cmp -s - "$artifacts"
}

if [[ "${1:-}" == --verify && $# == 1 ]]; then
    if [[ ! -f "$root/build.lock" ]]; then
        echo 'Build the Jia dynamic solver in VS Code before running this case.' >&2
        exit 2
    fi
    exec 9<"$root/build.lock"
    flock -sn 9 || { echo 'The Jia dynamic solver is being built.' >&2; exit 2; }
    if ! input_manifest "$project" | cmp -s - "$build_inputs" ||
        ! source_matches "$source_patch" || ! artifacts_match; then
        echo 'The Jia dynamic solver is out of date or its build cannot be verified. Rebuild it in VS Code before running this case.' >&2
        exit 2
    fi
    exit 0
fi
if (( $# != 0 )); then
    echo "Usage: $0 [--verify]" >&2
    exit 2
fi
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
staged="$(mktemp -d "$root/.build-XXXXXX")"
trap 'rm -rf -- "$staged"' EXIT
input_manifest "$project" > "$staged/solver-build-inputs.txt"
if [[ -d "$source/.git" ]] && cmp -s "$staged/solver-build-inputs.txt" "$build_inputs" &&
    source_matches "$source_patch"; then
    cp -- "$source_patch" "$staged/solver-source.patch"
else
    mkdir -- "$staged/inputs"
    (cd "$project"; cp --parents -- "${inputs[@]}" "$staged/inputs")
    input_manifest "$staged/inputs" | cmp -s - "$staged/solver-build-inputs.txt" || {
        echo 'Jia solver inputs changed while taking the build snapshot. Retry the build.' >&2
        exit 2
    }
    git clone --quiet --shared --no-checkout "$upstream" "$staged/source"
    git -C "$staged/source" checkout --quiet --detach "$revision"
    git -C "$staged/source" apply "$staged/inputs/$reference"
    python3 -B "$staged/inputs/$adaptive" "$staged/source"
    python3 -B "$staged/inputs/$full_run" "$staged/source"
    git -C "$staged/source" add --intent-to-add -- .
    source_diff "$staged/source" > "$staged/solver-source.patch"
    if [[ ! -d "$source/.git" ]] || ! source_matches "$staged/solver-source.patch"; then
        rm -f -- "$build_inputs"
        if [[ -e "$source" ]]; then
            mv -T -- "$source" "$staged/previous-source"
        fi
        if ! mv -T -- "$staged/source" "$source"; then
            if [[ -e "$staged/previous-source" ]]; then
                mv -T -- "$staged/previous-source" "$source"
            fi
            exit 2
        fi
    fi
fi

# A build is eligible for new runs only once the receipts below have been published.
rm -f -- "$build_inputs"
if ! artifacts_match; then
    rm -f -- "$binary" "$library"
fi

cmake -S "$source" -B "$root/build" -G Ninja -DCMAKE_BUILD_TYPE=Release \
    -DPICLAS_EQNSYSNAME=poisson -DPICLAS_TIMEDISCMETHOD=Leapfrog -DPICLAS_PARTICLES=ON -DPICLAS_LOADBALANCE=ON \
    -DHDF5_USE_STATIC_LIBRARIES=OFF -DHDF5_C_LIBRARY_hdf5=/usr/lib/x86_64-linux-gnu/hdf5/openmpi/libhdf5.so \
    -DHDF5_Fortran_LIBRARY_hdf5=/usr/lib/x86_64-linux-gnu/hdf5/openmpi/libhdf5.so \
    -DHDF5_Fortran_LIBRARY_hdf5_fortran=/usr/lib/x86_64-linux-gnu/hdf5/openmpi/libhdf5_fortran.so \
    -DLIBS_USE_MPI=ON -DLIBS_USE_PETSC=ON -DLIBS_BUILD_HDF5=OFF -DLIBS_BUILD_PETSC=OFF \
    -DPICLAS_IPO=OFF -DPICLAS_BUILD_POSTI=OFF -DPICLAS_CTAGS=OFF
cmake --build "$root/build" --parallel 4 --target piclas
input_manifest "$project" | cmp -s - "$staged/solver-build-inputs.txt" &&
    source_matches "$staged/solver-source.patch" || {
    echo 'Jia solver inputs or source changed during compilation. Rebuild before running.' >&2
    exit 2
}
sha256sum -- "$binary" "$library" > "$staged/solver-sha256.txt"
mv -f -- "$staged/solver-source.patch" "$source_patch"
mv -f -- "$staged/solver-sha256.txt" "$artifacts"
mv -f -- "$staged/solver-build-inputs.txt" "$build_inputs"
printf 'Jia dynamic solver build inputs: '
sha256sum -- "$build_inputs"
