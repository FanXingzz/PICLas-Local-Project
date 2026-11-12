#!/usr/bin/env bash
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
source "$here/runtime-config.sh"
rank="${1:-6}"
mode="${2:-research}"
case_dir="${3:-$here}"
case_dir="$(cd "$case_dir" && pwd)"
[[ "$rank" =~ ^[1-6]$ ]] || { echo "MPI ranks must be 1 through 6"; exit 2; }
[[ "$mode" == research || "$mode" == smoke || "$mode" == pilot || "$mode" == field-check ]] || exit 2
solver_profile=default
if [[ -f "$case_dir/case-info.json" ]]; then
    solver_profile="$(python3 - "$case_dir/case-info.json" "$mode" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8-sig") as stream:
    info = json.load(stream)
if info.get("network_status") == "draft":
    sys.exit("The staged reaction network is not connected to the solver.")
if sys.argv[2] == "research" and info.get("review_pending"):
    sys.exit("This case is awaiting review before a full pulse.")
print(info.get("solver_profile", "default"))
PY
)"
fi
case "$solver_profile" in
    default) root="$PICLAS_SOLVER_ROOT" ;;
    jia_initial_state) root="$PICLAS_JIA_INITIAL_SOLVER_ROOT" ;;
    *) echo "Unknown solver profile: $solver_profile" >&2; exit 2 ;;
esac
solver="$root/build/bin/piclas"
solver_lib="$root/build/lib/libpiclas.so"
data="$PICLAS_RUNTIME_DIR/collision-data"
if [[ "$solver_profile" == default && ! -x "$solver" ]]; then
    solver="$PICLAS_RUNTIME_DIR/solver/bin/piclas"
    solver_lib="$PICLAS_RUNTIME_DIR/solver/lib/libpiclas.so"
    export LD_LIBRARY_PATH="$PICLAS_RUNTIME_DIR/solver/lib:$PICLAS_RUNTIME_DIR/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
if [[ ! -d "$data" ]]; then
    data="$PICLAS_UPSTREAM/regressioncheck/NIG_Reservoir_single_core/CHEM_RATES_XSec_Chem_Elec-He-e"
fi
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 BLIS_NUM_THREADS=1
if [[ "$solver_profile" == jia_initial_state && ! -x "$solver" ]]; then
    echo 'Compile the Jia initial-state solver with bash helium_pulse/cases/He_W_D100um_TaperR2um_Jia_InitialState/build_solver.sh.' >&2
    exit 2
fi
[[ -x "$solver" ]] || { echo 'Extract the Linux runtime bundle or compile the solver.' >&2; exit 2; }
test -s "$case_dir/helium_mesh.h5"
if [[ "$case_dir" != "$here" ]]; then
    exec 8>"$case_dir/mesh.lock"
    flock -n 8 || { echo "This case is already meshing or running."; exit 2; }
    cmp -s "$case_dir/geometry.json" "$case_dir/mesh-geometry.json" || {
        echo "Generate a mesh for this geometry before running."
        exit 2
    }
fi
mkdir -p "$PICLAS_SOLVER_ROOT"
exec 9>"$PICLAS_SOLVER_ROOT/run.lock"
flock -n 9 || { echo "Another helium run is active."; exit 2; }
parameter_lock=
run=
cleanup() {
    local result=$?
    if [[ -n "$run" && "$result" -ne 0 ]]; then
        printf "failed\n" > "$run/run-status.txt"
    fi
    if [[ -n "$parameter_lock" ]]; then
        rmdir -- "$parameter_lock"
    fi
}
trap cleanup EXIT
if [[ "$solver_profile" == jia_initial_state ]]; then
    lock="$case_dir/.parameters.lock"
    mkdir -- "$lock" || { echo "This case is saving parameters. Try again shortly."; exit 2; }
    parameter_lock="$lock"
fi
mkdir -p "$case_dir/runs"
run="$(mktemp -d "$case_dir/runs/$(date +%Y%m%d-%H%M%S)-$mode-XXXXXX")"
printf "running\n" > "$run/run-status.txt"
cp "$case_dir/parameter.ini" "$case_dir/DSMC.ini" "$case_dir/geometry.json" "$case_dir/helium_mesh.h5" "$run/"
for info in case-info.json literature-review.txt REACTIONS.md review-checks.json CHEMISTRY_PLAN.json R15_SOURCE_REVIEW.md SOLVER_SETUP.md; do
    if [[ -f "$case_dir/$info" ]]; then cp "$case_dir/$info" "$run/"; fi
done
for database in XSec_Database_He_Plasma.h5 Electronic-State-Database.h5; do
    if [[ -f "$case_dir/$database" ]]; then
        cp "$case_dir/$database" "$run/"
    else
        cp "$data/$database" "$run/"
    fi
done
if [[ -n "$parameter_lock" ]]; then
    rmdir -- "$parameter_lock"
    parameter_lock=
fi
cd "$run"
if [[ "$mode" == smoke ]]; then
    sed -i -E 's/^(tend|PulseRise|PulseFlat|PulseFall) = .*/\1 = 2.e-12/; s/^tend = .*/tend = 6.e-12/; s/^Analyze_dt = .*/Analyze_dt = 1.e-12/' parameter.ini
elif [[ "$mode" == pilot ]]; then
    sed -i -E 's/^tend = .*/tend = 6.e-12/; s/^Analyze_dt = .*/Analyze_dt = 2.e-12/' parameter.ini
elif [[ "$mode" == field-check ]]; then
    # Allow multiple steps on the 1 V plateau before sampling the field.
    sed -i -E 's/^tend = .*/tend = 4.e-13/; s/^Analyze_dt = .*/Analyze_dt = 4.e-13/; s/^ManualTimeStep = .*/ManualTimeStep = 1.e-13/;
               s/^PulsePeak = .*/PulsePeak = 1./; s/^PulseRise = .*/PulseRise = 1.e-13/;
               s/^PulseFlat = .*/PulseFlat = 1.e-12/; s/^PulseFall = .*/PulseFall = 1.e-13/;
               s/^(Part-Species[2-6]-nInits) = .*/\1 = 0/' parameter.ini
fi
for input in parameter.ini DSMC.ini geometry.json helium_mesh.h5 XSec_Database_He_Plasma.h5 Electronic-State-Database.h5 CHEMISTRY_PLAN.json; do
    if [[ -f "$input" ]]; then sha256sum "$input"; fi
done > input-sha256.txt
printf 'RUN_DIRECTORY=%s\n' "$run"
printf 'mode=%s\nmpi_ranks=%s\nsolver_profile=%s\n' "$mode" "$rank" "$solver_profile" > run-info.txt
printf 'OMP_NUM_THREADS=%s\nOPENBLAS_NUM_THREADS=%s\nMKL_NUM_THREADS=%s\n' \
    "$OMP_NUM_THREADS" "$OPENBLAS_NUM_THREADS" "$MKL_NUM_THREADS" >> run-info.txt
sha256sum "$solver" "$solver_lib" > solver-sha256.txt
if [[ "$solver" == "$root/build/bin/piclas" ]]; then
    git -C "$root/source" diff --binary > solver-source.patch
else
    cp "$PICLAS_RUNTIME_DIR/solver-source.patch" solver-source.patch
fi
mpirun -np "$rank" "$solver" parameter.ini DSMC.ini 2>&1 | tee solver.log
bash "$here/convert_results.sh" 2>&1 | tee conversion.log
python3 "$here/record_model_settings.py" "$case_dir" "$run"
printf "complete\n" > run-status.txt
