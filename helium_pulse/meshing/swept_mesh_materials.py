"""Restore physical region IDs after PyHOPE reorders swept hexahedra."""
import h5py
import numpy as np
from scipy.spatial import cKDTree

with np.load("swept_regions.npz") as regions:
    centers = regions["centers"]
    zones = regions["zones"]
with h5py.File("helium_mesh.h5", "r+") as mesh:
    converted = mesh["NodeCoords"][:].reshape(-1, 8, 3).mean(axis=1)*1e6
    distance, index = cKDTree(centers).query(converted)
    if len(converted) != len(centers) or len(np.unique(index)) != len(centers) or np.max(distance) > 1e-7:
        raise RuntimeError("Could not match the swept cells to the imported mesh")
    mesh["ElemInfo"][:, 1] = zones[index]
    print(f"Imported helium: {(zones == 1).sum()}, quartz: {(zones == 2).sum()} swept hexes")
