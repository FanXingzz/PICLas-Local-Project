"""Create the independent, literature-informed D50 tungsten seed/SEE study."""
import json
import math
from pathlib import Path
import shutil

from tube_cases import replace_parameters

ROOT = Path(__file__).resolve().parent
OLD_CASE = ROOT/"cases/He_D50um_R2um_Gap1mm_Pos1500V_AnodeSeed_NoEmission"
NEW_NAME = "He_W_D50um_R2um_Gap1mm_Pos1500V_Seed1e16_SEE015_Refl020"


def prepare():
    target = ROOT/"cases"/NEW_NAME
    target.mkdir(exist_ok=False)
    for name in ("parameter.ini", "DSMC.ini", "geometry.json", "helium_mesh.h5",
                 "mesh-geometry.json", "mesh_regions.npz", "geometry.msh", "mesh.ini"):
        if (OLD_CASE/name).is_file():
            shutil.copy2(OLD_CASE/name, target/name)
    if (OLD_CASE/"model").is_dir():
        shutil.copytree(OLD_CASE/"model", target/"model")
    seed_radius, seed_length, seed_density, count = 24.5e-6, 998e-6, 1e16, 2048
    weight = seed_density*math.pi*seed_radius**2*seed_length/count
    source = {
        "display_name": "钨针｜全气隙预电离 1e16｜离子发射0.15｜电子反射0.20",
        "study": "uniform_gap_seed_and_tungsten_effective_emission",
        "electrode_material": "tungsten", "seed_density_m3": seed_density,
        "seed_radius_m": seed_radius, "seed_length_m": seed_length,
        "seed_start_x_m": -499e-6, "seed_macroparticles_per_species": count,
        "seed_weight": weight, "electron_temperature_eV": 1., "ion_temperature_K": 298.,
        "ion_induced_yield": .15, "electron_reflection_probability": .2,
        "emitted_energy_distribution": "uniform 0..4 eV (assumed low-energy spectrum)",
        "continuous_volume_source": False, "thermionic_emission": False, "field_emission": False,
        "secondary_emission_is_effective_assumption": True,
        "reference_urls": ["https://doi.org/10.1088/1361-6595/aac301",
                           "https://arxiv.org/abs/1803.04026",
                           "https://doi.org/10.1103/PhysRev.96.325",
                           "https://doi.org/10.1088/1361-6595/aad4db"],
        "limitations": ["预电离代表脉冲前残余电荷，不代表冷气体自然背景。",
                        "gamma=0.15 与电子反射0.2是有效假设，未标定真实钨针的污染、粗糙度与入射能量依赖。",
                        "发射能谱0..4 eV为低能近似，不是钨针实测能谱。",
                        "仍为简化纯He化学，无He2+、亚稳态、VUV光发射或杂质反应。",
                        "保留864单元网格便于与原始基线比较；等离子体数值收敛尚未证明。"]}
    values = {"doPrintStatusLine": "F", "IterDisplayStep": "1000"}
    for species in (2, 3):
        prefix = f"Part-Species{species}"
        values.update({f"{prefix}-MacroParticleFactor": f"{weight:.14g}",
                       f"{prefix}-Init1-ParticleNumber": str(count),
                       f"{prefix}-Init1-BasePointIC": "(/-0.000499,0.,0./)",
                       f"{prefix}-Init1-RadiusIC": f"{seed_radius:.14g}",
                       f"{prefix}-Init1-CylinderHeightIC": f"{seed_length:.14g}",
                       f"{prefix}-Init1-MWTemperatureIC": "11604.51812" if species == 3 else "298.",
                       f"{prefix}-vMPFMergeThreshold": "100"})
    for boundary in (1, 2):
        values[f"Part-Boundary{boundary}-Condition"] = "reflective"
    text = replace_parameters((target/"parameter.ini").read_text(), values)
    # Remove obsolete cuboid-only settings from the cylinder initialization.
    text = "\n".join(line for line in text.splitlines() if "-CuboidHeightIC" not in line)+"\n"
    text += "\n! Tungsten effective electrode model; see case-info.json and literature-review.txt.\n"
    for boundary in (1, 2):
        text += (f"Part-Boundary{boundary}-SurfaceModel = 7\n"
                 f"Part-Boundary{boundary}-WallTemp = 298.\n"
                 f"Part-Boundary{boundary}-MomentumACC = 0.\n"
                 f"Part-Boundary{boundary}-SurfModEmissionYield = 0.15\n"
                 f"Part-Boundary{boundary}-SurfModEnergyDistribution = uniform-energy\n"
                 f"Part-Boundary{boundary}-SurfModEmissionEnergy = 4.\n"
                 f"Part-Boundary{boundary}-SurfModElectronReflection = 0.2\n"
                 f"Part-Species2-PartBound{boundary}-ResultSpec = 3\n")
    text += "CalcCurrentSEE = T\n"
    (target/"parameter.ini").write_text(text, encoding="utf-8")
    (target/"case-info.json").write_text(json.dumps(source, ensure_ascii=False, indent=2), encoding="utf-8")
    print(target)
    print(f"Seed: {count} electrons + {count} ions; weight {weight:.9g}; physical number/species {count*weight:.9g}")
    return target


if __name__ == "__main__":
    prepare()
