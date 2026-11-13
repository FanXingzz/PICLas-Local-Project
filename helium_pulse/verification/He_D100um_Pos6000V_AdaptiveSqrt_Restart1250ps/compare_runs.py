"""Compare the adaptive checkpoint run with the fixed-threshold optimized run."""
import argparse
import csv
import json
from pathlib import Path
import sys

import h5py
import numpy as np

HERE = Path(__file__).resolve().parent
BASE = HERE.with_name("He_D100um_Pos6000V_Optimized_Restart1250ps")
DEFAULT_REFERENCE = BASE/"runs/20261112-175045-checkpoint1250ps-332GY5/optimized"
sys.path[:0] = [str(BASE), str(HERE.parents[1])]
from compare import DT, END, START, STEPS, measure
from adaptive_weight_settings import settings_for
from analyze_full_pulse import E_CHARGE, axisymmetric_gauss_weights, rotational_volumes

ELECTRON_MASS = 9.1093837015e-31
SPECIES = {2: "He+", 3: "e", 4: "He2+", 5: "He*", 6: "He2*"}


def high_energy_and_wall(run, charge_weights):
    path = next(path for path in run.glob("helium_pulse_State_*.h5")
                if abs(float(path.stem.rsplit("_", 1)[1])-END) < 1e-20)
    with h5py.File(path, "r") as state:
        particles = state["PartData"][:]
        electrons = particles[particles[:, 6] == 3]
        weights = electrons[:, -1]
        energy = 0.5*ELECTRON_MASS*np.sum(electrons[:, 3:6]**2, axis=1)/E_CHARGE
        tail = {str(threshold): float(weights[energy >= threshold].sum()/weights.sum())
                if weights.size else None for threshold in (19.82, 24.587)}
        source = state["DG_SourceExt"][:].reshape(-1, 2, 4).mean(axis=1)
        wall_charge = float(np.sum(source*charge_weights))
    return tail, wall_charge


def controller(run):
    config = json.loads((run/"settings.json").read_text(encoding="utf-8"))
    references = json.loads((run/"reference-populations.json").read_text(encoding="utf-8"))["species"]
    totals = {label: 0 for label in SPECIES.values()}
    targets = {}
    steps = set()
    log = run/"AdaptiveVMPF.csv"
    if config["exponent"] > 0 and not log.is_file():
        raise ValueError("The adaptive merge controller did not report any samples.")
    if log.is_file():
        with log.open(newline="") as stream:
            for row in csv.DictReader(stream):
                species = int(row["species"])
                reference = references[str(species)]
                weighted = float(row["weighted_population"])
                gain = min(config["max_gain"], max(1., weighted/reference["weighted"])**config["exponent"])
                target = float(row["target_mean_weight"])
                expected = reference["mean_weight"]*gain if gain > 1. else 0.
                if not np.isclose(target, expected, rtol=1e-10, atol=1e-12):
                    raise ValueError(f"Incorrect weight target at step {row['step']} for species {species}.")
                steps.add(int(row["step"]))
                totals[SPECIES[species]] += int(float(row["removed"]))
                targets[SPECIES[species]] = target
    return {"settings": config, "updates": len(steps), "macros_removed_by_adaptive_merge": totals,
            "last_target_mean_weight": targets}


def compare(run, reference):
    mesh = run/"helium_mesh.h5"
    checkpoint = json.loads((BASE/"inputs/checkpoint.json").read_text(encoding="utf-8"))
    frozen_inputs = dict((name, digest) for digest, name in
                         (line.split(maxsplit=1) for line in (BASE/"inputs/input-sha256.txt").read_text().splitlines()))
    for directory in (run, reference):
        hashes = dict((name, digest) for digest, name in
                      (line.split(maxsplit=1) for line in (directory/"input-sha256.txt").read_text().splitlines()))
        for name in (checkpoint["filename"], "helium_mesh.h5", "geometry.json", "DSMC.ini", "CHEMISTRY_PLAN.json",
                     "Electronic-State-Database.h5", "XSec_Database_He_Plasma.h5"):
            if hashes.get(name) != frozen_inputs[name]:
                raise ValueError(f"Unexpected hash for {name} in {directory.name}.")
    volumes = rotational_volumes(mesh)
    charge_weights = axisymmetric_gauss_weights(mesh)
    with h5py.File(mesh, "r") as source:
        gas_volume = float(volumes[source["ElemInfo"][:, 1] == 1].sum())
    geometry = json.loads((run/"geometry.json").read_text(encoding="utf-8"))
    half_gap = geometry["tip_gap_um"]*0.5e-6
    edges = np.linspace(-half_gap, half_gap, 41)
    bin_volume = np.pi*(geometry["tube_bore_um"]*0.5e-6)**2*np.diff(edges)
    base, b_e, b_current, b_axial = measure(reference, volumes, edges, bin_volume)
    trial, a_e, a_current, a_axial = measure(run, volumes, edges, bin_volume)
    for stats, directory in ((base, reference), (trial, run)):
        stats["final"]["gas_mean_density_m3"] = stats["final"]["weighted_electrons"]/gas_volume
        tail, wall = high_energy_and_wall(directory, charge_weights)
        stats["final"]["electron_weight_fraction_above_eV"] = tail
        stats["final"]["quartz_charge_C"] = wall
    reference_settings = settings_for(reference) if (reference/"settings.json").is_file() else None
    reference_key = "reference" if reference_settings and reference_settings["exponent"] > 0 else "fixed"
    result = {"checkpoint": checkpoint, "reference_run": str(reference.resolve()), reference_key: base, "adaptive": trial,
              "controller": controller(run), "speedup_wall_clock": base["wall_seconds"]/trial["wall_seconds"],
              "electron_final_axial_relative_l1": float(np.sum(abs(a_axial-b_axial))/np.sum(abs(b_axial)))
                                                  if np.any(b_axial) else None}
    if reference_settings:
        result["reference_settings"] = reference_settings
    with (run/"current_and_density_comparison.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["time_ns", f"{reference_key}_ne_m3", "adaptive_ne_m3", f"{reference_key}_hv_A",
                         "adaptive_hv_A", f"{reference_key}_ground_A", "adaptive_ground_A"])
        block = round(1e-12/DT)
        for i in range(0, STEPS, block):
            j = i+block
            writer.writerow([(START+(i+j)*0.5*DT)*1e9, b_e[i:j].mean()/gas_volume, a_e[i:j].mean()/gas_volume,
                             b_current["HV"][i:j].mean(), a_current["HV"][i:j].mean(),
                             b_current["Ground"][i:j].mean(), a_current["Ground"][i:j].mean()])
    with (run/"final_axial_density_comparison.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["x_um", f"{reference_key}_ne_m3", "adaptive_ne_m3"])
        writer.writerows(zip((edges[:-1]+edges[1:])*0.5e6, b_axial, a_axial))
    (run/"comparison.json").write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    args = parser.parse_args()
    print(json.dumps(compare(args.run, args.reference), indent=2))
