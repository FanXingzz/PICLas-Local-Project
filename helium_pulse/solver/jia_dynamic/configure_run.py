"""Configure the dynamic Jia solver in a newly staged run directory."""

import argparse
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from adaptive_weight_settings import FIELDS, MERGE_FIELDS, case_settings, weight_parameters, write_weight_parameters
from piclas_ini import parse_parameters, real
from tube_cases import read_geometry


def reference_parameters(parameters):
    references = {}
    for key, _, default_threshold, _, _, threshold in MERGE_FIELDS:
        prefix = f"Part-Species{key.removeprefix('merge_')}-"
        weight = real(parameters[prefix + "MacroParticleFactor"])
        count = int(parameters.get(prefix + "Init1-ParticleNumber", "0"))
        if count <= 0:
            count = int(parameters.get(threshold, default_threshold)) or default_threshold
        population = count * weight
        if not (math.isfinite(weight) and weight > 0 and math.isfinite(population) and population > 0):
            raise ValueError(f"{prefix} needs a positive nominal weight and reference population.")
        references[prefix + "vMPFReferencePopulation"] = f"{population:.16g}"
        references[prefix + "vMPFReferenceWeight"] = f"{weight:.16g}"
    return references


def configure(run, ranks, mode):
    path = run / "parameter.ini"
    text = path.read_text(encoding="utf-8-sig")
    parameters = parse_parameters(text)
    adaptive = mode != "field-check"
    balance = adaptive and ranks > 1
    changes = {"DoLoadBalance": "T" if balance else "F", "Part-AdaptiveVMPF": "T" if adaptive else "F"}
    if balance:
        changes.update({"UseH5IOLoadBalance": "T", "PartWeightLoadBalance": "F", "LoadBalanceSample": 100,
                        "LoadBalanceMaxSteps": 64, "Load-DeviationThreshold": 0.10})
    if adaptive:
        geometry = read_geometry(run / "geometry.json")
        half_gap = float(geometry["tip_gap_um"]) * 0.5e-6
        if not math.isfinite(half_gap) or half_gap <= 0:
            raise ValueError("Dynamic Jia requires a positive needle gap.")
        changes["Part-AdaptiveVMPFTipHalfGap"] = f"{half_gap:.16g}"
        weights = case_settings(parameters)
        changes.update(weight_parameters(weights, FIELDS))
        tip_width = min(weights["tip_width_um"]*1e-6, half_gap)
        changes["Part-AdaptiveVMPFTipWidth"] = f"{tip_width:.16g}"
        changes.update(reference_parameters(parameters))

    text = write_weight_parameters(text, parameters, changes)
    path.write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("ranks", type=int, choices=range(1, 7))
    parser.add_argument("mode", choices=("research", "pilot", "smoke", "field-check"))
    args = parser.parse_args()
    configure(args.run, args.ranks, args.mode)
