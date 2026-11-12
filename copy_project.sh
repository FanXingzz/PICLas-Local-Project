#!/bin/bash
set -e

SRC="${1:-$HOME/piclas_projects/official_streamer/pic-mcc}"
DST="$(cd "$(dirname "$0")" && pwd)/official_streamer/pic-mcc"

echo "========== ?????? =========="
test -d "$SRC"

echo "========== ??Windows???? =========="
mkdir -p "$DST"

echo "========== ????????? =========="
cp -rL "$SRC/." "$DST/"

echo "========== ?????? =========="
ls -lh "$DST/parameter.ini"
ls -lh "$DST/DSMC.ini"
ls -lh "$DST/streamer_mesh.h5"

echo "========== ??VTU?? =========="
find "$DST" -maxdepth 1 -name "*.vtu" | wc -l

echo "========== ??HDF5?? =========="
find "$DST" -maxdepth 1 -name "*.h5" | wc -l

echo "========== ????? =========="
du -sh "$DST"

echo "========== ?????? =========="
