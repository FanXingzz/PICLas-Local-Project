"""Check the D50 and D100 rounded-tip refinements against the 1 V baselines."""
import csv
import json
from pathlib import Path

import h5py
import numpy as np

from analyze_full_pulse import E_CHARGE, axisymmetric_gauss_weights, rotational_volumes, table
from check_swept_fields import CORNERS, GAUSS_LOW, GAUSS_WIDTH, completed_run, sample_run, tensor_weights
from tube_cases import taper_dimensions


ROOT = Path(__file__).resolve().parent
COARSE = {50: "He_D50um_R2um_Gap1mm_Pos1500V_AnodeSeed_NoEmission",
          100: "He_W_D100um_R2um_Gap1mm_Pos1500V_Seed1e16_QuartzAbsorb"}
LEVELS = ("coarse", "medium", "fine", "tip-fine")


def cap_error(case):
    """Measure the actual boundary chords in the linear Gmsh input, in µm."""
    geometry = json.loads((case/"geometry.json").read_text())
    tip = geometry["tip_gap_um"]/2
    radius = geometry["tip_radius_um"]
    tapered = geometry.get("needle_shape") == "tapered"
    tangent, tangent_r, _ = taper_dimensions(geometry) if tapered else (radius, radius, None)
    source = (case/"geometry.msh").read_text()
    vertices = np.loadtxt(source.split("$Nodes\n")[1].split("$EndNodes")[0].splitlines()[1:])[:, 1:3]
    deviations = []
    faces = {1: 0, 2: 0}
    for line in source.split("$Elements\n")[1].split("$EndElements")[0].splitlines()[1:]:
        record = [int(item) for item in line.split()]
        kind, n_tags, boundary = record[1:4]
        if kind != 3 or boundary not in faces:
            continue
        points = np.unique(vertices[np.array(record[3+n_tags:])-1], axis=0)
        x = abs(points[:, 0])
        r = points[:, 1]
        if tapered:
            depth = np.maximum(0, x-tip)
            cone = tangent_r+(depth-tangent)*np.tan(np.radians(geometry["cone_half_angle_deg"]))
            exact = np.where(depth <= tangent, np.sqrt(np.maximum(0, depth*(2*radius-depth))),
                             np.minimum(cone, geometry["shaft_diameter_um"]/2))
            if not np.allclose(r, exact, atol=1e-7, rtol=0):
                raise ValueError(f"Electrode vertices do not follow the cap, cone and shaft: {case}")
        if np.all(x >= tip-1e-8) and np.all(x <= tip+tangent+1e-8) and np.all(r <= tangent_r+1e-8):
            offsets = np.column_stack((x-tip-radius, r))
            if not np.allclose(np.linalg.norm(offsets, axis=1), radius, atol=1e-8, rtol=0):
                raise ValueError(f"Cap vertices do not lie on R={radius:g} µm: {case}")
            deviations.append(radius-np.linalg.norm(offsets.mean(axis=0)))
            faces[boundary] += 1
    if not all(faces.values()):
        raise ValueError(f"Missing electrode cap faces: {case}")
    return max(deviations), faces


def peak_gas_field(run):
    with h5py.File(run/"helium_mesh.h5") as mesh:
        vertices = mesh["NodeCoords"][:].reshape(-1, 8, 3)
        gas = mesh["ElemInfo"][:, 1] == 1
    with h5py.File(sorted(run.glob("helium_pulse_State_*.h5"))[-1]) as state:
        magnitudes = np.linalg.norm(state["DG_Solution"][:].reshape(len(vertices), 8, 4)[gas, :, 1:], axis=2)
    cell, node = np.unravel_index(np.argmax(magnitudes), magnitudes.shape)
    coordinate = tensor_weights(GAUSS_LOW+GAUSS_WIDTH*CORNERS[node]) @ vertices[gas][cell]*1e6
    return float(magnitudes[cell, node]), coordinate[:2].tolist()


def wall_balance(run):
    surface = table(run/"SurfaceAnalyze.csv")
    particles = table(run/"PartAnalyze.csv")
    time = surface["TIME"]
    dt = np.diff(time, prepend=0)
    incident_e = surface["Flux-Spec-003-BC_Quartz"]*dt
    incident_i = surface["Flux-Spec-002-BC_Quartz"]*dt
    expected = E_CHARGE*np.cumsum(incident_i-incident_e)
    weights = axisymmetric_gauss_weights(run/"helium_mesh.h5")
    errors = []
    for frame in sorted(run.glob("helium_pulse_State_*.h5")):
        with h5py.File(frame) as state:
            stamp = state.attrs["Time"][0]
            charge = float(np.sum(state["DG_SourceExt"][:].reshape(-1, 2, 4).mean(1)*weights))
            index = int(np.argmin(abs(time-stamp)))
            if abs(time[index]-stamp) > 1e-20:
                raise ValueError("Wall diagnostics and saved states differ in time.")
            errors.append(abs(charge-expected[index]))
    volume = rotational_volumes(run/"helium_mesh.h5").sum()
    changes = []
    for species in (2, 3):
        counts = particles[f"NumDens-Spec-00{species}"]*volume
        loss = sum(surface[f"Flux-Spec-00{species}-BC_{boundary}"]*dt
                   for boundary in ("HV", "Ground", "Quartz"))
        emitted = np.zeros(len(time))
        if species == 3:
            emitted = sum(surface.get(f"ElectricCurrentSEE-BC_{boundary}", np.zeros(len(time)))*dt/E_CHARGE
                          for boundary in ("HV", "Ground", "Quartz"))
        changes.append(counts-counts[0]+np.cumsum(loss-emitted))
    return float(incident_e.sum()), float(expected[-1]), max(errors), float(np.max(abs(changes[0]-changes[1])))


def main():
    all_rows = []
    cases = ROOT/"cases"
    for bore, coarse in COARSE.items():
        paths = [cases/coarse, *(cases/f"He_W_D{bore}um_R2um_Gap1mm_QuartzAbsorb_{suffix}"
                                for suffix in ("Medium", "Fine", "TipFine"))]
        by_level = {}
        for path, level in zip(paths, LEVELS, strict=True):
            run = completed_run(path)
            rows = [dict(bore_um=bore, run=run.name, **row) for row in sample_run(run, level, include_axis=True)]
            all_rows.extend(rows)
            by_level[level] = rows
            midpoint = next(row["Ex_V_m"] for row in rows if row["probe"] == "axis,x=0")
            error, faces = cap_error(path)
            print(bore, level, rows[0]["hexes"], f"center Ex {midpoint:.5f} V/m, cap sagitta {error:.6f} um", faces)
        for region, fields in (("tip", ("Ex_V_m", "Ey_V_m")), ("wall", ("Ex_V_m", "Ey_V_m")),
                               ("wall", ("Ey_V_m",)), ("axis", ("Ex_V_m",))):
            values = [np.array([[row[key] for key in fields] for row in by_level[level] if row["region"] == region])
                      for level in LEVELS]
            differences = [np.linalg.norm(a-b)/np.linalg.norm(b)*100 for a, b in zip(values[:-1], values[1:])]
            print(bore, region, "+".join(fields), "L2 %", *[round(value, 5) for value in differences])
        for path in paths[-2:]:
            for pilot in sorted((path/"runs").glob("*-pilot-*")):
                if (pilot/"run-status.txt").read_text().strip() == "complete":
                    print(bore, pilot.name, "(wall electrons, wall charge C, max charge error C, max e/ion balance error)",
                          wall_balance(pilot))
        tapered = cases/f"He_W_D{bore}um_TaperedR2um_Shaft10um_Gap1mm_QuartzAbsorb"
        if not (tapered/"mesh-geometry.json").is_file():
            continue
        run = completed_run(tapered)
        rows = [dict(bore_um=bore, run=run.name, **row) for row in sample_run(run, "tapered", include_axis=True)]
        all_rows.extend(rows)
        error, faces = cap_error(tapered)
        print(bore, "tapered", rows[0]["hexes"], f"cap sagitta {error:.6f} um", faces)
        for comparison, samples in (("tip-fine", by_level["tip-fine"]), ("tapered", rows)):
            tip = next(row for row in samples if row["probe"] == "HV+0.25um")
            center = next(row for row in samples if row["probe"] == "axis,x=0")
            print(bore, comparison, "tip axial E", tip["Ex_V_m"], "center axial E", center["Ex_V_m"])
        print(bore, "tapered gas peak E and (x,r) um", peak_gas_field(run))
        for pilot in sorted((tapered/"runs").glob("*-pilot-*")):
            if (pilot/"run-status.txt").is_file() and (pilot/"run-status.txt").read_text().strip() == "complete":
                print(bore, pilot.name, "tapered wall balance", wall_balance(pilot))
    with (cases/"axisymmetric_d50_d100_refinement.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(all_rows[0]))
        writer.writeheader()
        writer.writerows(all_rows)


if __name__ == "__main__":
    main()
