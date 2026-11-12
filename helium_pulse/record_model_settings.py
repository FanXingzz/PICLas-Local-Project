"""Save readable model settings alongside the exact inputs for a case or run."""
import argparse
import json
from pathlib import Path
import re

from tube_cases import axis_mesh_values, taper_dimensions


def entries(text):
    pairs = []
    for line in text.splitlines():
        key, separator, value = line.split("!", 1)[0].partition("=")
        if separator:
            pairs.append((key.strip(), value.strip()))
    return pairs


def real(value):
    return float(value.lower().replace("d", "e"))


def settings_text(directory, parameter=None, metadata=None):
    if parameter is None:
        parameter = (directory / "parameter.ini").read_text(encoding="utf-8-sig")
    dsmc = (directory / "DSMC.ini").read_text(encoding="utf-8-sig")
    parameters = entries(parameter)
    settings = dict(parameters + entries(dsmc))
    log = next((directory/name for name in ("solver.log", "piclas_run_corrected.log")
                if (directory/name).is_file()), None)
    log_text = log.read_text(encoding="utf-8", errors="replace") if log else ""
    geometry_file = directory / "geometry.json"
    metadata_file = directory / "case-info.json"
    geometry = json.loads(geometry_file.read_text(encoding="utf-8")) if geometry_file.is_file() else {}
    if metadata is None:
        metadata = json.loads(metadata_file.read_text(encoding="utf-8")) if metadata_file.is_file() else {}
    metal_he2_yield = settings.get("Particles-He2-MetalYield")
    run_info = directory / "run-info.txt"
    species = {i: settings.get(f"Part-Species{i}-SpeciesName", f"物种 {i}")
               for i in range(1, int(settings.get("Part-nSpecies", "0")) + 1)}
    display = {"HeIon1": "He⁺", "He2Ion1": "He₂⁺", "HeMeta": "He*", "He2Meta": "He₂*",
               "N2Ion1": "N₂⁺", "N2": "N₂", "electron": "e⁻"}
    species = {i: display.get(name, name) for i, name in species.items()}
    title = metadata.get("display_name", directory.name if geometry else settings.get("ProjectName", directory.name))
    title = re.sub(r"([\\`*_{}\[\]()&<>])", r"\\\1", title)
    lines = ["# 模型设置", "", f"**{title}**", "", f"目录 `{directory.name}`。"]
    if run_info.is_file():
        run = dict(entries(run_info.read_text(encoding="utf-8")))
        lines.append(f"运行模式 `{run.get('mode', '见运行记录')}`，MPI 进程 {run.get('mpi_ranks', '见运行记录')}。")
    if (directory / "run-validation.txt").is_file():
        lines.append("该次运行带有[无效诊断标记](run-validation.txt)。")
    if metadata.get("network_status") == "draft":
        lines.append("六物种和界面配置已准备。石英离子发射需要本算例的独立求解器。" if metal_he2_yield is not None
                     else "Jia 六物种反应待接入。下方求解设置来自保留的四物种输入底本。")

    lines.extend(["", "## 几何、网格与驱动", ""])
    if geometry:
        lines.append(f"- 网格方法 `{geometry.get('mesh_method', '见几何输入')}`，"
                     f"结构 `{geometry.get('structure', '见几何输入')}`。")
        for key, label in (("tube_bore_um", "石英管内径"), ("tube_outer_um", "石英管外径"),
                           ("tip_radius_um", "针尖半径"), ("tip_gap_um", "针尖间距"),
                           ("domain_length_um", "轴向计算域长度")):
            if key in geometry:
                lines.append(f"- {label} {geometry[key]:g} μm。")
        if geometry.get("mesh_method") == "axisymmetric" and geometry.get("structure") == "tube_only":
            if geometry.get("needle_shape") == "tapered":
                tangent, _, shoulder = taper_dimensions(geometry)
                lines.append(f"- 球面圆头与锥段相切，锥半角 {geometry['cone_half_angle_deg']:g}°，"
                             f"直针杆直径 {geometry['shaft_diameter_um']:g} μm。"
                             f"圆头切点与锥段肩部距针尖分别为 {tangent:g}、{shoulder:g} μm。")
            else:
                lines.append(f"- 半球端面，直针杆直径 {2*geometry['tip_radius_um']:g} μm。")
            mesh = axis_mesh_values(geometry["mesh_settings"])
            bore_radius = geometry["tube_bore_um"]/2
            gas_first = (bore_radius-geometry["tip_radius_um"])*mesh["wall_first_percent"]/100
            quartz_first = (geometry["tube_outer_um"]/2-bore_radius)*mesh["quartz_first_percent"]/100
            lines.append(f"- 近壁气体与石英首层分别为 {gas_first:g}、{quartz_first:g} μm，"
                         f"针尖前方轴向细分 {mesh['tip_gap_subdivisions']:g} 倍，"
                         f"直管段轴向最大尺寸 {mesh['axial_max_um']:g} μm。")
    if metadata.get("electrode_material") == "tungsten":
        lines.append("- 两针材料为钨，表面产额和反射概率采用有效参数。")
    mesh_count = re.search(r"^\s*\|\s*nElems\s*\|\s*(\d+)", log_text, re.M)
    cells = f"，{mesh_count[1]} 个单元" if mesh_count else ""
    lines.append(f"- 网格 `{settings.get('MeshFile', '见输入')}`{cells}，场求解多项式阶次 {settings.get('N', '见输入')}。")
    if settings.get("PrecondType") == "10":
        lines.append("- 场方程每个粒子步求解，采用 PETSc/MUMPS 直接分解。")
    if "TrackingMethod" in settings:
        lines.append(f"- 粒子追踪 `{settings['TrackingMethod']}`。")
    if "PulsePeak" in settings:
        rise, flat, fall = (real(settings[key])*1e9 for key in ("PulseRise", "PulseFlat", "PulseFall"))
        lines.append(f"- 高压针峰值 {real(settings['PulsePeak']):+g} V，上升 {rise:g} ns、"
                     f"平顶 {flat:g} ns、下降 {fall:g} ns。")
    for key, label, scale, unit in (("tend", "求解终止时间", 1e9, "ns"),
                                    ("ManualTimeStep", "时间步", 1e12, "ps"),
                                    ("Analyze_dt", "状态输出间隔", 1e9, "ns")):
        if key in settings:
            lines.append(f"- {label} {real(settings[key])*scale:g} {unit}。")
    if settings.get("DoDielectric") == "T":
        lines.append(f"- 介质区编号 `{settings.get('DielectricZoneID', '见输入')}`，"
                     f"相对介电常数 `{settings.get('DielectricZoneEpsR', '见输入')}`。")

    lines.extend(["", "## 气相碰撞与反应", ""])
    lines.append(f"- `UseDSMC={settings.get('UseDSMC', '见输入')}`，"
                 f"`CollisMode={settings.get('Particles-DSMC-CollisMode', '见输入')}`，"
                 f"空碰撞开关 `{settings.get('Particles-CollXSec-NullCollision', '见输入')}`。")
    for key, label in (("Particles-CollXSec-Database", "碰撞截面库"),
                       ("Particles-DSMCElectronicDatabase", "电子能级库")):
        if key in settings:
            lines.append(f"- {label} `{settings[key]}`。")
    for i in range(1, int(settings.get("DSMC-NumOfReactions", "0")) + 1):
        reaction = f"DSMC-Reaction{i}-"
        sides = []
        for role in ("Reactants", "Products"):
            indices = map(int, re.findall(r"\d+", settings.get(reaction + role, "")))
            sides.append(" + ".join(species.get(index, str(index)) for index in indices if index))
        lines.append(f"- 反应 {i}（`{settings.get(reaction + 'ReactionModel', '见输入')}`）"
                     f" {sides[0]} → {sides[1]}。")
    conversion = real(settings.get("Particles-He2-ThreeBodyRate", "0"))
    if conversion:
        lines.append(f"- 固定背景气体蒙特卡洛转化 He⁺ + 2He → He₂⁺ + He，系数 {conversion:.4g} m⁶/s。")
    if metal_he2_yield is None and (conversion or settings.get("Particles-JiaChemistry") == "T"):
        lines.append(f"- 钨针 He₂⁺ 有效发射产额 `{settings.get('Particles-He2-ElectrodeYield', '见输入')}`。")
    if settings.get("Particles-JiaChemistry") == "T":
        lines.append("- 启用 Jia 六物种反应。R1–R3 走背景气体截面，R4–R23 的系数和产物见反应清单。")
        if (directory / "JiaReactionCounts_rank0.csv").is_file():
            lines.append("- `JiaReactionCounts_rank*.csv` 按进程记录时间、R1–R23 累计加权事件数与最大单对反应强度。")
        for limitation in metadata.get("limitations", []):
            lines.append(f"- {limitation}")
    collision = [line.strip(" |\n") for line in log_text.splitlines()
                 if re.search(r": Found\s+.*(?:collision|excitation) cross section", line)]
    if collision:
        lines.extend(["", "求解日志记录的截面通道", "", *[f"- `{item}`" for item in collision]])

    lines.extend(["", "## 边界条件", ""])
    field = {"BC_HV": "指定脉冲电势", "BC_Ground": "电势 0 V",
             "BC_Outer": "零法向电场", "BC_Quartz": "氦气—石英介质界面",
             "BC_Axis": "轴对称", "BC_Sym": "降维对称"}
    overrides = [value for key, value in parameters if key == "BoundaryName"]
    override_types = [value for key, value in parameters if key == "BoundaryType"]
    field.update({name: f"场边界类型 `{value}`" for name, value in zip(overrides, override_types)})
    for i in range(1, int(settings.get("Part-nBounds", "0")) + 1):
        boundary = f"Part-Boundary{i}-"
        name = settings[boundary + "SourceName"]
        condition = settings[boundary + "Condition"]
        items = [f"粒子边界 `{condition}`"]
        if name in field:
            items.insert(0, field[name])
        absorbed = [species[int(match[1])] for key, value in parameters
                    if key.startswith(boundary + "SpeciesSwaps")
                    and (match := re.fullmatch(r"\(/\s*(\d+)\s*,\s*0\s*/\)", value))]
        if absorbed:
            items.append("吸收 " + "、".join(absorbed))
        if settings.get(boundary + "Dielectric") == "T":
            items.append("动态壁面电荷沉积")
        model = settings.get(boundary + "SurfaceModel")
        if model:
            items.append(f"表面模型 {model}")
        if model == "7":
            for suffix, label in (("SurfModEmissionYield", "He⁺ 诱导电子产额" if metal_he2_yield is not None else "离子诱导电子产额"),
                                  ("SurfModElectronReflection", "电子镜面反射概率"),
                                  ("SurfModEnergyDistribution", "发射能谱"),
                                  ("SurfModEmissionEnergy", "发射能量参数（eV）")):
                if boundary + suffix in settings:
                    items.append(f"{label} {settings[boundary + suffix]}")
            if metal_he2_yield is not None:
                he2_yield = (settings.get("Particles-He2-QuartzYield", settings.get(boundary+"SurfModEmissionYield"))
                             if settings.get(boundary+"Dielectric") == "T" else metal_he2_yield)
                items.append(f"He₂⁺ 诱导电子产额 {he2_yield}")
        if model == "11":
            items.append("电子总返回产额 δ(E)=0.8+0.2E/35（E 以 eV 计），含背散射和二次发射，He⁺ 吸收")
        lines.append(f"- `{name}` · " + "，".join(items) + "。")

    lines.extend(["", "## 初始粒子", ""])
    for i, name in species.items():
        prefix = f"Part-Species{i}-"
        count = int(settings.get(prefix + "nInits", "0"))
        weight = settings.get(prefix + "MacroParticleFactor")
        lines.append(f"- {name}，{count} 个初始化区域，宏粒子权重 {weight or '见输入'}。")
        for j in range(1, count + 1):
            initial = f"{prefix}Init{j}-"
            parts = [f"区域 {j} `{settings.get(initial + 'SpaceIC', '见输入')}`"]
            for key, label in (("PartDensity", "数密度（m⁻³）"), ("ParticleNumber", "宏粒子数"),
                               ("BasePointIC", "起点（m）"), ("RadiusIC", "半径（m）"),
                               ("CylinderHeightIC", "柱长（m）"), ("CuboidHeightIC", "块长（m）"),
                               ("MWTemperatureIC", "温度（K）"), ("velocityDistribution", "速度分布")):
                if initial + key in settings:
                    parts.append(f"{label} `{settings[initial + key]}`")
            if settings.get(initial + "SpaceIC") == "cuboid":
                parts.extend(f"底边向量 {k}（m） `{settings[initial + f'BaseVector{k}IC']}`"
                             for k in (1, 2) if initial + f"BaseVector{k}IC" in settings)
            if weight and initial + "ParticleNumber" in settings:
                physical_count = real(weight) * real(settings[initial + "ParticleNumber"])
                parts.append(f"折合 {physical_count:.7g} 个实际粒子")
            lines.append("  - " + "，".join(parts) + "。")
    charged = metadata.get("initial_charged_density_m3")
    if charged:
        values = "、".join(f"{label} {charged[key]:.5g}" for key, label in (("e", "e⁻"), ("He+", "He⁺"), ("He2+", "He₂⁺")))
        lines.append(f"- 带电粒子初始数密度（m⁻³） {values}。")
    elif metadata.get("seed_density_m3") and int(settings.get("Part-Species3-nInits", "0")):
        lines.append(f"- 记录的预电离密度 {metadata['seed_density_m3']:.4g} m⁻³。")
    random = [value for key, value in parameters if re.fullmatch(r"Particles-RandomSeed\d+", key)]
    if random:
        lines.append("- 随机种子 " + "、".join(random) + "。")

    lines.extend(["", "## 原始输入和复现记录", ""])
    for name in ("parameter.ini", "DSMC.ini", "REACTIONS.md", "INITIAL_STATE_VALIDATION.md", "review-checks.json",
                 "CHEMISTRY_PLAN.json", "R15_SOURCE_REVIEW.md",
                 "geometry.json", "mesh.ini", "hopr.ini", "case-info.json",
                 "input-sha256.txt", "input-sha256.json",
                 "literature-review.txt", "run-info.txt", "solver-sha256.txt", "solver-source.patch", "SOLVER_SETUP.md"):
        if (directory/name).is_file():
            lines.append(f"- [{name}]({name})")
    if log:
        lines.append(f"- [{log.name}]({log.name})")
    return "\n".join(lines) + "\n"


def record(directory):
    path = directory / "MODEL_SETTINGS.md"
    temporary = path.with_suffix(".md.tmp")
    temporary.write_text(settings_text(directory), encoding="utf-8")
    temporary.replace(path)
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directories", nargs="+", type=Path)
    for directory in parser.parse_args().directories:
        print(record(directory))
