"""Block-structured axial sweeps for the embedded, round-tip quartz tube."""
import json
from pathlib import Path

import meshio
import numpy as np

NAMES = {"BC_HV": (1, 2), "BC_Ground": (2, 2), "BC_Quartz": (3, 2),
         "BC_Outer": (4, 2), "Helium": (1, 3), "Quartz": (2, 3)}
FACES = ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
         (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7))


def section(g, level):
    """Map a square core and concentric rings to a conformal YZ section."""
    tube = g.get("structure") == "tube_only"
    settings = g.get("mesh_settings", {})
    n = settings["circumferential_segments"]//4 if tube else (4, 8, 12)[level]
    t = np.linspace(-1., 1., n+1)
    square = np.array([(y, z) for z in t for y in t])
    q = n+1
    edge = np.r_[np.arange(q), np.arange(1, q)*q+n,
                 n*q+np.arange(n-1, -1, -1), np.arange(n-1, 0, -1)*q]
    radius = g["tip_radius_um"]
    norm = np.linalg.norm(square, axis=1)
    direction = square / np.maximum(norm[:, None], 1e-15)
    core = (0.45*radius*square if tube
            else radius * np.max(abs(square), axis=1)[:, None] * direction)
    cells = [[j*q+i, j*q+i+1, (j+1)*q+i+1, (j+1)*q+i]
             for j in range(n) for i in range(n)]
    zones = [1]*len(cells)
    core_count = len(cells)
    points = list(core)

    def ring(coords, material):
        nonlocal edge
        start = len(points)
        points.extend(coords)
        outer = start+np.arange(len(edge))
        for i in range(len(edge)):
            j = (i+1) % len(edge)
            cells.append([edge[i], outer[i], outer[j], edge[j]])
            zones.append(int(material) if np.isscalar(material) else material[i])
        edge = outer

    bore = g["tube_bore_um"]/2
    wall = g["tube_outer_um"]/2
    unit = direction[edge]
    if tube:
        ring(radius*unit, 1)
        core_count = len(cells)
        width = bore-radius
        wall_first = width*settings["wall_first_percent"]/100
        layers = settings["bore_layers"]
        # Cluster near the rounded pin as well as at the dielectric interface.
        fractions = np.linspace(0., 1., layers)[1:]**1.65
        for r in np.r_[radius+(width-wall_first)*fractions, bore]:
            ring(r*unit, 1)
        for r in np.linspace(bore, wall, settings["quartz_layers"]+1)[1:]:
            ring(r*unit, 2)
        return np.array(points), np.array(cells), np.array(zones), core_count

    plate = g["plate_gap_um"]/2
    width = g["domain_width_um"]/2
    height = plate+g["plate_thickness_um"]
    near_pin = (0.7, 1.4, 2.8, 4.0) if level == 0 else (0.35, 0.7, 1.4, 2.8, 4.0)
    if level == 2:
        near_pin = (0.18, 0.35, 0.7, 1.4, 2.8, 4.0)
    wall_layers = ((3., 1.2), (3., 1.5, 0.6), (3., 1.5, 0.75, 0.3))[level]
    radii = [radius+delta for delta in near_pin] + [10., 15., 19.]
    radii.extend(bore-delta for delta in wall_layers)
    radii.append(bore)
    for r in radii:
        ring(r*unit, 1)

    # Match the circular tube/plate intersections to the same height on the box.
    angle = np.arctan2(abs(unit[:, 1]), abs(unit[:, 0]))
    cross = np.arcsin(plate/wall)
    section_knots = [0., np.arctan(0.5), np.pi/4, np.pi/2]
    outer_angle = np.interp(angle, section_knots, [0., cross, np.pi/3, np.pi/2])
    signs = np.sign(unit)
    wall_edge = wall*np.column_stack((np.cos(outer_angle), np.sin(outer_angle)))*signs
    for fraction in (0.05, 0.22, 0.52, 1.):
        ring((1-fraction)*bore*unit+fraction*wall_edge, 2)

    rect_y = np.interp(angle, section_knots, [width, width, width, 0.])
    rect_z = np.interp(angle, section_knots, [0., plate, height, height])
    box_edge = np.column_stack((rect_y, rect_z))*signs
    wall_gas = (abs(wall_edge[:, 1])+abs(np.roll(wall_edge[:, 1], -1)))/2 < plate
    for fraction in (0.32, 0.67, 1.):
        ring((1-fraction)*wall_edge+fraction*box_edge, np.where(wall_gas, 1, 2))
    return np.array(points), np.array(cells), np.array(zones), core_count


def axial_planes(g, level):
    """Axially refine the hemispheres and grade into the straight section."""
    half = g["domain_length_um"]/2
    tip = g["tip_gap_um"]/2
    radius = g["tip_radius_um"]
    center = -tip-radius
    end = -half
    if g.get("structure") == "tube_only":
        settings = g["mesh_settings"]
        step = settings["axial_max_um"]
        near_shaft = min(8*radius, (center-end)*0.5)
        shaft = np.linspace(end, center-near_shaft,
                            int(np.ceil((center-near_shaft-end)/step))+1, endpoint=True)
        shaft = np.r_[shaft[:-1], center-near_shaft*np.array([1., .5, .25, .125, .0625])]
        cap = center+np.linspace(0., radius, settings["cap_layers"], endpoint=False)
        transition_end = min(tip, 12*radius)
        transition = -tip+transition_end*np.array([0., .03, .07, .12, .18, .3, .48, .7, 1.])
        subdivisions = int(settings.get("tip_gap_subdivisions", 1))
        if subdivisions > 1:
            near_tip = np.concatenate([np.linspace(a, b, subdivisions, endpoint=False)
                                       for a, b in zip(transition[:4], transition[1:5])])
            transition = np.r_[near_tip, transition[4:]]
        middle = np.linspace(transition[-1], 0., int(np.ceil(-transition[-1]/step))+1)[1:]
        left = np.r_[shaft, cap, transition, middle]
        left[-1] = 0.
        return np.r_[left, -left[-2::-1]]
    cap_count = (3, 6, 12)[level]
    shaft = np.r_[np.linspace(end, center-8*radius, 7, endpoint=False),
                  center+radius*np.array([-8., -4., -2., -1., -0.5])]
    cap = center+np.linspace(0., radius, cap_count, endpoint=False)
    transition = -tip+radius*np.array([0., 0.35, 0.8, 1.4, 2., 3.5, 5., 8., 12.])
    middle = np.linspace(transition[-1], 0., (13, 17, 21)[level])[1:]
    left = np.r_[shaft, cap, transition, middle]
    return np.r_[left, -left[-2::-1]]


def plane_points(x, section_points, g):
    """Project the cutout's front and side faces to the round metal cap."""
    radius = g["tip_radius_um"]
    sign = -1. if x < 0 else 1.
    s = g["tip_gap_um"]/2+radius-abs(x)
    r = np.linalg.norm(section_points, axis=1)
    if s <= 0 or s >= 3*radius:
        return np.column_stack((np.full(len(r), x), section_points))
    cap_s = min(s, radius)
    cap_r = np.minimum(r, radius)
    projection = radius/np.hypot(cap_s, cap_r)
    influence = 3*radius
    if g.get("structure") == "tube_only":
        influence = min(influence, g["tube_bore_um"]/2)
    blend = np.clip((influence-r)/(influence-radius), 0., 1.)
    if s > radius:
        blend *= (3*radius-s)/(2*radius)
    axial_shift = cap_s*(projection-1)*blend
    radial_shift = cap_r*(projection-1)*blend
    radial_scale = 1+radial_shift/np.maximum(r, 1e-15)
    return np.column_stack((x-sign*axial_shift, section_points*radial_scale[:, None]))


def write_mesh(geometry):
    level = geometry.get("sweep_level")
    tube = geometry.get("structure") == "tube_only"
    if not tube and (geometry["tube_bore_um"], geometry["tip_radius_um"], geometry["tip_gap_um"]) != (50, 2, 1000):
        raise ValueError("The swept refinement levels are defined for D=50 um, R=2 um, gap=1000 um")
    yz, quads, cross_zones, core_count = section(geometry, level)
    planes = axial_planes(geometry, level)
    xyz = np.concatenate([plane_points(x, yz, geometry) for x in planes])
    ns = len(yz)
    tip = geometry["tip_gap_um"]/2
    slabs = []
    materials = []
    for i, (start, end) in enumerate(zip(planes[:-1], planes[1:])):
        first = core_count if end <= -tip or start >= tip else 0
        lower = quads[first:]+i*ns
        slabs.append(np.column_stack((lower, lower+ns)))
        materials.append(cross_zones[first:])
    hexes = np.concatenate(slabs)
    zones = np.concatenate(materials)

    exposed = {}
    quad_faces, boundaries = [], []
    for hex_nodes, material in zip(hexes.tolist(), zones.tolist()):
        for indices in FACES:
            face = tuple(hex_nodes[i] for i in indices)
            key = tuple(sorted(face))
            previous = exposed.pop(key, None)
            if previous is None:
                exposed[key] = (face, material)
            elif previous[1] != material:
                quad_faces.append(face if material == 1 else previous[0])
                boundaries.append(3)

    for face, _ in exposed.values():
        layers = [i//ns for i in face]
        # End faces and box sides are outer walls. The open core is the pin.
        if max(layers) == 0 or min(layers) == len(planes)-1:
            tag = 4
        else:
            yz_coords = xyz[list(face), 1:]
            on_pin = np.max(np.linalg.norm(yz_coords, axis=1)) <= geometry["tip_radius_um"]*(1+1e-9)
            tag = (1 if xyz[face[0], 0] < 0 else 2) if on_pin else 4
        quad_faces.append(face)
        boundaries.append(tag)

    save_mesh(xyz, hexes, zones, quad_faces, boundaries, NAMES)
    print(f"Swept mesh: {len(hexes)} hexes, {len(planes)-1} slabs, "
          f"boundary counts {np.bincount(boundaries, minlength=5)[1:].tolist()}", flush=True)


def save_mesh(xyz, hexes, zones, quad_faces, boundaries, names):
    # PyHOPE 1.1 expects element IDs within each Gmsh entity to be consecutive.
    boundary_order = np.argsort(boundaries, kind="stable")
    volume_order = np.argsort(zones, kind="stable")
    quad_faces = np.asarray(quad_faces)[boundary_order]
    boundaries = np.asarray(boundaries)[boundary_order]
    hexes = hexes[volume_order]
    zones = zones[volume_order]

    # Remove unreferenced core nodes left by the two excluded metal volumes.
    used = np.unique(hexes)
    new_id = np.full(len(xyz), -1)
    new_id[used] = np.arange(len(used))
    meshio.write("geometry.msh", meshio.Mesh(
        xyz[used], [("quad", new_id[quad_faces]), ("hexahedron", new_id[hexes])],
        cell_data={"gmsh:physical": [np.array(boundaries), zones],
                   "gmsh:geometrical": [np.array(boundaries), zones]},
        field_data={key: np.array(value) for key, value in names.items()},
    ), file_format="gmsh22", binary=False)
    np.savez_compressed("swept_regions.npz", centers=xyz[hexes].mean(axis=1), zones=zones)


if __name__ == "__main__":
    write_mesh(json.loads(Path("geometry.json").read_text(encoding="utf-8")))
