"""Stage the original checkpoint model plus the selected adaptive settings."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from adaptive_weight_settings import FIELDS, MERGE_FIELDS, settings_for
from record_model_settings import settings_text
from tube_cases import replace_parameters

REFERENCE = HERE.with_name("He_D100um_Pos6000V_Optimized_Restart1250ps")


def stage(run, fixed_control=False, settings_from=None, reference=REFERENCE):
    inputs = reference/"inputs"
    checkpoint = json.loads((inputs/"checkpoint.json").read_text(encoding="utf-8"))
    populations = json.loads((HERE/"reference-populations.json").read_text(encoding="utf-8"))
    if populations["checkpoint_sha256"] != checkpoint["sha256"]:
        raise ValueError("Adaptive reference populations do not match the frozen checkpoint.")
    for name in ("DSMC.ini", "geometry.json", "CHEMISTRY_PLAN.json", "helium_mesh.h5", "Electronic-State-Database.h5",
                 "XSec_Database_He_Plasma.h5", "R15_SOURCE_REVIEW.md", checkpoint["filename"]):
        shutil.copy2(inputs/name, run/name)
    if sha256((run/checkpoint["filename"]).read_bytes()).hexdigest() != checkpoint["sha256"]:
        raise ValueError("Checkpoint copy failed verification.")
    shutil.copy2(HERE/"reference-populations.json", run/"reference-populations.json")
    if settings_from and not (settings_from/"settings.json").is_file():
        raise ValueError("The reference run has no saved weight settings.")
    settings = settings_for(settings_from or HERE)
    if fixed_control:
        settings["exponent"] = 0.
    base = (reference/"optimized"/"parameter.ini").read_text(encoding="ascii")
    base = replace_parameters(base, {parameter: settings[key] for key, _, _, _, _, parameter in MERGE_FIELDS})
    lines = ["Part-AdaptiveVMPF = T"]
    for key, _, _, _, _, parameter in FIELDS:
        value = settings[key]*1e-6 if key == "tip_width_um" else settings[key]
        lines.append(f"{parameter} = {value:.16g}")
    for species, values in populations["species"].items():
        lines.append(f"Part-Species{species}-vMPFReferencePopulation = {values['weighted']:.16g}")
        lines.append(f"Part-Species{species}-vMPFReferenceWeight = {values['mean_weight']:.16g}")
    parameter = base.rstrip()+"\n\n! Adaptive vMPF\n"+"\n".join(lines)+"\n"
    (run/"parameter.ini").write_text(parameter, encoding="ascii")
    (run/"settings.json").write_text(json.dumps(settings, indent=2)+"\n", encoding="utf-8")
    metadata = json.loads((inputs/"case-info.json").read_text(encoding="utf-8"))
    label = f"100 μm · 自适应权重 α={settings['exponent']:g}"
    thresholds = [f"{species} {settings[key]}" for key, species, default, *_ in MERGE_FIELDS
                  if settings[key] != default]
    if thresholds:
        label += " · " + "、".join(thresholds)
    metadata.update(display_name=label, study="adaptive_vmpf",
                    adaptive_weight=settings, restart_checkpoint=checkpoint)
    (run/"case-info.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    extra = ("## 动态权重短测\n\n"
             "从 1.25 ns 检查点续算到 1.275 ns，6 个 MPI 进程。初始粒子来自检查点。\n\n")
    for key, label, *_ in FIELDS:
        extra += f"- {label} `{settings[key]}`\n"
    extra += "\n### 固定合并阈值（每单元、每物种）\n\n"
    for key, label, *_ in MERGE_FIELDS:
        extra += f"- {label} `{settings[key]}`\n"
    if settings["exponent"] > 0:
        extra += "\n自适应权重目标和额外合并数见 `AdaptiveVMPF.csv`。"
    extra += "\n\n"
    model = settings_text(run, parameter, metadata).replace("## 几何、网格与驱动", extra+"## 几何、网格与驱动", 1)
    (run/"MODEL_SETTINGS.md").write_text(model, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--reference", type=Path, default=REFERENCE)
    options = parser.add_mutually_exclusive_group()
    options.add_argument("--fixed-control", action="store_true")
    options.add_argument("--settings-from", type=Path)
    args = parser.parse_args()
    stage(args.run, args.fixed_control, args.settings_from, args.reference)
