"""Prepare matched quartz-wall cases from the completed tungsten reference."""
import json
import math
from pathlib import Path
import shutil

from tube_cases import replace_parameters

ROOT = Path(__file__).resolve().parent
REFERENCE = ROOT / "cases/He_W_D50um_R2um_Gap1mm_Pos1500V_Seed1e16_SEE015_Refl020/runs/20261111-114633-research-l6wfPv"
PREFIX = "He_W_D{bore}um_R2um_Gap1mm_Pos1500V_Seed1e16"


def prepare(bore, returning):
    suffix = "QuartzDunaevsky" if returning else "QuartzAbsorb"
    case = ROOT / "cases" / (PREFIX.format(bore=bore) + "_" + suffix)
    case.mkdir()
    geometry = json.loads((REFERENCE / "geometry.json").read_text(encoding="utf-8"))
    info = json.loads((REFERENCE / "case-info.json").read_text(encoding="utf-8"))
    text = (REFERENCE / "parameter.ini").read_text(encoding="utf-8")
    if bore == 50:
        original = REFERENCE.parent.parent
        for name in ("helium_mesh.h5", "mesh-geometry.json", "geometry.msh", "mesh.ini"):
            shutil.copy2(original / name, case / name)
        shutil.copytree(original / "model", case / "model")
    else:
        outer = bore + geometry["tube_outer_um"] - geometry["tube_bore_um"]
        geometry.update(tube_bore_um=float(bore), tube_outer_um=outer,
                        domain_width_um=outer, radius_over_bore=geometry["tip_radius_um"]/bore)
        geometry["mesh_settings"]["bore_layers"] = 12
        radius = (bore/2 - 0.5)*1e-6
        weight = info["seed_density_m3"]*math.pi*radius**2*info["seed_length_m"]/info["seed_macroparticles_per_species"]
        info.update(seed_radius_m=radius, seed_weight=weight)
        info["limitations"][-1] = "100 μm 轴对称基准网格，等离子体网格与时间步收敛仍待验证。"
        text = replace_parameters(text, {
            f"Part-Species{species}-{key}": f"{value:.14g}"
            for species in (2, 3)
            for key, value in (("Init1-RadiusIC", radius), ("MacroParticleFactor", weight))
        })
    if returning:
        text = "\n".join(line for line in text.splitlines()
                         if not line.startswith(("Part-Boundary3-NbrOfSpeciesSwaps",
                                                 "Part-Boundary3-SpeciesSwaps"))) + "\n"
        text += ("\n! Dunaevsky Table I effective total electron return on BC_Quartz\n"
                 "Part-Boundary3-SurfaceModel = 11\n"
                 "Part-Species3-PartBound3-ResultSpec = 3\n")
        info["limitations"].append("石英总返回产额沿用低能电子束线性拟合，包含反射与二次发射。角分布、返回能谱及实管低能数据仍有不确定性。")
    info.update(display_name=f"钨针｜{bore} μm｜石英壁" + ("总返回模型" if returning else "全吸收"),
                quartz_wall_model="Dunaevsky2003_linear_total_return" if returning else "absorb",
                reference_run=str(REFERENCE.resolve()))
    info["reference_urls"].append("https://doi.org/10.1063/1.1568344")
    shutil.copy2(REFERENCE / "DSMC.ini", case / "DSMC.ini")
    shutil.copy2(ROOT / "docs" / "quartz-wall-literature.txt", case / "literature-review.txt")
    geometry_text = ((REFERENCE / "geometry.json").read_text(encoding="utf-8")
                     if bore == 50 else json.dumps(geometry, indent=2) + "\n")
    (case / "geometry.json").write_text(geometry_text, encoding="utf-8")
    (case / "parameter.ini").write_text(text, encoding="utf-8")
    (case / "case-info.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    print(case)


if __name__ == "__main__":
    prepare(50, True)
    prepare(100, False)
    prepare(100, True)
