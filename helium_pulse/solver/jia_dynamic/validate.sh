#!/usr/bin/env bash
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
project="$(cd "$here/../.." && pwd)"
source "$project/runtime-config.sh"
reference="${PICLAS_JIA_VALIDATION_REFERENCE:-$project/verification/He_D100um_Pos6000V_Optimized_Restart1250ps}"
original="$project/cases/He_W_D100um_TaperR2um_Jia_InitialState"
solver_root="$PICLAS_JIA_DYNAMIC_SOLVER_ROOT"
solver="$solver_root/build/bin/piclas"
project_lock="$PICLAS_SOLVER_ROOT/run.lock"
checkpoint=helium_pulse_State_000.00000000125000.h5
output="${PICLAS_JIA_VALIDATION_OUTPUT:-$project/verification/He_D100um_Jia_Dynamic_Validation}"
cold_only=0
if [[ $# == 1 && "$1" == --cold-only ]]; then
    cold_only=1
elif (( $# != 0 )); then
    echo "Usage: $0 [--cold-only]" >&2
    exit 2
fi
if [[ ! -s "$original/helium_mesh.h5" ]]; then
    echo "Restore the Jia initial-state mesh or generate it before validation: $original" >&2
    exit 2
fi
if (( ! cold_only )); then
    if [[ ! -s "$reference/inputs/$checkpoint" ]]; then
        echo 'The 1.25 ns checkpoint is missing. Set PICLAS_JIA_VALIDATION_REFERENCE to the archived benchmark directory or use --cold-only.' >&2
        exit 2
    fi
    reference="$(cd "$reference" && pwd)"
fi

mkdir -p "$output"
batch="$(mktemp -d "$output/$(date +%Y%m%d-%H%M%S)-dynamic-XXXXXX")"
printf 'VALIDATION_BATCH=%s\n' "$batch"
mkdir "$batch/cold"
cp "$original/"{parameter.ini,DSMC.ini,geometry.json,mesh-geometry.json,case-info.json,helium_mesh.h5,CHEMISTRY_PLAN.json,R15_SOURCE_REVIEW.md,SOLVER_SETUP.md} "$batch/cold/"
for database in Electronic-State-Database.h5 XSec_Database_He_Plasma.h5; do
    if [[ -s "$original/$database" ]]; then cp "$original/$database" "$batch/cold/"; fi
done
bash "$project/run_case.sh" 6 pilot "$batch/cold" > "$batch/cold/launch.log" 2>&1
printf 'COLD_VALIDATION_COMPLETE\n'
if (( cold_only )); then exit 0; fi

exec 9<"$project_lock"
flock -n 9 || { echo 'Another helium run is active.' >&2; exit 2; }
exec 7<"$solver_root/build.lock"
flock -sn 7 || { echo 'The Jia dynamic solver is being built.' >&2; exit 2; }
( cd "$reference/inputs"; sha256sum -c input-sha256.txt )
( cd "$reference"; sha256sum -c parameter-sha256.txt )
bash "$here/build_solver.sh" --verify
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 BLIS_NUM_THREADS=1

mkdir "$batch/hot"
cd "$batch/hot"
printf 'running\n' > run-status.txt
trap 'if [[ $? -ne 0 ]]; then printf "failed\n" > run-status.txt; fi' EXIT
cp "$reference/baseline/parameter.ini" .
cp "$reference/inputs/"{DSMC.ini,geometry.json,case-info.json,CHEMISTRY_PLAN.json,helium_mesh.h5,Electronic-State-Database.h5,XSec_Database_He_Plasma.h5,R15_SOURCE_REVIEW.md,"$checkpoint"} .
python3 -B "$here/configure_run.py" "$PWD" 6 research
cp "$solver_root/"{solver-source.patch,solver-sha256.txt,solver-build-inputs.txt} .
sha256sum parameter.ini DSMC.ini CHEMISTRY_PLAN.json geometry.json *.h5 > input-sha256.txt
printf 'mode=checkpoint-validation\nmpi_ranks=6\nrestart_time_ns=1.25\nend_time_ns=1.275\nsolver_profile=jia_initial_state\nsolver_variant=jia_dynamic\n' > run-info.txt
printf 'solver_build_inputs_sha256=%s\n' "$(sha256sum solver-build-inputs.txt | cut -d' ' -f1)" >> run-info.txt
python3 -B "$project/record_model_settings.py" "$PWD" >/dev/null
started="$(date +%s%N)"
mpirun -np 6 "$solver" parameter.ini DSMC.ini "$checkpoint" > solver.log 2>&1
if ! grep -qF 'PICLAS FINISHED!' solver.log; then
    echo 'The solver exited without its completion message. See solver.log.' >&2
    exit 1
fi
finished="$(date +%s%N)"
printf '%s\n' "$((finished-started))" > wall-time-ns.txt
python3 -B "$project/record_model_settings.py" "$PWD" >/dev/null
printf 'complete\n' > run-status.txt
printf 'HOT_VALIDATION_COMPLETE\n'
