"""Local data and rendering bridge for the VS Code workbench."""
import base64
from io import BytesIO
import json
import math
import shutil
import sys

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from case_preflight import describe_case, fingerprints
from record_model_settings import entries, record
from tube_cases import (
    AXIS_MESH_FIELDS, AXIS_MESH_PRESETS, DIAMETERS, TUBE_FIELDS, axis_mesh_values, configure_taper, format_length,
    new_case_directory, particle_search_parameters, plan_axisymmetric_tube, read_geometry, replace_parameters,
    seed_parameters,
)
from workbench import (
    FIELDS, NITROGEN, PARAMETERS, ROOT, case_info, frame_stamp, launch_paraview,
    make_series, parameter_values,
)
from slice_plot import render_slice


JIA_SEED_SPECIES = ((3, "e", "电子 e⁻"), (2, "He+", "He⁺"), (4, "He2+", "He₂⁺"))
JIA_EMISSION_FIELDS = (
    ("tungsten_he", "两根钨针 He⁺ γ", ("Part-Boundary1-SurfModEmissionYield", "Part-Boundary2-SurfModEmissionYield")),
    ("tungsten_he2", "两根钨针 He₂⁺ γ", ("Particles-He2-MetalYield",)),
    ("quartz_he", "石英壁 He⁺ γ", ("Part-Boundary3-SurfModEmissionYield",)),
    ("quartz_he2", "石英壁 He₂⁺ γ", ("Particles-He2-QuartzYield",)),
)


def jia_seed_volume(params, species):
    prefix = f"Part-Species{species}-Init1-"
    return math.pi*float(params[prefix+"RadiusIC"])**2*float(params[prefix+"CylinderHeightIC"])


def jia_initial_fields(params):
    if "Particles-He2-MetalYield" not in params:
        return []
    fields = []
    for species, name, label in JIA_SEED_SPECIES:
        prefix = f"Part-Species{species}-"
        count = int(params[prefix+"Init1-ParticleNumber"]) if params[prefix+"nInits"] == "1" else 0
        density = count*float(params[prefix+"MacroParticleFactor"])/jia_seed_volume(params, species)
        fields.append({"id": name, "label": f"{label} 初始密度 (m⁻³)", "value": float(f"{density:.12g}")})
    fields.extend({"id": name, "label": label, "value": float(params[keys[0]])}
                  for name, label, keys in JIA_EMISSION_FIELDS if keys[0] in params)
    return fields


def relative(directory):
    return directory.relative_to(ROOT).as_posix() if directory != NITROGEN else "nitrogen"


def directory_for(key):
    if key == "nitrogen":
        return NITROGEN
    directory = (ROOT/key).resolve()
    if not directory.is_relative_to(ROOT) or not (directory/"parameter.ini").is_file():
        raise ValueError("找不到所选算例。")
    return directory


def mesh_ready(directory):
    snapshot = directory/"mesh-geometry.json"
    return ((directory/"helium_mesh.h5").is_file() and snapshot.is_file()
            and snapshot.read_bytes() == (directory/"geometry.json").read_bytes())


def run_status(directory):
    for name in ("run-status.txt", "job-status.txt"):
        path = directory/name
        if path.is_file():
            return path.read_text().strip()
    return ""


def catalog():
    models = []
    runs = [{"id": "nitrogen", "label": "氮气 · 原负流注", "case": None}]
    for directory in sorted((ROOT/"cases").iterdir()):
        if not (directory/"geometry.json").is_file() or not (directory/"parameter.ini").is_file():
            continue
        geometry = read_geometry(directory/"geometry.json")
        metadata = case_info(directory)
        label = metadata.get("display_name", directory.name)
        model_id = relative(directory)
        case_runs = {run: run_status(run) for run in sorted((directory/"runs").glob("*"), reverse=True)
                     if run.is_dir()}
        if geometry.get("mesh_method") == "axisymmetric":
            formal_runs = sum(state == "complete" and "-research-" in run.name for run, state in case_runs.items())
            delete_block = ""
            if "running" in case_runs.values():
                delete_block = "此算例正在运行。"
            elif metadata.get("protect_from_deletion", False):
                delete_block = "此算例已标为关键算例。"
            models.append({"id": model_id, "label": f"D {format_length(geometry['tube_bore_um'])} · {label}",
                           "ready": mesh_ready(directory), "review": metadata.get("review_pending", False),
                           "draft": metadata.get("network_status") == "draft",
                           "deletable": not delete_block, "deleteBlock": delete_block,
                           "runCount": len(case_runs), "formalRunCount": formal_runs,
                           "validation": not metadata.get("cloned_from") and (
                               "Static" in directory.name or bool(metadata.get("mesh_reference") and not
                                                                  geometry.get("needle_shape")))})
        for run, state in case_runs.items():
            if not any(run.glob("*_State_0*.h5")):
                continue
            valid = not (run/"run-validation.txt").is_file()
            kind = next((kind for kind in ("field-check", "pilot", "smoke") if f"-{kind}-" in run.name), "")
            complete = state == "complete"
            if not valid:
                prefix = "无效 · "
            elif state == "running":
                prefix = "运行中 · "
            elif state == "snapshot":
                prefix = "运行快照 · "
            elif state == "failed":
                prefix = "运行失败 · "
            elif not complete:
                prefix = "未完成 · "
            else:
                prefix = {"field-check": "静电 · ", "pilot": "短验证 · ", "smoke": "短验证 · "}.get(kind, "")
            runs.append({"id": relative(run), "case": model_id, "validation": bool(kind) or not valid
                         or state not in ("running", "complete", "snapshot"),
                         "deletable": state != "running" and (not valid or (complete and bool(kind))),
                         "label": f"{prefix}{label} · {run.name}"})
    pointer = ROOT/"latest-result.txt"
    latest = pointer.read_text(encoding="utf-8").strip() if pointer.is_file() else ""
    latest = next((item["id"] for item in runs if latest in (item["id"], str(ROOT/item["id"]))), None)
    return {"models": models, "runs": runs, "latest": latest,
            "meshPresets": AXIS_MESH_PRESETS, "diameters": DIAMETERS}


def frames(directory):
    return sorted(directory.glob("*_State_0*.h5"), key=frame_stamp)


def self_check(key):
    directory = directory_for(key)
    return describe_case(directory, directory != NITROGEN and mesh_ready(directory))


def describe(key):
    directory = directory_for(key)
    geometry = read_geometry(directory/"geometry.json") if directory != NITROGEN else None
    values = parameter_values(directory/"parameter.ini")
    inputs = dict(entries((directory/"parameter.ini").read_text(encoding="utf-8-sig")))
    summary_file = directory/"pulse-summary.json"
    summary = json.loads(summary_file.read_text(encoding="utf-8")) if summary_file.is_file() else {}
    case = directory.parent.parent if directory.parent.name == "runs" else directory
    taper_controls = None
    if geometry:
        radius = geometry["tip_radius_um"]
        bore = geometry["tube_bore_um"]
        shaft = 5*radius if 5*radius < bore else (2*radius+bore)/2
        taper_controls = {
            "needle_shape": geometry.get("needle_shape", "hemisphere"),
            "shaft_diameter_um": geometry.get("shaft_diameter_um", shaft),
            "cone_half_angle_deg": geometry.get("cone_half_angle_deg", 30.),
        }
    return {
        "geometry": geometry, "frames": [frame_stamp(frame)*1e9 for frame in frames(directory)],
        "meshControls": axis_mesh_values(geometry["mesh_settings"])
                        if geometry and geometry.get("mesh_method") == "axisymmetric" else None,
        "taperControls": taper_controls,
        "taperFields": [{"id": "shaft_diameter_um", "label": "针杆直径 (μm)"},
                        {"id": "cone_half_angle_deg", "label": "锥半角 (°)"}],
        "assessment": summary.get("assessment", ""), "invalid": (directory/"run-validation.txt").is_file(),
        "settingsAvailable": (directory/"MODEL_SETTINGS.md").is_file(),
        "reactionsAvailable": (directory/"REACTIONS.md").is_file(),
        "vtuAvailable": any(directory.glob("*_Solution_*.vtu")),
        "modelAvailable": (case/"model"/"helium_geometry.vtm").is_file(),
        "parameters": [{"id": k, "label": title, "value": round(values[k]*scale, 12)}
                       for k, (title, scale) in PARAMETERS.items() if k in values],
        "initialFields": jia_initial_fields(inputs),
        "geometryFields": [{"id": key, "label": title + " (μm)"} for key, title in TUBE_FIELDS] +
                          [{"id": "tip_radius_um", "label": "针尖半径 (μm)"}],
        "meshFields": [{"id": key, "label": title, "integer": dtype is int}
                       for key, title, dtype in AXIS_MESH_FIELDS],
    }


def draft_geometry(values, mesh):
    sizes = {key: float(values[key]) for key, _ in TUBE_FIELDS}
    controls = {key: float(mesh[key]) for key, _, _ in AXIS_MESH_FIELDS}
    geometry = plan_axisymmetric_tube(sizes, float(values["tip_radius_um"]), controls)
    for key, _, dtype in AXIS_MESH_FIELDS:
        if key in geometry["mesh_settings"]:
            geometry["mesh_settings"][key] = dtype(controls[key])
    if values.get("needle_shape") == "tapered":
        configure_taper(geometry, float(values["shaft_diameter_um"]), float(values["cone_half_angle_deg"]))
    return geometry


def render(key, field, index, draft=None, mesh_overlay=False, equal=False, color=None, focus="full", clean=False):
    directory = directory_for(key)
    if field not in FIELDS.values():
        raise ValueError("请选择可用的场量。")
    geometry = None
    if directory == NITROGEN:
        mesh = directory/"streamer_mesh.h5"
    else:
        geometry = read_geometry(directory/"geometry.json")
        mesh = directory/"helium_mesh.h5"
    frame = None
    if draft:
        geometry = draft_geometry(draft["geometry"], draft["mesh"])
        mesh = None
        field = ""
    elif field:
        states = frames(directory)
        frame = states[index] if 0 <= index < len(states) else None
    if mesh and not mesh.is_file():
        mesh = None
    summary = directory/"pulse-summary.json"
    limits = (None, None)
    color = color or {}
    mode = color.get("scale", "auto")
    logarithmic = mode == "log" or (mode == "auto" and field == "ElectronDensityCell")
    if frame and field == "ElectronDensityCell" and mode == "auto" and summary.is_file():
        values = json.loads(summary.read_text(encoding="utf-8"))
        if values["density_max_m3"] > 0:
            limits = (values["density_scale_min_m3"], values["density_max_m3"])
    if frame and color.get("manual"):
        limits = tuple(float(color[bound]) for bound in ("low", "high"))
    width = 5.4 if equal and focus in ("hv-tip", "ground-tip") else 6.7
    figure = Figure(figsize=(width, 5.9), dpi=190 if clean else 115, facecolor="white")
    canvas = FigureCanvasAgg(figure)
    title = next(label for label, value in FIELDS.items() if value == field)
    render_slice(figure, title if frame else "几何与材料", geometry, mesh, frame, field,
                 logarithmic, limits, True, True, equal, mesh_overlay, focus, clean)
    png = BytesIO()
    if clean:
        canvas.draw()
        crop = figure.axes[0].get_window_extent().transformed(figure.dpi_scale_trans.inverted())
        canvas.print_figure(png, format="png", bbox_inches=crop, pad_inches=0)
    else:
        canvas.print_png(png)
    return base64.b64encode(png.getvalue()).decode("ascii")


def resize_seed(text, old, new, metadata):
    if metadata.get("study") != "uniform_gap_seed_and_tungsten_effective_emission":
        return seed_parameters(text, new)
    values = {}
    updated = {}
    jia_initial = metadata.get("quartz_wall_model") == "ion_induced_see"
    seed_species = ((2, 3, 4, 5, 6) if jia_initial else
                    (2, 3, 5, 6) if metadata.get("network_status") == "ready" and "Particles-JiaChemistry = T" in text else (2, 3))
    allowed_inits = ("0", "1") if jia_initial else ("1",)
    for species in seed_species:
        prefix = f"Part-Species{species}-"
        original = {line.split("=", 1)[0].strip(): line.split("=", 1)[1].split("!")[0].strip()
                    for line in text.splitlines() if line.startswith(prefix) and "=" in line}
        if original.get(prefix+"Init1-SpaceIC") != "cylinder" or original.get(prefix+"nInits") not in allowed_inits:
            raise ValueError("这个算例的种子区域已自定义，请在参数文件中设置新几何对应的种子。")
        radius = float(original[prefix+"Init1-RadiusIC"])*new["tube_bore_um"]/old["tube_bore_um"]
        length = float(original[prefix+"Init1-CylinderHeightIC"])*new["tip_gap_um"]/old["tip_gap_um"]
        start = float(original[prefix+"Init1-BasePointIC"].strip("()/").split(",")[0])
        start *= new["tip_gap_um"]/old["tip_gap_um"]
        weight = float(original[prefix+"MacroParticleFactor"])
        weight *= (new["tube_bore_um"]/old["tube_bore_um"])**2*new["tip_gap_um"]/old["tip_gap_um"]
        values.update({prefix+"Init1-RadiusIC": f"{radius:.13g}",
                       prefix+"Init1-CylinderHeightIC": f"{length:.13g}",
                       prefix+"Init1-BasePointIC": f"(/{start:.13g},0.,0./)",
                       prefix+"MacroParticleFactor": f"{weight:.13g}"})
        if species == 3:
            updated = dict(seed_radius_m=radius, seed_length_m=length, seed_start_x_m=start, seed_weight=weight)
    metadata.update(updated)
    return replace_parameters(text, values)


def configure_jia_initial(text, requested, metadata):
    params = dict(entries(text))
    defaults = jia_initial_fields(params)
    if not defaults:
        return text
    values = {item["id"]: item["value"] for item in defaults}
    values.update({key: value for key, value in (requested or {}).items() if key in values})
    for item in defaults:
        value = values[item["id"]]
        if value is None or not math.isfinite(value) or value < 0.0:
            raise ValueError(f"{item['label']}须为有限非负数。")
    if values["tungsten_he2"] > 1.0:
        raise ValueError("钨针 He₂⁺ 发射系数不能超过 1。")
    changes = {}
    densities = {}
    for species, name, _ in JIA_SEED_SPECIES:
        density = values[name]
        prefix = f"Part-Species{species}-"
        changes[prefix+"nInits"] = "1" if density else "0"
        weight_key = prefix+"MacroParticleFactor"
        if density:
            count = int(params[prefix+"Init1-ParticleNumber"])
            weight = density*jia_seed_volume(params, species)/count
            if not math.isfinite(weight) or weight <= 0:
                raise ValueError(f"{name} 初始密度无法换算为有效的宏粒子权重。")
            changes[weight_key] = f"{weight:.16g}"
        if name == "e":
            metadata["seed_weight"] = float(changes.get(weight_key, params[weight_key]))
        densities[name] = density
    for name, _, keys in JIA_EMISSION_FIELDS:
        if name in values:
            changes.update({key: f"{values[name]:.16g}" for key in keys})
    quartz_he2 = values.get("quartz_he2", values["quartz_he"])
    metadata.update(
        seed_density_m3=densities["e"], initial_charged_density_m3=densities,
        ion_induced_yield=values["tungsten_he"], molecular_ion_induced_yield=values["tungsten_he2"],
        quartz_ion_induced_yield={"He+": values["quartz_he"], "He2+": quartz_he2},
    )
    return replace_parameters(text, changes)


def clone(key, draft, parameters, initial=None):
    source = directory_for(key)
    if source.parent != ROOT/"cases":
        raise ValueError("请选择一个二维氦气算例作为模板。")
    original = read_geometry(source/"geometry.json")
    if original.get("mesh_method") != "axisymmetric":
        raise ValueError("请选择一个二维轴对称算例。")
    proposed = draft_geometry(draft["geometry"], draft["mesh"])
    same_domain = all(proposed[k] == original[k] for k in ("tube_bore_um", "tube_outer_um", "tip_gap_um",
                                                          "domain_length_um"))
    same_needle = all(proposed.get(k) == original.get(k) for k in ("tip_radius_um", "needle_shape",
                                                                  "shaft_diameter_um", "cone_half_angle_deg"))
    same_dimensions = same_domain and same_needle
    same_mesh = same_dimensions and proposed["mesh_settings"] == original["mesh_settings"]
    geometry = original if same_mesh else proposed
    text = (source/"parameter.ini").read_text(encoding="ascii")
    active = parameter_values(source/"parameter.ini")
    values = {key: float(parameters[key])/PARAMETERS[key][1] for key in active}
    if any(not math.isfinite(value) or value < 0 or (value == 0 and key != "PulseFlat")
           for key, value in values.items()):
        raise ValueError("参数须为有限正数，平顶时长可为零。")
    values["tend"] = sum(values[key] for key in ("PulseRise", "PulseFlat", "PulseFall"))
    replacements = {key: f"{value:.13g}" for key, value in values.items()}
    replacements["DielectricZoneEpsR"] = f"(/ {replacements['DielectricZoneEpsR']} /)"
    text = replace_parameters(text, replacements)
    metadata = case_info(source)
    if not same_domain:
        text = particle_search_parameters(resize_seed(text, original, geometry, metadata), geometry)
    text = configure_jia_initial(text, initial, metadata)
    case = new_case_directory(ROOT, geometry)
    metadata.pop("protect_from_deletion", None)
    metadata.update(display_name=case.name, cloned_from=relative(source))
    (case/"parameter.ini").write_text(text, encoding="ascii")
    geometry_text = ((source/"geometry.json").read_text(encoding="utf-8") if same_mesh
                     else json.dumps(geometry, indent=2) + "\n")
    (case/"geometry.json").write_text(geometry_text, encoding="utf-8")
    (case/"case-info.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shutil.copy2(source/"DSMC.ini", case/"DSMC.ini")
    for database in ("XSec_Database_He_Plasma.h5", "Electronic-State-Database.h5"):
        if (source/database).is_file():
            shutil.copy2(source/database, case/database)
    if (source/"literature-review.txt").is_file():
        shutil.copy2(source/"literature-review.txt", case/"literature-review.txt")
    for filename in ("REACTIONS.md", "CHEMISTRY_PLAN.json", "R15_SOURCE_REVIEW.md",
                     "solver-source.patch", "SOLVER_SETUP.md", "build_solver.sh"):
        if (source/filename).is_file():
            shutil.copy2(source/filename, case/filename)
    if same_mesh and mesh_ready(source):
        for filename in ("helium_mesh.h5", "mesh-geometry.json", "mesh.ini"):
            if (source/filename).is_file():
                shutil.copy2(source/filename, case/filename)
        if (source/"model").is_dir():
            shutil.copytree(source/"model", case/"model")
    if metadata.get("quartz_wall_model") == "ion_induced_see":
        (case/"input-sha256.json").write_text(json.dumps(fingerprints(case), indent=2) + "\n", encoding="utf-8")
    record(case)
    return relative(case)


def paraview(key, field, geometry=False):
    directory = directory_for(key)
    if geometry:
        case = directory.parent.parent if directory.parent.name == "runs" else directory
        model = case/"model"/"helium_geometry.vtm"
        if not model.is_file():
            raise ValueError("请先生成该算例的网格。")
        launch_paraview(model)
    else:
        launch_paraview(make_series(directory, field))


if __name__ == "__main__":
    methods = {"catalog": catalog, "describe": describe, "render": render, "clone": clone,
               "paraview": paraview, "selfCheck": self_check}
    for line in sys.stdin:
        request = json.loads(line)
        response = {"id": request["id"]}
        try:
            response["result"] = methods[request["method"]](**request.get("args", {}))
        except (ValueError, TypeError, OSError, KeyError, IndexError, RuntimeError) as error:
            response["error"] = str(error)
        print(json.dumps(response, ensure_ascii=False), flush=True)
