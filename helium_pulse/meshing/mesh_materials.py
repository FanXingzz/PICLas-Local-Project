"""Transfer Gmsh material IDs to the subdivided PICLas hexahedra."""
import h5py
import numpy as np
from scipy.spatial import cKDTree

with np.load("mesh_regions.npz") as regions:
    tet = regions["tetrahedra"]
    zone = regions["zones"]
origin = tet[:, 0]
inv = np.linalg.inv((tet[:, 1:] - origin[:, None]).transpose(0, 2, 1))
tree = cKDTree(tet.mean(axis=1))

with h5py.File("helium_mesh.h5", "r+") as mesh:
    info = mesh["ElemInfo"][:]
    xyz = mesh["NodeCoords"][:]
    if len(xyz) != 8*len(info) or np.max(np.abs(xyz)) > 0.002:
        raise RuntimeError("Expected eight linear geometry nodes per hex, in metres")
    center = xyz.reshape(-1, 8, 3).mean(axis=1)*1e6
    found = np.zeros(len(center), dtype=int)
    for k in (12, 64, 256, len(tet)):
        missing = np.flatnonzero(found == 0)
        if not len(missing):
            break
        for chunk in np.array_split(missing, (len(missing)+999)//1000):
            point = center[chunk]
            _, index = tree.query(point, k=min(k, len(tet)))
            local = np.einsum("nkij,nkj->nki", inv[index], point[:, None] - origin[index])
            inside = (local.min(axis=2) >= -1e-7) & (local.sum(axis=2) <= 1+1e-7)
            rows = np.flatnonzero(inside.any(axis=1))
            found[chunk[rows]] = zone[index[rows, inside[rows].argmax(axis=1)]]
    if np.any(found == 0) or set(found) != {1, 2}:
        raise RuntimeError("Mesh material assignment failed")
    for material in (1, 2):
        if np.count_nonzero(found == material) != 4*np.count_nonzero(zone == material):
            raise RuntimeError(f"Unexpected number of hex children in material {material}")
    mesh["ElemInfo"][:, 1] = found
    print(f"Helium: {np.count_nonzero(found == 1)} hexes; quartz: {np.count_nonzero(found == 2)} hexes.")
