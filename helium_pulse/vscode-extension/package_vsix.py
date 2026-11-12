"""Build the local VSIX package using the Python standard library."""
import json
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile


root = Path(__file__).resolve().parent
metadata = json.loads((root/"package.json").read_text(encoding="utf-8"))
manifest = ET.Element("PackageManifest", {
    "Version": "2.0.0",
    "xmlns": "http://schemas.microsoft.com/developer/vsx-schema/2011",
})
info = ET.SubElement(manifest, "Metadata")
ET.SubElement(info, "Identity", Id=metadata["name"], Publisher=metadata["publisher"],
              Version=metadata["version"], Language="zh-CN")
for name, field in (("DisplayName", "displayName"), ("Description", "description")):
    ET.SubElement(info, name).text = metadata[field]
ET.SubElement(info, "Categories").text = ",".join(metadata["categories"])
properties = ET.SubElement(info, "Properties")
ET.SubElement(properties, "Property", Id="Microsoft.VisualStudio.Code.Engine", Value=metadata["engines"]["vscode"])
installation = ET.SubElement(manifest, "Installation")
ET.SubElement(installation, "InstallationTarget", Id="Microsoft.VisualStudio.Code")
assets = ET.SubElement(manifest, "Assets")
ET.SubElement(assets, "Asset", Type="Microsoft.VisualStudio.Code.Manifest", Path="extension/package.json",
              Addressable="true")

types = ET.Element("Types", {"xmlns": "http://schemas.openxmlformats.org/package/2006/content-types"})
for suffix, mime in (("vsixmanifest", "text/xml"), ("json", "application/json"), ("js", "application/javascript"),
                     ("html", "text/html"), ("css", "text/css")):
    ET.SubElement(types, "Default", Extension=suffix, ContentType=mime)

target = root/"PICLas-Workbench.vsix"
with ZipFile(target, "w", compression=ZIP_DEFLATED) as package:
    package.writestr("extension.vsixmanifest", ET.tostring(manifest, encoding="utf-8", xml_declaration=True))
    package.writestr("[Content_Types].xml", ET.tostring(types, encoding="utf-8", xml_declaration=True))
    for item in ["package.json", "extension.js", "media/index.html", "media/workbench.css", "media/workbench.js"]:
        package.write(root/item, "extension/"+item)
print(target)
