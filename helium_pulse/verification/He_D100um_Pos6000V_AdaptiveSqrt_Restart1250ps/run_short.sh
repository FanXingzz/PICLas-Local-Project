#!/usr/bin/env bash
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
project="$(cd "$here/../.." && pwd)"
source "$project/runtime-config.sh"
reference="${PICLAS_JIA_VALIDATION_REFERENCE:-$(dirname "$here")/He_D100um_Pos6000V_Optimized_Restart1250ps}"
root="$PICLAS_JIA_ADAPTIVE_SOLVER_ROOT"
solver="$root/build/bin/piclas"
checkpoint=helium_pulse_State_000.00000000125000.h5
project_lock="$PICLAS_SOLVER_ROOT/run.lock"
mode=adaptive
if [[ $# -ne 0 ]]; then
    if [[ $# -eq 1 && "$1" == --fixed-control ]]; then
        mode=fixed-control
    elif [[ $# -eq 2 && "$1" == --settings-from && -f "$2/settings.json" ]]; then
        mode=repeat
        set -- "$1" "$(cd "$2" && pwd)"
    else
        echo 'Usage: run_short.sh [--fixed-control | --settings-from RUN_DIRECTORY]' >&2
        exit 2
    fi
fi

[[ -s "$reference/inputs/$checkpoint" ]] || {
    echo 'The 1.25 ns checkpoint is missing. Set PICLAS_JIA_VALIDATION_REFERENCE to the archived benchmark directory.' >&2
    exit 2
}
reference="$(cd "$reference" && pwd)"
[[ -x "$solver" && -f "$root/build.lock" && -s "$here/solver-sha256.txt" ]] || {
    echo "Build the experimental adaptive solver with $here/build_solver.sh first." >&2
    exit 2
}
mkdir -p "$PICLAS_SOLVER_ROOT"
exec 9>"$project_lock"
flock -n 9 || { echo 'A helium run is still using the six-rank slot.' >&2; exit 2; }
exec 7<"$root/build.lock"
flock -sn 7 || { echo 'The experimental adaptive solver is being built.' >&2; exit 2; }
( cd "$reference/inputs"; sha256sum -c input-sha256.txt )
( cd "$reference"; sha256sum -c parameter-sha256.txt )
sha256sum "$solver" "$root/build/lib/libpiclas.so" | cmp -s - "$here/solver-sha256.txt" || {
    echo "Rebuild the experimental adaptive solver in $root to refresh its checksum." >&2
    exit 2
}
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 BLIS_NUM_THREADS=1

mkdir -p "$here/runs"
run="$(mktemp -d "$here/runs/$(date +%Y%m%d-%H%M%S)-$mode-XXXXXX")"
cd "$run"
printf 'running\n' > run-status.txt
trap 'if [[ $? -ne 0 ]]; then printf "failed\n" > run-status.txt; fi' EXIT
printf 'mode=%s\nmpi_ranks=6\nrestart_time_ns=1.25\nend_time_ns=1.275\n' "$mode" > run-info.txt
python3 -B "$here/prepare_run.py" "$run" --reference "$reference" "$@"
cp "$here/solver-source.patch" "$here/solver-sha256.txt" .
sha256sum parameter.ini DSMC.ini CHEMISTRY_PLAN.json geometry.json settings.json reference-populations.json *.h5 > input-sha256.txt
printf 'RUN_DIRECTORY=%s\n' "$run"
started="$(date +%s%N)"
mpirun -np 6 "$solver" parameter.ini DSMC.ini "$checkpoint" 2>&1 | tee solver.log
if ! grep -qF 'PICLAS FINISHED!' solver.log; then
    echo 'The solver exited without its completion message. See solver.log.' >&2
    exit 1
fi
finished="$(date +%s%N)"
printf '%s\n' "$((finished-started))" > wall-time-ns.txt
printf 'complete\n' > run-status.txt
