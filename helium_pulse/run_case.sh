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
    default) solver_root="$PICLAS_SOLVER_ROOT" ;;
    jia_initial_state) solver_root="$PICLAS_JIA_DYNAMIC_SOLVER_ROOT" ;;
    *) echo "Unknown solver profile: $solver_profile" >&2; exit 2 ;;
esac
solver="$solver_root/build/bin/piclas"
solver_lib="$solver_root/build/lib/libpiclas.so"
prebuilt=0
if [[ "$solver_profile" == default && ! -x "$solver" ]]; then
    solver="$PICLAS_RUNTIME_DIR/solver/bin/piclas"
    solver_lib="$PICLAS_RUNTIME_DIR/solver/lib/libpiclas.so"
    export LD_LIBRARY_PATH="$PICLAS_RUNTIME_DIR/solver/lib:$PICLAS_RUNTIME_DIR/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    prebuilt=1
fi
data="$PICLAS_RUNTIME_DIR/collision-data"
if [[ ! -d "$data" ]]; then
    data="$PICLAS_UPSTREAM/regressioncheck/NIG_Reservoir_single_core/CHEM_RATES_XSec_Chem_Elec-He-e"
fi
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 BLIS_NUM_THREADS=1
if [[ ! -s "$case_dir/helium_mesh.h5" ]]; then
    echo "Generate the case mesh or restore helium_mesh.h5 from the matching data bundle: $case_dir" >&2
    exit 2
fi
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
if (( ! prebuilt )); then
    [[ -f "$solver_root/build.lock" ]] || {
        echo "Build the selected solver first: $solver_profile" >&2
        exit 2
    }
    exec 7<"$solver_root/build.lock"
    flock -sn 7 || { echo 'The selected solver is being built.' >&2; exit 2; }
fi
if [[ "$solver_profile" == jia_initial_state ]]; then
    bash "$here/solver/jia_dynamic/build_solver.sh" --verify
fi
[[ -x "$solver" && -f "$solver_lib" ]] || {
    echo "Build the selected solver or extract its supported runtime bundle: $solver_profile" >&2
    exit 2
}
parameter_lock=
run=
solver_complete=0
cleanup() {
    local result=$?
    if [[ -n "$run" ]]; then
        if (( solver_complete )); then
            printf 'complete\n' > "$run/run-status.txt"
        elif (( result != 0 )); then
            printf 'failed\n' > "$run/solver-status.txt"
            printf 'failed\n' > "$run/run-status.txt"
        fi
    fi
    if [[ -n "$parameter_lock" ]]; then
        rmdir -- "$parameter_lock"
    fi
}
trap cleanup EXIT
if [[ "$solver_profile" == jia_initial_state ]]; then
    mkdir -- "$case_dir/.parameters.lock" || { echo "This case is saving parameters. Try again shortly."; exit 2; }
    parameter_lock="$case_dir/.parameters.lock"
fi
mkdir -p "$case_dir/runs"
run="$(mktemp -d "$case_dir/runs/$(date +%Y%m%d-%H%M%S)-$mode-XXXXXX")"
printf "running\n" > "$run/run-status.txt"
printf "pending\n" > "$run/solver-status.txt"
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
if [[ "$mode" != research ]]; then
    python3 -B - "$here" "$mode" <<'PY'
from pathlib import Path
import sys

sys.path.insert(0, sys.argv[1])
from piclas_ini import parse_parameters, replace_parameters

path = Path("parameter.ini")
text = path.read_text(encoding="utf-8-sig")
mode = sys.argv[2]
if mode == "smoke":
    changes = {"tend": "6.e-12", "Analyze_dt": "1.e-12",
               "PulseRise": "2.e-12", "PulseFlat": "2.e-12", "PulseFall": "2.e-12"}
elif mode == "pilot":
    changes = {"tend": "6.e-12", "Analyze_dt": "2.e-12"}
else:
    # Sample multiple time steps on the 1 V plateau without initial plasma.
    changes = {"tend": "4.e-13", "Analyze_dt": "4.e-13", "ManualTimeStep": "1.e-13",
               "PulsePeak": "1.", "PulseRise": "1.e-13", "PulseFlat": "1.e-12", "PulseFall": "1.e-13"}
    parameters = parse_parameters(text)
    for species in range(2, 7):
        key = f"Part-Species{species}-nInits"
        if key in parameters:
            changes[key] = 0
path.write_text(replace_parameters(text, changes), encoding="utf-8", newline="\n")
PY
fi
if [[ "$solver_profile" == jia_initial_state ]]; then
    python3 -B "$here/solver/jia_dynamic/configure_run.py" "$run" "$rank" "$mode"
fi
bash "$here/convert_results.sh" --prepare
for input in parameter.ini DSMC.ini geometry.json helium_mesh.h5 XSec_Database_He_Plasma.h5 Electronic-State-Database.h5 CHEMISTRY_PLAN.json visualization.ini; do
    if [[ -f "$input" ]]; then sha256sum "$input"; fi
done > input-sha256.txt
printf 'RUN_DIRECTORY=%s\n' "$run"
printf 'mode=%s\nmpi_ranks=%s\nsolver_profile=%s\n' "$mode" "$rank" "$solver_profile" > run-info.txt
printf 'OMP_NUM_THREADS=%s\nOPENBLAS_NUM_THREADS=%s\nMKL_NUM_THREADS=%s\n' \
    "$OMP_NUM_THREADS" "$OPENBLAS_NUM_THREADS" "$MKL_NUM_THREADS" >> run-info.txt
sha256sum "$solver" "$solver_lib" > solver-sha256.txt
if [[ "$solver_profile" == jia_initial_state ]]; then
    printf 'solver_variant=jia_dynamic\n' >> run-info.txt
    cp "$solver_root/"{solver-build-inputs.txt,solver-source.patch} .
    printf 'solver_build_inputs_sha256=%s\n' "$(sha256sum solver-build-inputs.txt | cut -d' ' -f1)" >> run-info.txt
    python3 -B "$here/record_model_settings.py" "$run"
elif (( prebuilt )); then
    cp "$PICLAS_RUNTIME_DIR/solver-source.patch" solver-source.patch
else
    git -C "$solver_root/source" diff --binary > solver-source.patch
fi
printf 'running\n' > solver-status.txt
mpirun -np "$rank" "$solver" parameter.ini DSMC.ini 2>&1 | tee solver.log
if ! grep -qF 'PICLAS FINISHED!' solver.log; then
    echo 'The solver exited without its completion message. See solver.log.' >&2
    exit 1
fi
solver_complete=1
printf 'complete\n' > solver-status.txt
if ! bash "$here/convert_results.sh"; then
    echo 'PICLas finished and HDF5 results are available. VTU export failed. See conversion.log.' >&2
fi
python3 "$here/record_model_settings.py" "$case_dir" "$run"
