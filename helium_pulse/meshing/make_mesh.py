"""Conformal helium/quartz CAD in micrometres; the PICLas mesh is in metres."""
from pathlib import Path
import json

import gmsh
import numpy as np

G = json.loads(Path("geometry.json").read_text())
L = G["domain_length_um"] / 2
Y = G["domain_width_um"] / 2
Z = G["plate_gap_um"] / 2
T = G["plate_thickness_um"]
R = G["tube_bore_um"] / 2
O = G["tube_outer_um"] / 2
P = G["tip_radius_um"]
H = G["tip_gap_um"] / 2
if not (0 < P < R <= Z < O < min(Y, Z + T) and H + P < L):
    raise ValueError("Invalid nested bore, plate and electrode dimensions")

gmsh.initialize()
try:
    gmsh.option.setNumber("General.NumThreads", 1)
    gmsh.model.add("helium_pin_pin")
    cad = gmsh.model.occ
    lower = cad.addBox(-L, -Y, -Z-T, 2*L, 2*Y, T)
    upper = cad.addBox(-L, -Y, Z, 2*L, 2*Y, T)
    outer = cad.addCylinder(-L, 0, 0, 2*L, 0, 0, O)
    bore = cad.addCylinder(-L, 0, 0, 2*L, 0, 0, R)
    tube, _ = cad.cut([(3, outer)], [(3, bore)])
    quartz, _ = cad.fuse(tube, [(3, lower), (3, upper)])
    domain = cad.addBox(-L, -Y, -Z-T, 2*L, 2*Y, 2*(Z+T))

    pins = []
    for sign in (-1, 1):
        center = sign*(H+P)
        end = sign*L
        shaft = cad.addCylinder(end, 0, 0, center-end, 0, 0, P)
        sphere = cad.addSphere(center, 0, 0, P)
        pin, _ = cad.fuse([(3, shaft)], [(3, sphere)])
        pins.extend(pin)

    _, mapping = cad.fragment([(3, domain)], quartz + pins)
    cad.synchronize()
    volumes = {tag for dim, tag in mapping[0] if dim == 3}
    quartz_tags = {tag for block in mapping[1:1+len(quartz)] for dim, tag in block if dim == 3}
    pin_tags = [{tag for dim, tag in block if dim == 3} for block in mapping[1+len(quartz):]]
    metal = set.union(*pin_tags)
    gas = volumes - quartz_tags - metal
    assert gas and quartz_tags and all(pin_tags)
    surfaces = {name: [] for name in ("BC_HV", "BC_Ground", "BC_Quartz", "BC_Outer")}
    for _, tag in gmsh.model.getEntities(2):
        adjacent = set(gmsh.model.getAdjacencies(2, tag)[0])
        if not adjacent & (gas | quartz_tags):
            continue
        if adjacent & pin_tags[0]:
            surfaces["BC_HV"].append(tag)
        elif adjacent & pin_tags[1]:
            surfaces["BC_Ground"].append(tag)
        elif adjacent & gas and adjacent & quartz_tags:
            surfaces["BC_Quartz"].append(tag)
        elif len(adjacent) == 1:
            surfaces["BC_Outer"].append(tag)
    for name, tags in surfaces.items():
        if not tags:
            raise RuntimeError(f"No CAD surfaces for {name}")
        gmsh.model.addPhysicalGroup(2, tags, name=name)
    gmsh.model.addPhysicalGroup(3, sorted(gas), tag=1, name="Helium")
    gmsh.model.addPhysicalGroup(3, sorted(quartz_tags), tag=2, name="Quartz")
    cad.remove([(3, tag) for tag in metal], recursive=True)
    cad.synchronize()
    gmsh.option.setNumber("Mesh.MeshSizeMin", G["tip_mesh_um"])
    gmsh.option.setNumber("Mesh.MeshSizeMax", G["bulk_mesh_um"])
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 8)
    points = gmsh.model.getBoundary(
        [(2, tag) for tag in surfaces["BC_HV"] + surfaces["BC_Ground"]],
        combined=False, recursive=True,
    )
    gmsh.model.mesh.setSize(list(set(points)), G["tip_mesh_um"])
    gmsh.model.mesh.generate(3)
    gmsh.write("geometry.msh")

    node_ids, xyz, _ = gmsh.model.mesh.getNodes()
    xyz = xyz.reshape(-1, 3)
    order = np.argsort(node_ids)
    tets = []
    zones = []
    for zone, tags in ((1, gas), (2, quartz_tags)):
        for tag in sorted(tags):
            _, nodes = gmsh.model.mesh.getElementsByType(4, tag)
            corners = xyz[order[np.searchsorted(node_ids[order], nodes)]].reshape(-1, 4, 3)
            tets.extend(corners)
            zones.extend([zone]*len(corners))
    np.savez_compressed("mesh_regions.npz", tetrahedra=tets, zones=zones)
finally:
    gmsh.finalize()
