"""Local data and rendering bridge for the VS Code workbench."""
import base64
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import re
import shutil
import sys
from tempfile import TemporaryDirectory

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from adaptive_weight_settings import (
    CASE as ADAPTIVE_CASE, MERGE_FIELDS, case_settings, editor_fields, save_settings, settings_for,
    validate, weight_parameters, write_weight_parameters,
)
from case_preflight import describe_case, fingerprints
from piclas_ini import parse_parameters, real
from record_model_settings import record, settings_text
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
    return math.pi*real(params[prefix+"RadiusIC"])**2*real(params[prefix+"CylinderHeightIC"])


def jia_initial_fields(params):
    if "Particles-He2-MetalYield" not in params:
        return []
    fields = []
    for species, name, label in JIA_SEED_SPECIES:
        prefix = f"Part-Species{species}-"
        count = int(params[prefix+"Init1-ParticleNumber"]) if params[prefix+"nInits"] == "1" else 0
        density = count*real(params[prefix+"MacroParticleFactor"])/jia_seed_volume(params, species)
        fields.append({"id": name, "label": f"{label} 初始密度 (m⁻³)", "value": float(f"{density:.12g}")})
    fields.extend({"id": name, "label": label, "value": real(params[keys[0]])}
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


def conversion_status(directory):
    path = directory/"conversion-status.txt"
    return path.read_text(encoding="utf-8").strip() if path.is_file() else ""


def run_delete_block(state, removable):
    if state == "running":
        return "此运行正在求解。"
    return "" if removable else "此运行结果已保留。"


def adaptive_weight_settings():
    case = ROOT/ADAPTIVE_CASE
    script = case/"run_short.sh"
    values = settings_for(case) if script.is_file() else None
    return {"fields": editor_fields(values) if values else [],
            "mergeFields": editor_fields(values, MERGE_FIELDS) if values else [],
            "script": relative(script), "ready": (case/"solver-sha256.txt").is_file()}


def save_adaptive_weight(settings):
    return save_settings(ROOT/ADAPTIVE_CASE, settings)


def complete_log_tail(path):
    """Read recent complete lines without loading growing diagnostics files."""
    try:
        with path.open("rb") as stream:
            offset = max(0, stream.seek(0, 2) - 32768)
            stream.seek(offset)
            lines = stream.read(32768).split(b"\n")
    except FileNotFoundError:
        return ""
    return b"\n".join(lines[bool(offset):-1]).decode("ascii", errors="replace")


def run_progress(key=None):
    cases = ROOT/"cases"
    adaptive_runs = ROOT/ADAPTIVE_CASE/"runs"
    previous = (ROOT/key).resolve() if key else None
    if previous and previous.parent != adaptive_runs and (
        previous.parent.name != "runs" or previous.parent.parent.parent != cases
    ):
        previous = None
    state = run_status(previous) if previous else ""
    run = previous if state == "running" else max(
        (item for pattern in ("cases/*/runs/*", (ADAPTIVE_CASE/"runs/*").as_posix())
         for item in ROOT.glob(pattern) if item.is_dir() and run_status(item) == "running"),
        key=lambda item: item.name, default=None,
    )
    if run:
        state = "running"
    elif previous and state in {"complete", "failed", "stopped"}:
        run = previous
    else:
        return None

    case = run.parent.parent
    label = case_info(run if run.parent == adaptive_runs else case).get("display_name", case.name)
    run_info = run/"run-info.txt"
    start_time = real(parse_parameters(run_info.read_text()).get("restart_time_ns", "0"))*1e-9 if run_info.is_file() else 0.
    parameter_file = run/"parameter.ini"
    params = parameter_file.read_text(encoding="utf-8-sig") if parameter_file.is_file() else ""
    number = r"[0-9.EeDd+\-]+"
    end_match = re.search(rf"(?im)^[ \t]*tend[ \t]*=[ \t]*({number})", params)
    end = float(end_match[1].lower().replace("d", "e")) if end_match else None
    log = run/"solver.log"
    analysis = run/"PartAnalyze.csv"
    tail = complete_log_tail(log)
    stamps = re.findall(rf"(?im)^[ \t]*(?:iter:\s*\d+\s*time:|sim time\s*:)\s*({number})", tail)
    stamps += re.findall(rf"(?m)^[ \t]*({number}),", complete_log_tail(analysis))[-1:]
    current = max((float(stamp.lower().replace("d", "e")) for stamp in stamps), default=start_time)
    eta = None
    if end and end > start_time:
        current = end if state == "complete" else min(current, end)
        if state == "running" and current >= end * (1. - 1e-10):
            state = "saving"
        elif state == "running" and current > start_time:
            reports = re.findall(rf"(?im)^[ \t]*Time[ \t]*=[ \t]*({number})[^\n]*?\beta[ \t]*=[ \t]*([0-9:]+)", tail)
            if reports:
                stamp, duration = reports[-1]
                remaining = end - float(stamp.lower().replace("d", "e"))
                seconds = sum(int(part) * scale for part, scale in
                              zip(reversed(duration.split(":")), (1, 60, 3600, 86400)))
                if remaining > 0:
                    eta = seconds * (end - current) / remaining
            if eta is None:
                if run_info.is_file():
                    latest = max(p.stat().st_mtime for p in (run_info, log, analysis) if p.is_file())
                    elapsed = latest - run_info.stat().st_mtime
                    if elapsed > 0:
                        eta = elapsed * (end - current) / (current - start_time)
    else:
        end = None
    return {"id": relative(run), "label": label, "state": state, "currentNs": current*1e9,
            "conversionStatus": conversion_status(run),
            "endNs": end*1e9 if end else None,
            "percent": max(0., (current-start_time)/(end-start_time)*100) if end else None,
            "etaSeconds": round(eta) if eta is not None else None}


def catalog():
    models = []
    runs = [{"id": "nitrogen", "label": "氮气 · 原负流注", "case": None,
             "deleteBlock": "原始氮气结果受保护。"}]
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
            elif (directory/".parameters.lock").is_dir():
                delete_block = "此算例正在保存参数或准备运行。"
            elif metadata.get("protect_from_deletion", False):
                delete_block = "此算例已标为关键算例。"
            models.append({"id": model_id, "name": label,
                           "label": f"D {format_length(geometry['tube_bore_um'])} · {label}",
                           "ready": mesh_ready(directory), "review": metadata.get("review_pending", False),
                           "draft": metadata.get("network_status") == "draft",
                           "canSaveParameters": metadata.get("solver_profile") == "jia_initial_state",
                           "solverBuildScript": "solver/jia_dynamic/build_solver.sh"
                           if metadata.get("solver_profile") == "jia_initial_state" else "build_solver.sh",
                           "running": "running" in case_runs.values(),
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
            elif state == "stopped":
                prefix = "已停止 · "
            elif not complete:
                prefix = "未完成 · "
            else:
                prefix = {"field-check": "静电 · ", "pilot": "短验证 · ", "smoke": "短验证 · "}.get(kind, "")
            delete_block = run_delete_block(state, not valid or state in ("stopped", "failed")
                                            or (complete and bool(kind)))
            runs.append({"id": relative(run), "case": model_id, "validation": bool(kind) or not valid
                         or state not in ("running", "complete", "stopped", "snapshot"),
                         "complete": complete, "kind": kind, "conversionStatus": conversion_status(run),
                         "deletable": not delete_block, "deleteBlock": delete_block,
                         "label": f"{prefix}{label} · {run.name}"})
    for run in sorted((ROOT/ADAPTIVE_CASE/"runs").glob("*"), reverse=True):
        if not (run/"parameter.ini").is_file() or not any(run.glob("*_State_0*.h5")):
            continue
        state = run_status(run)
        label = case_info(run).get("display_name", "100 μm · 自适应权重")
        prefix = {"running": "运行中 · ", "failed": "运行失败 · ", "stopped": "已停止 · "}.get(state, "")
        delete_block = run_delete_block(state, state in ("complete", "failed", "stopped"))
        runs.append({"id": relative(run), "case": None, "adaptive": True, "complete": state == "complete",
                     "label": f"{prefix}{label} · {run.name}",
                     "deletable": not delete_block, "deleteBlock": delete_block})
    formal = [item for item in runs if item.get("case") and item.get("complete")
              and not item["validation"] and "-research-" in Path(item["id"]).name]
    latest = max(formal, key=lambda item: Path(item["id"]).name, default=None)
    if latest is None:
        pointer = ROOT/"latest-result.txt"
        archived = pointer.read_text(encoding="utf-8").strip() if pointer.is_file() else ""
        latest = next((item for item in runs if item.get("case") and not item["validation"]
                       and archived in (item["id"], str(ROOT/item["id"]))
                       and run_status(ROOT/item["id"]) == "snapshot"), None)
    return {"models": models, "runs": runs, "latest": latest["id"] if latest else None,
            "meshPresets": AXIS_MESH_PRESETS, "diameters": DIAMETERS}


def frames(directory):
    return sorted(directory.glob("*_State_0*.h5"), key=frame_stamp)


def self_check(key):
    directory = directory_for(key)
    return describe_case(directory, directory != NITROGEN and mesh_ready(directory))


def describe(key):
    directory = directory_for(key)
    geometry = read_geometry(directory/"geometry.json") if directory != NITROGEN else None
    parameter_data = (directory/"parameter.ini").read_bytes()
    parameter_text = parameter_data.decode("utf-8-sig")
    values = parameter_values(parameter_text)
    inputs = parse_parameters(parameter_text)
    summary_file = directory/"pulse-summary.json"
    summary = json.loads(summary_file.read_text(encoding="utf-8")) if summary_file.is_file() else {}
    case = directory.parent.parent if directory.parent.name == "runs" else directory
    weights = (case_settings(inputs) if directory.parent == ROOT/"cases"
               and case_info(directory).get("solver_profile") == "jia_initial_state" else None)
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
        "conversionStatus": conversion_status(directory),
        "modelAvailable": (case/"model"/"helium_geometry.vtm").is_file(),
        "parameters": [{"id": k, "label": title, "value": round(values[k]*scale, 12)}
                       for k, (title, scale) in PARAMETERS.items() if k in values],
        "initialFields": jia_initial_fields(inputs),
        "caseWeightFields": editor_fields(weights) if weights is not None else [],
        "caseMergeFields": editor_fields(weights, MERGE_FIELDS) if weights is not None else [],
        "parameterRevision": hashlib.sha256(parameter_data).hexdigest(),
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
    original = parse_parameters(text)
    seed_species = ((2, 3, 4, 5, 6) if jia_initial else
                    (2, 3, 5, 6) if metadata.get("network_status") == "ready"
                    and original.get("Particles-JiaChemistry") == "T" else (2, 3))
    allowed_inits = ("0", "1") if jia_initial else ("1",)
    for species in seed_species:
        prefix = f"Part-Species{species}-"
        if original.get(prefix+"Init1-SpaceIC") != "cylinder" or original.get(prefix+"nInits") not in allowed_inits:
            raise ValueError("这个算例的种子区域已自定义，请在参数文件中设置新几何对应的种子。")
        radius = real(original[prefix+"Init1-RadiusIC"])*new["tube_bore_um"]/old["tube_bore_um"]
        length = real(original[prefix+"Init1-CylinderHeightIC"])*new["tip_gap_um"]/old["tip_gap_um"]
        start = real(original[prefix+"Init1-BasePointIC"].strip("()/").split(",")[0])
        start *= new["tip_gap_um"]/old["tip_gap_um"]
        weight = real(original[prefix+"MacroParticleFactor"])
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
    params = parse_parameters(text)
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
            metadata["seed_weight"] = real(changes.get(weight_key, params[weight_key]))
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


def configure_pulse(text, parameters):
    active = parse_parameters(text)
    values = {key: float(parameters[key])/scale for key, (_, scale) in PARAMETERS.items() if key in active}
    if any(not math.isfinite(value) or value < 0 or (value == 0 and key != "PulseFlat")
           for key, value in values.items()):
        raise ValueError("参数须为有限正数，平顶时长可为零。")
    values["tend"] = sum(values[key] for key in ("PulseRise", "PulseFlat", "PulseFall"))
    if not math.isfinite(values["tend"]):
        raise ValueError("脉冲总时长须为有限数值。")
    replacements = {key: f"{value:.13g}" for key, value in values.items()}
    replacements["DielectricZoneEpsR"] = f"(/ {replacements['DielectricZoneEpsR']} /)"
    return replace_parameters(text, replacements)


def same_geometry(original, proposed):
    same_domain = all(proposed[k] == original[k] for k in ("tube_bore_um", "tube_outer_um", "tip_gap_um",
                                                          "domain_length_um"))
    same_needle = all(proposed.get(k) == original.get(k) for k in ("tip_radius_um", "needle_shape",
                                                                  "shaft_diameter_um", "cone_half_angle_deg"))
    return same_domain, same_domain and same_needle and proposed["mesh_settings"] == original["mesh_settings"]


def lock_case_parameters(case):
    lock = case/".parameters.lock"
    try:
        lock.mkdir()
    except FileExistsError:
        raise ValueError("此算例正在保存参数或准备运行，请稍后重试。") from None
    return lock


def write_case_files(case, files):
    with TemporaryDirectory(dir=case) as temporary:
        stage = Path(temporary)
        previous = {}
        for name, data in files.items():
            (stage/name).write_bytes(data)
            target = case/name
            if target.is_file():
                previous[name] = stage/(name + ".previous")
                shutil.copy2(target, previous[name])
        replaced = []
        try:
            for name in files:
                (stage/name).replace(case/name)
                replaced.append(name)
        except OSError:
            for name in reversed(replaced):
                if name in previous:
                    previous[name].replace(case/name)
                else:
                    (case/name).unlink()
            raise


def rename_case(key, name):
    case = directory_for(key)
    if (case.parent != ROOT/"cases" or key != relative(case) or not (case/"geometry.json").is_file()
            or read_geometry(case/"geometry.json").get("mesh_method") != "axisymmetric"):
        raise ValueError("请选择一个二维氦气算例。")
    if not isinstance(name, str):
        raise ValueError("请输入算例名称。")
    name = name.strip()
    if not name or len(name) > 100 or not name.isprintable():
        raise ValueError("算例名称须为 1 至 100 个可显示字符，且只能占一行。")
    lock = lock_case_parameters(case)
    try:
        metadata = case_info(case)
        if name != metadata.get("display_name", case.name):
            metadata["display_name"] = name
            write_case_files(case, {
                "case-info.json": (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
                "MODEL_SETTINGS.md": settings_text(case, metadata=metadata).encode("utf-8"),
            })
    finally:
        lock.rmdir()
    return name


def save_parameters(key, draft, parameters, revision, initial=None, weights=None):
    case = directory_for(key)
    if case.parent != ROOT/"cases" or case_info(case).get("solver_profile") != "jia_initial_state":
        raise ValueError("请选择 Jia 初始状态算例。")
    lock = lock_case_parameters(case)
    try:
        if any(run_status(run) == "running" for run in (case/"runs").glob("*") if run.is_dir()):
            raise ValueError("此算例正在运行，请等运行结束后保存参数。")
        original = read_geometry(case/"geometry.json")
        proposed = draft_geometry(draft["geometry"], draft["mesh"])
        if not same_geometry(original, proposed)[1]:
            raise ValueError("几何或网格已修改，请另存为独立算例并生成网格。")
        meta = case_info(case)
        parameter_file = case/"parameter.ini"
        current = parameter_file.read_bytes()
        if hashlib.sha256(current).hexdigest() != revision:
            raise ValueError("磁盘上的参数已更新，请重新打开算例后再保存。")
        text = configure_pulse(current.decode("utf-8-sig").replace("\r\n", "\n"), parameters)
        text = configure_jia_initial(text, initial, meta)
        if weights is not None:
            text = write_weight_parameters(text, parse_parameters(text), weight_parameters(validate(weights)))
        manifest = case/"input-sha256.json"
        hashes = json.loads(manifest.read_text(encoding="utf-8")) if manifest.is_file() else fingerprints(case)
        parameter_data = text.encode("utf-8")
        hashes[parameter_file.name] = hashlib.sha256(parameter_data).hexdigest()
        if parameter_data != current:
            meta["parameters_edited_since_validation"] = True
        files = {
            parameter_file.name: parameter_data,
            "case-info.json": (json.dumps(meta, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
            "MODEL_SETTINGS.md": settings_text(case, text, meta).encode("utf-8"),
            manifest.name: (json.dumps(hashes, indent=2) + "\n").encode("utf-8"),
        }
        write_case_files(case, files)
    finally:
        lock.rmdir()
    return relative(case)


def clone(key, draft, parameters, initial=None, weights=None):
    source = directory_for(key)
    if source.parent != ROOT/"cases":
        raise ValueError("请选择一个二维氦气算例作为模板。")
    original = read_geometry(source/"geometry.json")
    if original.get("mesh_method") != "axisymmetric":
        raise ValueError("请选择一个二维轴对称算例。")
    proposed = draft_geometry(draft["geometry"], draft["mesh"])
    same_domain, same_mesh = same_geometry(original, proposed)
    geometry = original if same_mesh else proposed
    text = configure_pulse((source/"parameter.ini").read_text(encoding="utf-8-sig"), parameters)
    metadata = case_info(source)
    if not same_domain:
        text = particle_search_parameters(resize_seed(text, original, geometry, metadata), geometry)
    text = configure_jia_initial(text, initial, metadata)
    if weights is not None:
        if metadata.get("solver_profile") != "jia_initial_state":
            raise ValueError("请选择 Jia 初始状态算例。")
        text = write_weight_parameters(text, parse_parameters(text), weight_parameters(validate(weights)))
    case = new_case_directory(ROOT, geometry)
    metadata.pop("protect_from_deletion", None)
    metadata.update(display_name=case.name, cloned_from=relative(source))
    (case/"parameter.ini").write_text(text, encoding="utf-8")
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
               "saveParameters": save_parameters, "renameCase": rename_case,
               "paraview": paraview, "selfCheck": self_check, "runProgress": run_progress,
               "adaptiveWeightSettings": adaptive_weight_settings, "saveAdaptiveWeight": save_adaptive_weight}
    for line in sys.stdin:
        request = json.loads(line)
        response = {"id": request["id"]}
        try:
            response["result"] = methods[request["method"]](**request.get("args", {}))
        except (ValueError, TypeError, OSError, KeyError, IndexError, RuntimeError) as error:
            response["error"] = str(error)
        print(json.dumps(response, ensure_ascii=False), flush=True)
