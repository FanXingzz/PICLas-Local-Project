"""Single-layer hexahedral storage mesh for the PICLas x-r solver."""
import json
from pathlib import Path

import numpy as np

from make_swept_mesh import axial_planes, plane_points, save_mesh, FACES, NAMES
from tube_cases import taper_dimensions

NAMES = {**NAMES, "BC_Axis": (5, 2), "BC_Sym": (6, 2)}


def taper_points(points, geometry, reference_cone):
    """Map the rounded reference grid to the tapered contour at fixed wall radius."""
    tip = geometry["tip_gap_um"]/2
    radius = geometry["tip_radius_um"]
    shaft = geometry["shaft_diameter_um"]/2
    end = geometry["domain_length_um"]/2-tip
    tangent_x, tangent_r, shoulder = taper_dimensions(geometry)
    x, r = points.T
    depth = np.clip(abs(x)-tip, 0., end)
    cap_angle = np.arccos(1-np.minimum(depth/radius, 1.))
    angle = np.radians(geometry["cone_half_angle_deg"])
    cap_angle_new = cap_angle*(1-2*angle/np.pi)
    new_depth = np.interp(depth, [0., radius, radius+reference_cone, end],
                          [0., tangent_x, shoulder, end])
    on_cap = depth < radius
    new_depth[on_cap] = radius*(1-np.cos(cap_angle_new[on_cap]))
    old_surface = radius*np.sin(cap_angle)
    new_surface = np.where(on_cap, radius*np.sin(cap_angle_new),
                           np.minimum(shaft, tangent_r+(new_depth-tangent_x)*np.tan(angle)))
    bore = geometry["tube_bore_um"]/2
    cutoff = (bore+shaft)/2
    scale = np.divide(new_surface, old_surface, out=np.full_like(depth, 1-2*angle/np.pi), where=old_surface > 0)
    ahead = np.maximum(tip-abs(x), 0.)
    scale = 1+(scale-1)*np.maximum(0., 1-ahead/(6*radius))**2
    radial_basis = np.minimum(r, radius)*np.clip((cutoff-r)/(cutoff-radius), 0., 1.)
    return np.column_stack((x+np.sign(x)*(new_depth-depth),
                            r+(scale-1)*radial_basis))


def write_mesh(g):
    settings = g["mesh_settings"]
    radius = g["tip_radius_um"]
    bore = g["tube_bore_um"]/2
    wall = g["tube_outer_um"]/2
    layers = settings["bore_layers"]
    wall_first = (bore-radius)*settings["wall_first_percent"]/100
    fractions = np.linspace(0., 1., layers)[1:]**1.65
    core = settings["tip_radial_layers"]
    quartz_layers = settings["quartz_layers"]
    quartz_fraction = np.linspace(0., 1., quartz_layers+1)
    first = settings.get("quartz_first_percent", 100/quartz_layers)/100
    if quartz_layers > 1 and not np.isclose(first, 1/quartz_layers):
        quartz_fraction **= np.log(first)/np.log(1/quartz_layers)
    r = np.r_[np.linspace(0., radius, core+1),
              radius+(bore-radius-wall_first)*fractions, bore,
              (np.linspace(bore, wall, quartz_layers+1) if np.isclose(first, 1/quartz_layers)
               else bore+(wall-bore)*quartz_fraction)[1:]]
    n = len(r)
    planes = axial_planes(g, None)
    reference_cone = None
    if g.get("needle_shape") == "tapered":
        tangent, _, shoulder = taper_dimensions(g)
        half_gap = g["tip_gap_um"]/2
        guard = g["domain_length_um"]/2-half_gap
        reference_cone = min(shoulder-tangent, (guard-radius)*0.8)
        extra = half_gap+radius+np.linspace(0., reference_cone, 9)[1:]
        planes = np.unique(np.r_[planes, extra, -extra])
    section = np.column_stack((r, np.zeros(n)))
    xy = np.concatenate([plane_points(x, section, g)[:, :2] for x in planes])
    if reference_cone:
        xy = taper_points(xy, g, reference_cone)
    stride = len(xy)
    xyz = np.vstack([np.column_stack((xy, np.full(stride, z))) for z in (-0.5, 0.5)])
    cells, zones = [], []
    tip = g["tip_gap_um"]/2
    for i, (start, end) in enumerate(zip(planes[:-1], planes[1:])):
        first = core if end <= -tip or start >= tip else 0
        for j in range(first, n-1):
            a = i*n+j
            base = [a, a+n, a+n+1, a+1]
            cells.append(base+[k+stride for k in base])
            zones.append(1 if r[j] < bore else 2)
    exposed = {}
    faces, boundaries = [], []
    for cell, zone in zip(cells, zones):
        for indices in FACES:
            face = tuple(cell[i] for i in indices)
            key = tuple(sorted(face))
            previous = exposed.pop(key, None)
            if previous is None:
                exposed[key] = (face, zone)
            elif previous[1] != zone:
                faces.append(face if zone == 1 else previous[0])
                boundaries.append(3)
    for face, _ in exposed.values():
        indices = np.array(face)
        x, r_coords, _ = xyz[indices].T
        if np.all(indices < stride) or np.all(indices >= stride):
            tag = 6
        elif np.all(abs(x) >= g["domain_length_um"]/2-1e-8) or np.all(r_coords >= wall-1e-8):
            tag = 4
        elif np.all(r_coords <= 1e-9):
            tag = 5
        else:
            tag = 1 if x.mean() < 0 else 2
        faces.append(face)
        boundaries.append(tag)
    save_mesh(xyz, np.array(cells), np.array(zones), faces, boundaries, NAMES)
    print(f"x-r mesh: {len(cells)} cells, one storage layer, "
          f"boundary counts {np.bincount(boundaries, minlength=7)[1:].tolist()}", flush=True)


if __name__ == "__main__":
    write_mesh(json.loads(Path("geometry.json").read_text(encoding="utf-8")))
