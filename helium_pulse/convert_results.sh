#!/usr/bin/env bash
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
source "$here/runtime-config.sh"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 BLIS_NUM_THREADS=1

prepare=0
if [[ "${1:-}" == --prepare ]]; then
    prepare=1
    shift
fi
if (( $# > 1 )); then
    echo 'Usage: convert_results.sh [--prepare] [run-directory]' >&2
    exit 2
fi
if (( $# == 1 )); then cd -- "$1"; fi

post_options='nvisu nvisuadd nodetypevisu visuparticles visuadaptiveinfo convertpointtocelldata dmdsinglemodeoutput dmdmaximummodeoutput'
shared_options='timestamplength meshcheckweirdelements meshfile usecurveds meshscale meshdeform meshcheckref calcmeshinfo readfemconnectivity crossproductmetrics boundaryname boundarytype padaptiontype padaptionbclevel gatheredwrite usecollectiveio n nmax nanalyze coloredoutput'

# Use a separate INI so solver settings do not become unknown VTU options.
write_visualization_ini() {
    awk -F '=' -v options="$post_options $shared_options" '
        BEGIN {
            count = split(options, names, " ")
            for (i = 1; i <= count; ++i) allowed[names[i]] = 1
        }
        NF >= 2 {
            key = tolower($1)
            sub(/^[[:space:]]+/, "", key)
            sub(/[[:space:]]+$/, "", key)
            if (key == "nvisu") has_nvisu = 1
            if (key in allowed) print
        }
        END { if (!has_nvisu) print "NVisu = 2" }
    ' parameter.ini > visualization.ini.tmp
    mv -- visualization.ini.tmp visualization.ini
}

if (( prepare )); then
    write_visualization_ini
    # Remove postprocessing-only settings from the copied solver input.
    awk -F '=' -v options="$post_options" '
        BEGIN {
            count = split(options, names, " ")
            for (i = 1; i <= count; ++i) post[names[i]] = 1
        }
        {
            key = tolower($1)
            sub(/^[[:space:]]+/, "", key)
            sub(/[[:space:]]+$/, "", key)
            if (NF < 2 || !(key in post)) print
        }
    ' parameter.ini > parameter.ini.tmp
    mv -- parameter.ini.tmp parameter.ini
    exit 0
fi

exec 6>conversion.lock
flock -n 6 || { echo 'VTU export is already running.' >&2; exit 2; }
printf 'running\n' > conversion-status.txt
finish_conversion() {
    if [[ $? == 0 ]]; then
        printf 'complete\n' > conversion-status.txt
    else
        printf 'failed\n' > conversion-status.txt
    fi
}
trap finish_conversion EXIT
exec > >(tee -a conversion.log) 2>&1

if [[ ! -f visualization.ini ]]; then write_visualization_ini; fi
vtk="${PICLAS2VTK:-${PICLAS_VTK_BIN:-}}"
bundled_vtk="$PICLAS_RUNTIME_DIR/vtk/bin/piclas2vtk"
if [[ -z "$vtk" ]]; then
    if [[ -x "$bundled_vtk" ]]; then
        vtk="$bundled_vtk"
    elif [[ -x "$PICLAS_UPSTREAM/build_poisson_Ninja/bin/piclas2vtk" ]]; then
        vtk="$PICLAS_UPSTREAM/build_poisson_Ninja/bin/piclas2vtk"
    else
        vtk=piclas2vtk
    fi
fi
if [[ "$vtk" == "$bundled_vtk" ]]; then
    export LD_LIBRARY_PATH="$PICLAS_RUNTIME_DIR/vtk/lib:$PICLAS_RUNTIME_DIR/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
command -v -- "$vtk" >/dev/null || {
    echo "VTU converter not found: $vtk. Extract the runtime bundle or set PICLAS_VTK_BIN." >&2
    exit 2
}
printf 'VTU converter: %s\n' "$(command -v -- "$vtk")"
shopt -s nullglob
states=(*_State_*.h5)
if (( ${#states[@]} == 0 )); then
    echo 'No HDF5 state files are available for VTU export.' >&2
    exit 2
fi
for file in "${states[@]}"; do
    project="${file%_State_*}"
    stamp="${file##*_State_}"
    stamp="${stamp%.h5}"
    solution="${project}_Solution_$stamp.vtu"
    elements="${project}_Solution_ElemData_$stamp.vtu"
    if [[ ! -s "$solution" || ! -s "$elements" ]]; then
        "$vtk" visualization.ini "$file"
        if [[ ! -s "$solution" || ! -s "$elements" ]]; then
            echo "Expected VTU outputs were not created for $file." >&2
            exit 2
        fi
    fi
done
printf 'VTU export complete for %s HDF5 state files.\n' "${#states[@]}"
