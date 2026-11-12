"""Data and ParaView helpers for the VS Code PICLas workbench."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parent
NITROGEN = ROOT.parent / "official_streamer" / "pic-mcc"
FIELDS = {"几何 / 材料": "", "电子密度 (m⁻³)": "ElectronDensityCell",
          "电势 (V)": "Phi", "电场强度 (V/m)": "E"}
PARAMETERS = {
    "PulsePeak": ("正峰值电压 (V)", 1), "PulseRise": ("上升沿 (ns)", 1e9),
    "PulseFlat": ("平顶 (ns)", 1e9), "PulseFall": ("下降沿 (ns)", 1e9),
    "ManualTimeStep": ("步长 (ps)", 1e12), "Analyze_dt": ("输出间隔 (ns)", 1e9),
    "DielectricZoneEpsR": ("石英相对介电常数", 1),
    "Part-Species1-Init1-PartDensity": ("氦气数密度 (m⁻³)", 1),
    "Part-Species1-Init1-MWTemperatureIC": ("氦气温度 (K)", 1),
}


def parameter_values(path):
    return {k.strip(): float(v.strip().removeprefix("(/").removesuffix("/)"))
            for k, v in re.findall(r"^([^!\r\n=]+?)\s*=\s*([^!\r\n]+)", path.read_text(), re.M)
            if k.strip() in PARAMETERS}


def frame_stamp(path):
    return float(path.stem.rsplit("_", 1)[-1])


def case_info(path):
    metadata = path/"case-info.json"
    return json.loads(metadata.read_text(encoding="utf-8")) if metadata.is_file() else {}


def make_series(directory, field):
    pattern = "*_Solution_ElemData_*.vtu" if field == "ElectronDensityCell" else "*_Solution_0*.vtu"
    files = sorted(directory.glob(pattern), key=frame_stamp)
    if not files:
        raise ValueError("此运行目录还没有对应的 VTU 时间序列")
    target = (ROOT if directory == NITROGEN else directory) / (
        f"{'nitrogen' if directory == NITROGEN else 'helium'}_{'density' if field == 'ElectronDensityCell' else 'fields'}.pvd")
    collection = ET.Element("VTKFile", type="Collection", version="0.1", byte_order="LittleEndian")
    timeline = ET.SubElement(collection, "Collection")
    for file in files:
        ET.SubElement(timeline, "DataSet", timestep=str(frame_stamp(file)), group="", part="0",
                      file=os.path.relpath(file, target.parent).replace(os.sep, "/"))
    ET.ElementTree(collection).write(target, encoding="utf-8", xml_declaration=True)
    return target


def launch_paraview(series):
    executable = os.environ.get("PICLAS_PARAVIEW") or shutil.which("paraview")
    if not executable and os.name == "nt":
        folders = [os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")]
        candidates = [candidate for folder in folders if folder
                      for pattern in ("ParaView*/bin/paraview.exe", "Programs/ParaView*/bin/paraview.exe")
                      for candidate in Path(folder).glob(pattern)]
        executable = next(iter(sorted(candidates, reverse=True)), None)
    if not executable or not Path(executable).is_file():
        raise ValueError("请安装 ParaView，或将 PICLAS_PARAVIEW 指向 paraview.exe。")
    subprocess.Popen([str(executable), f"--data={series}"])
