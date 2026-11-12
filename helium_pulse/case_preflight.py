"""Report the frozen input and chemistry used by a model or run."""
import hashlib
import json
import h5py

from record_model_settings import entries


INPUTS = ("parameter.ini", "DSMC.ini", "geometry.json", "helium_mesh.h5",
          "XSec_Database_He_Plasma.h5", "Electronic-State-Database.h5", "CHEMISTRY_PLAN.json")
SPECIES = {"electron": "e⁻", "HeIon1": "He⁺", "He2Ion1": "He₂⁺", "HeMeta": "He*", "He2Meta": "He₂*"}


def fingerprints(directory):
    result = {}
    for name in INPUTS:
        path = directory/name
        if path.is_file():
            with path.open("rb") as stream:
                result[name] = hashlib.file_digest(stream, "sha256").hexdigest()
    return result


def json_file(path):
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else {}


def validate_plan(plan):
    species = plan["species"]
    ids = [row["id"] for row in plan["reactions"]]
    if ids != list(range(1, 24)):
        raise ValueError("Jia 气相反应编号必须覆盖 1 至 23。")
    for row in plan["reactions"]:
        left, right = row["reactants"], row["products"]
        if not left or not right:
            raise ValueError(f"R{row['id']} 缺少反应物或产物。")
        for key in ("he_atoms", "charge"):
            if sum(species[s][key] for s in left) != sum(species[s][key] for s in right):
                raise ValueError(f"R{row['id']} 的氦原子数或电荷不守恒。")
        if row["rate"]["kind"] != "cross_section":
            expected = {1: "s⁻¹", 2: "m³/s", 3: "m⁶/s"}[len(left)]
            if row["rate"]["unit"] != expected:
                raise ValueError(f"R{row['id']} 反应阶数与速率单位不一致。")


def describe_case(directory, geometry_ready):
    info = json_file(directory/"case-info.json")
    plan = json_file(directory/"CHEMISTRY_PLAN.json")
    params = dict(entries((directory/"parameter.ini").read_text(encoding="utf-8-sig")))
    dsmc = directory/"DSMC.ini"
    params.update(entries(dsmc.read_text(encoding="utf-8-sig")) if dsmc.is_file() else [])
    names = [params.get(f"Part-Species{i}-SpeciesName", f"物种 {i}")
             for i in range(1, int(params.get("Part-nSpecies", "0"))+1)]
    names = [SPECIES.get(name, name) for name in names]
    run = (directory/"run-info.txt").is_file()
    hashes = fingerprints(directory)
    expected = json_file(directory/"input-sha256.json")
    checksum_file = directory/"input-sha256.txt"
    if checksum_file.is_file():
        expected = {name: digest for digest, name in
                    (line.split(maxsplit=1) for line in checksum_file.read_text().splitlines())}
    changed = [name for name, digest in expected.items() if hashes.get(name) != digest]
    checks = [
        {"label": "数据来源", "value": "运行目录输入快照" if run else "算例目录当前输入"},
        {"label": "求解物种", "value": "、".join(names) or "未读取到物种名称"},
        {"label": "网格", "value": ("已保存运行网格" if "helium_mesh.h5" in hashes else "缺少运行网格") if run
         else ("几何与网格快照一致" if geometry_ready else "需要生成或核对网格")},
        {"label": "输入指纹", "value": "、".join(changed)+" 已改变" if changed else
         ("与保存的 SHA-256 一致" if expected else "已计算当前 SHA-256")},
    ]
    blocked = bool(info.get("review_pending") or info.get("network_status") == "draft" or changed)
    if plan:
        validate_plan(plan)
        checks.append({"label": "拟用网络", "value": f"{len(plan['species'])} 个物种，{len(plan['reactions'])} 条体反应，氦原子数和电荷检查通过"})
        if plan["hold_reason"]:
            checks.append({"label": "启动状态", "value": plan["hold_reason"]})
            blocked = True
    if run:
        state = next((directory/name for name in ("job-status.txt", "run-status.txt") if (directory/name).is_file()), None)
        checks.append({"label": "运行状态", "value": state.read_text().strip() if state else "状态待写入"})

    reactions = []
    if "XSec_Database_He_Plasma.h5" in hashes:
        with h5py.File(directory/"XSec_Database_He_Plasma.h5") as db:
            def collect(path, dataset):
                if isinstance(dataset, h5py.Dataset):
                    threshold = dataset.attrs.get("Threshold [eV]")
                    energy = f" · {float(threshold):g} eV" if threshold is not None else ""
                    reactions.append({"name": path, "detail": "截面库"+energy})

            db.visititems(collect)
    for index in range(1, int(params.get("DSMC-NumOfReactions", "0"))+1):
        prefix = f"DSMC-Reaction{index}-"
        reactions.append({"name": f"DSMC {index} · {params.get(prefix+'ReactionModel', '')}",
                          "detail": f"{params.get(prefix+'Reactants', '')} → {params.get(prefix+'Products', '')}"})
    conversion = params.get("Particles-He2-ThreeBodyRate")
    if conversion and float(conversion) > 0:
        reactions.append({"name": "He⁺ + 2He → He₂⁺ + He", "detail": f"定制 MCC · {conversion} m⁶/s"})

    surfaces = []
    for i in range(1, int(params.get("Part-nBounds", "0"))+1):
        prefix = f"Part-Boundary{i}-"
        name = params.get(prefix+"SourceName")
        if not name:
            continue
        details = [params.get(prefix+"Condition", "")]
        if params.get(prefix+"Dielectric") == "T":
            details.append("动态介质充电")
        for key, label in (("SurfaceModel", "表面模型"), ("SurfModEmissionYield", "He⁺ γ"),
                           ("SurfModElectronReflection", "电子反射概率")):
            if prefix+key in params:
                details.append(f"{label} {params[prefix+key]}")
        if params.get(prefix+"SurfaceModel") == "7":
            molecular_yield = params.get("Particles-He2-ElectrodeYield")
            if "Particles-He2-MetalYield" in params:
                molecular_yield = (params.get("Particles-He2-QuartzYield", params.get(prefix+"SurfModEmissionYield"))
                                   if params.get(prefix+"Dielectric") == "T"
                                   else params["Particles-He2-MetalYield"])
            if molecular_yield is not None:
                details.append(f"He₂⁺ γ {molecular_yield}")
        swaps = [value for key, value in params.items() if key.startswith(prefix+"SpeciesSwaps")]
        if swaps:
            details.append("物种转换 " + "、".join(swaps))
        surfaces.append({"name": name, "detail": " · ".join(details)})
    return {"checks": checks, "reactions": reactions, "surfaces": surfaces, "hashes": hashes,
            "blocked": blocked, "draft": info.get("network_status") == "draft",
            "planned": plan.get("reactions", []), "plannedSurfaces": plan.get("surface_reference", {})}
