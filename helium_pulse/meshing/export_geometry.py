"""Export named CAD regions for inspection in ParaView."""
from pathlib import Path
from xml.etree import ElementTree as ET

import meshio

mesh = meshio.read("geometry.msh")
directory = Path("model")
directory.mkdir(exist_ok=True)
root = ET.Element("VTKFile", type="vtkMultiBlockDataSet", version="1.0", byte_order="LittleEndian")
blocks = ET.SubElement(root, "vtkMultiBlockDataSet")
names = ("BC_HV", "BC_Ground", "BC_Quartz", "BC_Outer", "Helium", "Quartz")
for index, name in enumerate(name for name in names if name in mesh.field_data):
    tag, dimension = mesh.field_data[name]
    shapes = {2: ("triangle", "quad"), 3: ("tetra", "hexahedron")}[dimension]
    shape = next(shape for shape in shapes if shape in mesh.cells_dict)
    mask = mesh.get_cell_data("gmsh:physical", shape) == tag
    file = f"{name}.vtu"
    meshio.write(directory / file, meshio.Mesh(mesh.points * 1e-6, [(shape, mesh.get_cells_type(shape)[mask])]))
    ET.SubElement(blocks, "DataSet", index=str(index), name=name, file=file)
ET.ElementTree(root).write(directory / "helium_geometry.vtm", encoding="utf-8", xml_declaration=True)
