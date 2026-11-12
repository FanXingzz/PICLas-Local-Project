#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")" && pwd)"
for case in electron_absorb_p0 electron_reflect_p1 ion_emit_gamma1; do
  bash "$root/run_case.sh" 6 pilot "$root/verification/$case" > "$root/verification/$case/verification-launch.log" 2>&1
done
