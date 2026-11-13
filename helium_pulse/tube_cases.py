"""Geometry and initialization for independent quartz bore cases."""
import json
import math
import re

from piclas_ini import parse_parameters, replace_parameters

DIAMETERS = {
    "100 μm": 100.0, "50 μm": 50.0, "10 μm": 10.0,
    "1 μm": 1.0, "100 nm": 0.1, "10 nm": 0.01,
}
GEOMETRY_FIELDS = (
    ("tube_bore_um", "石英管内径 D"),
    ("tip_gap_um", "针尖间距 d"),
    ("plate_gap_um", "石英板间隙"),
    ("tube_outer_um", "石英管外径"),
)


TUBE_FIELDS = (
    ("tube_bore_um", "石英管内径 D"),
    ("tip_gap_um", "针尖间距 d"),
    ("domain_length_um", "石英管长度"),
    ("tube_outer_um", "石英管外径"),
)
MESH_FIELDS = (
    ("circumferential_segments", "管周分段数（8 的倍数）", int),
    ("cap_layers", "圆头轴向分段数", int),
    ("bore_layers", "管腔径向层数", int),
    ("wall_first_percent", "贴壁首层占径向余量 (%)", float),
    ("quartz_layers", "石英壁径向层数", int),
    ("axial_max_um", "直管轴向最大尺寸 (μm)", float),
)
MESH_PRESETS = {
    "较粗": (16, 3, 8, 5., 3, 40.),
    "常规": (32, 6, 12, 2.5, 4, 30.),
    "较细": (48, 12, 16, 1.25, 5, 24.),
}


def mesh_preset(name):
    return dict(zip((key for key, _, _ in MESH_FIELDS), MESH_PRESETS[name], strict=True))


def plan_tube(sizes, radius, mesh):
    bore, gap, length, outer = (sizes[key] for key, _ in TUBE_FIELDS)
    if not all(math.isfinite(value) and value > 0 for value in (bore, gap, length, outer, radius)):
        raise ValueError("管与电极尺寸须为有限正数。")
    if not 2*radius < bore < outer:
        raise ValueError("针杆直径须小于管内径，管内径须小于管外径。")
    if length <= gap+2*radius or gap <= 4*radius:
        raise ValueError("管长须容纳两端圆头，针尖间距须大于四倍圆头半径。")
    if not all(math.isfinite(mesh[key]) and mesh[key] > 0 for key, _, _ in MESH_FIELDS):
        raise ValueError("网格设置须为有限正数。")
    if any(mesh[key] != int(mesh[key]) for key, _, dtype in MESH_FIELDS if dtype is int):
        raise ValueError("分段数和层数须为整数。")
    if mesh["circumferential_segments"] % 8 or mesh["circumferential_segments"] < 16:
        raise ValueError("管周分段数须为不小于 16 的 8 的倍数。")
    if mesh["bore_layers"] < 2 or mesh["wall_first_percent"] >= 100:
        raise ValueError("管腔至少分两层，贴壁首层占比须小于 100%。")
    return {**sizes, "domain_width_um": outer, "tip_radius_um": radius,
            "radius_over_bore": radius/bore, "structure": "tube_only",
            "mesh_method": "swept", "mesh_settings": dict(mesh)}


AXIS_MESH_FIELDS = tuple(field for field in MESH_FIELDS if field[0] != "circumferential_segments") + (
    ("tip_radial_layers", "圆头径向分段数", int),
    ("tip_gap_subdivisions", "针尖前方轴向细分倍数", int),
    ("quartz_first_percent", "石英首层占壁厚 (%)", float),
)


def axis_mesh_values(settings):
    return {"tip_gap_subdivisions": 1, "quartz_first_percent": 100/max(1, settings["quartz_layers"]), **settings}


def axis_mesh_preset(name):
    values = mesh_preset(name)
    values.pop("circumferential_segments")
    values["tip_radial_layers"] = {"较粗": 4, "常规": 6, "较细": 9}[name]
    values["tip_gap_subdivisions"] = {"较粗": 1, "常规": 2, "较细": 4}[name]
    values["quartz_first_percent"] = {"较粗": 100/3, "常规": 10, "较细": 5}[name]
    return values


AXIS_MESH_PRESETS = {name: axis_mesh_preset(name) for name in MESH_PRESETS}


def plan_axisymmetric_tube(sizes, radius, mesh):
    mesh = axis_mesh_values(mesh)
    if mesh["tip_radial_layers"] < 2 or mesh["tip_radial_layers"] != int(mesh["tip_radial_layers"]):
        raise ValueError("圆头径向分段数须为不小于 2 的整数。")
    subdivisions = mesh["tip_gap_subdivisions"]
    if not math.isfinite(subdivisions) or subdivisions < 1 or subdivisions != int(subdivisions):
        raise ValueError("针尖前方轴向细分倍数须为正整数。")
    wall_first = mesh["quartz_first_percent"]
    if (not math.isfinite(wall_first) or not 0 < wall_first <= 100 or
            (mesh["quartz_layers"] > 1 and wall_first == 100) or
            (mesh["quartz_layers"] == 1 and wall_first != 100)):
        raise ValueError("单层石英首层占比为 100%，多层时首层占比须在 0% 与 100% 之间。")
    geometry = plan_tube(sizes, radius, {**mesh, "circumferential_segments": 16})
    geometry["mesh_method"] = "axisymmetric"
    if subdivisions == 1:
        mesh.pop("tip_gap_subdivisions")
    if math.isclose(wall_first, 100/mesh["quartz_layers"], rel_tol=1e-10):
        mesh.pop("quartz_first_percent")
    geometry["mesh_settings"] = dict(mesh)
    return geometry


def taper_dimensions(geometry):
    radius = geometry["tip_radius_um"]
    angle = math.radians(geometry["cone_half_angle_deg"])
    tangent_x = radius*(1-math.sin(angle))
    tangent_r = radius*math.cos(angle)
    shoulder_x = tangent_x + (geometry["shaft_diameter_um"]/2-tangent_r)/math.tan(angle)
    return tangent_x, tangent_r, shoulder_x


def configure_taper(geometry, shaft_diameter, half_angle):
    """Add a spherical nose tangent to a cone, with an independent cylindrical shank."""
    if not (math.isfinite(shaft_diameter) and 2*geometry["tip_radius_um"] < shaft_diameter < geometry["tube_bore_um"]):
        raise ValueError("锥形针的针杆直径须大于两倍针尖半径、小于管内径。")
    if not (math.isfinite(half_angle) and 0 < half_angle < 90):
        raise ValueError("锥半角须在 0° 与 90° 之间。")
    geometry.update(needle_shape="tapered", shaft_diameter_um=shaft_diameter, cone_half_angle_deg=half_angle)
    _, _, shoulder = taper_dimensions(geometry)
    if shoulder >= (geometry["domain_length_um"]-geometry["tip_gap_um"])/2:
        raise ValueError("现有管长无法容纳锥段与直针杆。")
    return geometry


def chamber_height(geometry):
    if geometry.get("structure") == "tube_only":
        return geometry["tube_outer_um"]
    return geometry["plate_gap_um"] + 2*geometry["plate_thickness_um"]


def format_length(um):
    return f"{um*1000:g} nm" if um < 1 else f"{um:g} μm"


def length_slug(um):
    value = f"{um/1000:g}mm" if um >= 1000 else f"{um:g}um" if um >= 1 else f"{um*1000:g}nm"
    return value.replace(".", "p").replace("+", "")


def read_geometry(path):
    return json.loads(path.read_text(encoding="utf-8"))


def plan_geometry(base, sizes, tip_radius=None, radius_ratio=None):
    """Keep chamber and electrode geometry explicit in the case snapshot."""
    bore, gap, plate_gap, outer = (sizes[key] for key, _ in GEOMETRY_FIELDS)
    radius = tip_radius if radius_ratio is None else radius_ratio*bore
    dimensions = (bore, gap, plate_gap, outer, radius)
    if not all(math.isfinite(value) and value > 0 for value in dimensions):
        raise ValueError("几何尺寸与针尖半径须为有限正数。")
    if 2*radius >= bore:
        raise ValueError("针杆直径等于两倍圆头半径，须小于管内径。请减小针尖半径或选择按比例缩放。")
    if not bore <= plate_gap < outer:
        raise ValueError("嵌入式结构要求管内径 ≤ 石英板间隙 < 石英管外径。")
    clearance = bore/2 - radius
    end_margin = (base["domain_length_um"] - base["tip_gap_um"])/2
    side_margin = (base["domain_width_um"] - base["tube_outer_um"])/2
    return {
        **base, **sizes,
        "domain_length_um": gap + 2*max(end_margin, 2*radius),
        "domain_width_um": outer + 2*side_margin,
        "plate_thickness_um": max(base["plate_thickness_um"], (outer - plate_gap)/2 + 10),
        "tip_radius_um": radius,
        "tip_mesh_um": min(base["tip_mesh_um"], radius*0.5, clearance*0.5),
        "electrode_size_mode": "ratio" if radius_ratio is not None else "fixed",
        "radius_over_bore": radius/bore,
    }


def seed_geometry(geometry):
    """Use a square seed wholly inside the bore at the same nominal density."""
    side_um = min(20., geometry["tube_bore_um"]*0.25, geometry["tip_gap_um"]*0.15)
    offset_um = min(20., geometry["tip_gap_um"]*0.15)
    weight = 20*(side_um/20)**3
    return side_um, offset_um, weight


def seed_parameters(text, geometry):
    side_um, offset_um, weight = seed_geometry(geometry)
    side = side_um*1e-6
    start_x = (-geometry["tip_gap_um"]/2 + offset_um)*1e-6
    values = {}
    for species in (2, 3):
        prefix = f"Part-Species{species}-"
        values.update({
            prefix + "MacroParticleFactor": f"{weight:.12g}",
            prefix + "Init1-BasePointIC": f"(/{start_x:.12g},{-side/2:.12g},{-side/2:.12g}/)",
            prefix + "Init1-BaseVector1IC": f"(/0.,{side:.12g},0./)",
            prefix + "Init1-BaseVector2IC": f"(/0.,0.,{side:.12g}/)",
            prefix + "Init1-CuboidHeightIC": f"{side:.12g}",
        })
    text = re.sub(r"^! Co-located He\+ and electron seed[^\n]*",
                  "! He+ and electron seed fitted to the bore; baseline nominal density.", text, flags=re.M)
    text = replace_parameters(text, values)
    if geometry.get("mesh_method") == "axisymmetric":
        radius = side/math.sqrt(math.pi)
        for species in (2, 3):
            prefix = f"Part-Species{species}-Init1-"
            text = replace_parameters(text, {
                prefix+"SpaceIC": "cylinder",
                prefix+"BasePointIC": f"(/{start_x:.12g},0.,0./)",
                prefix+"BaseVector1IC": "(/0.,1.,0./)",
                prefix+"BaseVector2IC": "(/0.,0.,1./)",
            })
            extra = {prefix+"RadiusIC": f"{radius:.12g}", prefix+"Radius2IC": "0.",
                     prefix+"CylinderHeightIC": f"{side:.12g}"}
            active = parse_parameters(text)
            for key, value in extra.items():
                if key in active:
                    text = replace_parameters(text, {key: value})
                else:
                    text += f"\n{key} = {value}\n"
    return text



def particle_search_parameters(text, geometry):
    # This Cartesian grid indexes the unstructured mesh for particle lookup.
    # Use the chamber dimensions so local tip refinement cannot shrink every bin.
    length = geometry["domain_length_um"]
    width = geometry["domain_width_um"]
    height = chamber_height(geometry)
    spacing = f"(/{length/110*1e-6:.12g},{width/22*1e-6:.12g},{height/20*1e-6:.12g}/)"
    key = "Part-FIBGMdeltas"
    if key in parse_parameters(text):
        return replace_parameters(text, {key: spacing})
    return text + f"\n! Particle lookup bins (independent of the field mesh)\n{key} = {spacing}\n"


def create_case(root, geometry, parameters):
    source = root / "DSMC.ini"
    chemistry = source.read_bytes()
    parameters = particle_search_parameters(seed_parameters(parameters, geometry), geometry)
    # Iterative multigrid avoids the direct factorization cost of refined 3D meshes.
    parameters = replace_parameters(parameters, {"PrecondType": "3"})
    if geometry.get("mesh_method") == "axisymmetric":
        parameters = replace_parameters(parameters, {"Part-nBounds": "6"})
        extra = {
            "Particles-Symmetry-Order": "2", "Particles-Symmetry2DAxisymmetric": "T",
            "Part-Boundary5-SourceName": "BC_Axis", "Part-Boundary5-Condition": "symmetric_axis",
            "Part-Boundary6-SourceName": "BC_Sym", "Part-Boundary6-Condition": "symmetric_dim",
        }
        active = parse_parameters(parameters)
        for key, value in extra.items():
            if key in active:
                parameters = replace_parameters(parameters, {key: value})
            else:
                parameters += f"\n{key} = {value}\n"
    case = new_case_directory(root, geometry)
    (case / "geometry.json").write_text(json.dumps(geometry, indent=2) + "\n", encoding="utf-8")
    (case / "parameter.ini").write_text(parameters, encoding="ascii")
    (case / source.name).write_bytes(chemistry)
    return case


def new_case_directory(root, geometry):
    cases = root / "cases"
    cases.mkdir(exist_ok=True)
    layout = "Tube" if geometry.get("structure") == "tube_only" else "Plates"
    axisymmetric = geometry.get("mesh_method") == "axisymmetric"
    dims = "2D" if axisymmetric else "3D"
    preset = next((tag for name, tag in zip(AXIS_MESH_PRESETS, ("Coarse", "Medium", "Fine"))
                   if AXIS_MESH_PRESETS[name] == geometry.get("mesh_settings")), "Custom")
    label = (f'He_{layout}{dims}_D{length_slug(geometry["tube_bore_um"])}'
             f'_R{length_slug(geometry["tip_radius_um"])}_Gap{length_slug(geometry["tip_gap_um"])}'
             f'_{preset if axisymmetric else geometry.get("mesh_method", "Tetra").title()}')
    if geometry.get("needle_shape") == "tapered":
        label += f'_TaperS{length_slug(geometry["shaft_diameter_um"])}'
    version = 1
    while True:
        case = cases/(label if version == 1 else f"{label}_v{version:02d}")
        try:
            case.mkdir()
            return case
        except FileExistsError:
            version += 1
