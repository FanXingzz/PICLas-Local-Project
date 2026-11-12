"""Sample matched gas-side points in completed 1 V swept-grid comparisons."""
import argparse
import csv
import json
from pathlib import Path

import h5py
import numpy as np

# HOPR stores linear geometry nodes in tensor order, first index fastest.
CORNERS = np.array([(i, j, k) for k in (0, 1) for j in (0, 1) for i in (0, 1)])
GAUSS_LOW = (1-1/np.sqrt(3))/2
GAUSS_WIDTH = 1/np.sqrt(3)
LEVELS = ("coarse", "medium", "fine")


def tensor_weights(local):
    return np.where(CORNERS, local, 1-local).prod(axis=1)


def invert_hex(vertices, point):
    """Invert the trilinear geometry map in micrometres."""
    local = np.full(3, 0.5)
    for _ in range(12):
        residual = tensor_weights(local) @ vertices - point
        if np.linalg.norm(residual, ord=np.inf) < 1e-9:
            return local
        factors = np.where(CORNERS, local, 1-local)
        jacobian = np.column_stack([
            ((2*CORNERS[:, axis]-1) * np.delete(factors, axis, axis=1).prod(axis=1)) @ vertices
            for axis in range(3)
        ])
        local -= np.linalg.solve(jacobian, residual)
    raise ValueError(f"Could not invert geometry at {point}")


def probe_points(axisymmetric=False, bore_radius=25., include_axis=False):
    for distance in (0.25, 0.5, 1., 2., 4.):
        yield "tip", f"HV+{distance:g}um", (-500+distance, 0., 0.)
        yield "tip", f"ground-{distance:g}um", (500-distance, 0., 0.)
    for x in (-495., -490., -475., -450., -250., 0., 250., 450., 475., 490., 495.):
        for offset in (0.25, 0.5, 1., 2.):
            if not axisymmetric:
                yield "wall", f"z-wall,x={x:g},offset={offset:g}", (x, 0., bore_radius-offset)
            yield "wall", f"y-wall,x={x:g},offset={offset:g}", (x, bore_radius-offset, 0.)
    if include_axis:
        for x in (-250., 0., 250.):
            yield "axis", f"axis,x={x:g}", (x, 0., 0.)


def completed_run(case):
    options = sorted((case/"runs").glob("*-field-check-*"))
    return next(run for run in reversed(options) if (run/"run-status.txt").is_file())


def sample_run(run, level, include_axis=False):
    with (run/"FieldAnalyze.csv").open(newline="") as stream:
        last = list(csv.DictReader(stream))[-1]
    applied = float(last[next(key for key in last if key.endswith("BFO-boundary-001-bc_hv"))])
    grounded = float(last[next(key for key in last if key.endswith("BFO-boundary-002-bc_ground"))])
    if applied != 1. or grounded != 0.:
        raise ValueError("Expected 1 V on the high-voltage needle and 0 V on ground")
    with h5py.File(run/"helium_mesh.h5") as mesh:
        vertices = mesh["NodeCoords"][:].reshape(-1, 8, 3)*1e6
        gas = mesh["ElemInfo"][:, 1] == 1
    state_path = sorted(run.glob("*_State_*.h5"))[-1]
    with h5py.File(state_path) as state:
        if int(state.attrs["N"][0]) != 1 or state.attrs["NodeType"][0] != b"GAUSS":
            raise ValueError("The field sampler requires N=1 with Gauss nodes")
        if state["PartData"].shape[0] != 0:
            raise ValueError("Electrostatic comparison must have no charged particles")
        if not np.isclose(state.attrs["Time"][0], 4e-13, rtol=1e-10, atol=0):
            raise ValueError("Missing final electrostatic frame")
        values = state["DG_Solution"][:].reshape(len(vertices), 8, 4)

    lower, upper = vertices.min(axis=1), vertices.max(axis=1)
    geometry = json.loads((run/"geometry.json").read_text())
    axisymmetric = geometry.get("mesh_method") == "axisymmetric"
    for group, name, coords in probe_points(axisymmetric, geometry["tube_bore_um"]/2, include_axis):
        point = np.array(coords)
        candidates = np.flatnonzero(gas & np.all(point >= lower-1e-9, axis=1)
                                    & np.all(point <= upper+1e-9, axis=1))
        samples = []
        for cell in candidates:
            try:
                local = invert_hex(vertices[cell], point)
            except (ValueError, np.linalg.LinAlgError):
                continue
            if np.all(local >= -1e-8) and np.all(local <= 1+1e-8):
                samples.append(tensor_weights((local-GAUSS_LOW)/GAUSS_WIDTH) @ values[cell])
        if not samples:
            raise ValueError(f"{level}: no gas cell covers {name}")
        potential, ex, ey, ez = np.mean(samples, axis=0)
        yield {"level": level, "hexes": len(vertices), "region": group, "probe": name,
               "x_um": coords[0], "y_um": coords[1], "z_um": coords[2],
               "phi_V": potential, "Ex_V_m": ex, "Ey_V_m": ey, "Ez_V_m": ez,
               "traces": len(samples)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=Path(__file__).resolve().parent/"archive"/"3d-meshes")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case-names", nargs=3, metavar=("COARSE", "MEDIUM", "FINE"))
    args = parser.parse_args()
    names = args.case_names or [f"Archive3D_D50um_R2um_Plates_Swept_{level.title()}" for level in LEVELS]
    runs = {level: completed_run(args.cases/name) for level, name in zip(LEVELS, names, strict=True)}
    rows = [row for level, run in runs.items() for row in sample_run(run, level)]
    with args.output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    fields = ("Ex_V_m", "Ey_V_m", "Ez_V_m")
    for group in ("tip", "wall"):
        print(group)
        arrays = {level: np.array([[row[field] for field in fields] for row in rows
                                   if row["level"] == level and row["region"] == group])
                  for level in LEVELS}
        for old, new in zip(LEVELS, LEVELS[1:]):
            diff = np.linalg.norm(arrays[old]-arrays[new])/np.linalg.norm(arrays[new])
            print(f"  {old} -> {new}: relative vector L2 change {100*diff:.3f}%")
    normals = {level: np.array([row["Ey_V_m"] if row["y_um"] else row["Ez_V_m"]
                               for row in rows if row["level"] == level and row["region"] == "wall"])
               for level in LEVELS}
    for old, new in zip(LEVELS, LEVELS[1:]):
        diff = np.linalg.norm(normals[old]-normals[new])/np.linalg.norm(normals[new])
        print(f"wall-normal {old} -> {new}: relative L2 change {100*diff:.3f}%")
    for level, run in runs.items():
        print(level, run.name)


if __name__ == "__main__":
    main()
