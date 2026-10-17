"""Karma / MaterialX material from a folder of textures, every map plugged automatically.

materialFromFolder() asks for a folder and builds a Karma Material Builder in a Material Library LOP
(the selected one, or /stage/mke_materials). build() does the work and can run without UI.
"""
import os
import re

import hou
import voptoolutils

IMAGE_EXT = (".exr", ".tif", ".tiff", ".png", ".jpg", ".jpeg", ".tx", ".rat", ".tga", ".hdr")
UDIM_RE = re.compile(r"([._])(1\d{3})(\.[^.]+)$")

# channel: (keywords in the file name, image signature, colour data?)
CHANNELS = {
    "base_color": (("basecolor", "base_color", "albedo", "diffuse", "diff", "color", "col"), "color3", True),
    "specular_roughness": (("roughness", "rough", "rgh"), "default", False),
    "metalness": (("metalness", "metallic", "metal", "mtl"), "default", False),
    "normal": (("normal", "nrm", "nor", "nml"), "vector3", False),
    "displacement": (("displacement", "height", "disp", "bump"), "default", False),
    "opacity": (("opacity", "alpha", "mask"), "color3", False),
    "emission_color": (("emissive", "emission", "emit"), "color3", True),
    "occlusion": (("ambientocclusion", "occlusion", "ao"), None, False),  # no slot in standard_surface: reported
}


def _tokens(filename):
    stem = os.path.splitext(filename)[0].lower()
    return set(re.split(r"[^a-z0-9]+", stem)) | {stem.replace("_", "").replace("-", "")}


def classify(folder):
    """{channel: path} picked from the folder (UDIM tiles collapsed to <UDIM>), plus the unused files."""
    files = sorted(f for f in os.listdir(folder) if f.lower().endswith(IMAGE_EXT))
    found, unused = {}, []
    for name in files:
        tokens = _tokens(name)
        lower = name.lower()
        channel = None
        for key, (words, _, _) in CHANNELS.items():
            if any(w in tokens or (len(w) > 4 and w in lower) for w in words):
                channel = key
                break
        if channel == "normal" and ("dx" in tokens or "directx" in tokens) and any("gl" in _tokens(f) for f in files):
            channel = None  # keep the OpenGL normal map when both exist
        path = os.path.join(folder, name).replace("\\", "/")
        path = UDIM_RE.sub(r"\1<UDIM>\3", path)
        if channel and channel not in found:
            found[channel] = path
        elif not (channel and found.get(channel) == path):
            unused.append(name)
    return found, unused


def material_library(parent=None):
    """The selected Material Library LOP, else /stage/mke_materials (created once)."""
    for node in hou.selectedNodes():
        if node.type().name() == "materiallibrary":
            return node
    stage = hou.node("/stage")
    return stage.node("mke_materials") or stage.createNode("materiallibrary", "mke_materials")


def build(folder, name=None, library=None):
    """Create the material. Returns (builder node, {channel: path}, [unused files])."""
    found, unused = classify(folder)
    if not found:
        raise ValueError("Aucune texture reconnue dans ce dossier.")
    library = library or material_library()
    name = re.sub(r"[^A-Za-z0-9_]+", "_", name or os.path.basename(os.path.normpath(folder))).strip("_") or "material"
    builder = voptoolutils._setupMtlXBuilderSubnet(destination_node=library, name=name,
                                                   mask=voptoolutils.KARMAMTLX_TAB_MASK,
                                                   folder_label="Karma Material Builder", render_context="kma")
    surface = builder.node("mtlxstandard_surface")
    displacement = builder.node("mtlxdisplacement")
    y = 0.0
    for channel, path in found.items():
        words, signature, is_color = CHANNELS[channel]
        if signature is None:
            continue
        image = builder.createNode("mtlximage", channel)
        image.parm("signature").set(signature)
        image.parm("file").set(path)
        if not is_color and image.parm("filecolorspace") is not None:
            image.parm("filecolorspace").set("raw")  # data maps must not be colour-managed
        image.setPosition(hou.Vector2(-4.5, y))
        y -= 1.6
        if channel == "normal":
            normal_map = builder.createNode("mtlxnormalmap", "normal_map")
            normal_map.setInput(0, image)
            normal_map.setPosition(hou.Vector2(-2.2, image.position()[1]))
            surface.setNamedInput("normal", normal_map, 0)
        elif channel == "displacement":
            displacement.setNamedInput("displacement", image, 0)
            displacement.parm("scale").set(0.05)
        else:
            surface.setNamedInput(channel, image, 0)
            if channel == "emission_color":
                surface.parm("emission").set(1)
    library.layoutChildren()
    return builder, found, unused


def materialFromFolder():
    """MK Utils > Matériau depuis un dossier de textures."""
    from hutil.Qt import QtWidgets
    start = hou.getenv("JOB") or os.path.expanduser("~")
    folder = QtWidgets.QFileDialog.getExistingDirectory(hou.qt.mainWindow(), "Dossier de textures", start)
    if not folder:
        return None
    try:
        builder, found, unused = build(folder)
    except ValueError as error:
        hou.ui.displayMessage(str(error), severity=hou.severityType.Warning)
        return None
    labels = {"base_color": "Base color", "specular_roughness": "Roughness", "metalness": "Metalness", "normal": "Normal",
              "displacement": "Displacement", "opacity": "Opacity", "emission_color": "Emission", "occlusion": "AO (non branché)"}
    lines = [f"{labels[c]} : {os.path.basename(p)}" for c, p in found.items()]
    if unused:
        lines.append(f"\nNon utilisés : {', '.join(unused[:8])}")
    builder.setSelected(True, clear_all_selected=True)
    editor = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
    if editor is not None:
        editor.setCurrentNode(builder)
    hou.ui.displayMessage(f"Matériau « {builder.name()} » créé dans {builder.parent().path()}\n\n" + "\n".join(lines),
                          title="Matériau depuis textures")
    return builder
