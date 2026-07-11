"""Inspect Arkanaut Company structure in BSData library."""
import xml.etree.ElementTree as ET

NS = "{http://www.battlescribe.net/schema/catalogueSchema}"

xml = open("./_ko_lib.cat", "r", encoding="utf-8").read()
root = ET.fromstring(xml)


def walk(elem, depth=0):
    tag = elem.tag.replace(NS, "")
    name = elem.get("name") or ""
    typ = elem.get("type") or ""
    indent = "  " * depth
    label = f"{indent}<{tag}"
    if name:
        label += f" name={name!r}"
    if typ:
        label += f" type={typ!r}"
    if tag == "constraint":
        label += f" field={elem.get('field')} val={elem.get('value')} scope={elem.get('scope')}"
    label += ">"
    print(label)
    for child in elem:
        walk(child, depth + 1)


for entry in root.findall(NS + "sharedSelectionEntries/" + NS + "selectionEntry"):
    name = entry.get("name") or ""
    if "Arkanaut Company" == name:
        walk(entry)
        break
else:
    print("not found in sharedSelectionEntries")
