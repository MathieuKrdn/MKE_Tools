"""Copernicus comp from a Karma multi-AOV EXR (After Effects replacement).

Subtractive build: residual = C - sum(passes), then residual + graded passes.
With every gain at 1 the result is the beauty (alpha from C), so muting a
pass (gain 0) removes exactly its contribution from the beauty.
"""
import os
import re

import hou

# Karma light components; combined<X> wins over direct<X> + indirect<X>
COMPONENTS = ("diffuse", "glossyreflection", "glossytransmission",
              "diffusetransmission", "emission", "volume", "coat", "sss")
FRAME_RE = re.compile(r"(\d+)(\.exr)$", re.IGNORECASE)


def light_passes(aovs):
    """Default passes summing to the beauty, without double counting."""
    out = []
    for c in COMPONENTS:
        if "combined" + c in aovs:
            out.append("combined" + c)
        else:
            out += [a for a in ("direct" + c, "indirect" + c) if a in aovs]
            if c in aovs:
                out.append(c)
    if not out:  # no LPE passes: fall back to light groups
        out = [a for a in aovs if a.startswith("C_")]
    return out


def sequence_path(path):
    """name.1250.exr -> (name.$F4.exr, first, last) from the files on disk."""
    path = path.replace("\\", "/")
    m = FRAME_RE.search(path)
    if not m:
        return path, None, None
    pad = len(m.group(1))
    head = path[:m.start(1)]
    frames = []
    folder = os.path.dirname(path)
    base = os.path.basename(head)
    for f in os.listdir(folder):
        fm = FRAME_RE.search(f)
        if fm and f[:fm.start(1)] == base and len(fm.group(1)) == pad:
            frames.append(int(fm.group(1)))
    return head + "$F%d" % pad + m.group(2), min(frames), max(frames)


def read_aovs(file_node):
    file_node.parm("addaovs").pressButton()
    return list(file_node.outputNames())


def build(exr_path, passes=None, parent=None, name=None):
    """Create the copnet. passes=None -> light_passes(). Returns the copnet."""
    seq, first, last = sequence_path(exr_path)
    name = name or re.sub(r"[^A-Za-z0-9_]", "_",
                          os.path.basename(seq).split(".")[0])
    parent = parent or hou.node("/img") or hou.node("/obj")
    net = parent.createNode("copnet", "comp_" + name)

    src = net.createNode("file", "render")
    src.parm("filename").set(exr_path.replace("\\", "/"))  # a frame that exists
    aovs = read_aovs(src)
    src.parm("filename").set(seq)
    if "C" not in aovs:
        raise hou.Error("No beauty (C) AOV in %s" % exr_path)
    passes = [p for p in (passes or light_passes(aovs)) if p in aovs]
    if not passes:
        raise hou.Error("No light pass found in %s" % exr_path)

    def blend(mode, bg, fg, fg_out, label):
        b = net.createNode("blend", label)
        b.parm("mode").set(mode)
        b.parm("scopergba").set(7)  # rgb only, alpha stays the beauty's
        b.setInput(0, bg)
        b.setInput(1, fg, src.outputIndex(fg_out) if fg is src else 0)
        return b

    # residual = C - passes: whatever the passes don't cover (keeps comp == beauty)
    node = net.createNode("null", "beauty")
    node.setInput(0, src, src.outputIndex("C"))
    for p in passes:
        node = blend("subtract", node, src, p, "minus_" + p)
    node = grade(net, node, "residual")
    node.setColor(hou.Color(0.4, 0.4, 0.4))

    for p in passes:
        g = grade(net, src, p, src.outputIndex(p))
        g.setColor(hou.Color(1, 0.8, 0.2))
        node = blend("add", node, g, None, "plus_" + p)

    out = net.createNode("null", "OUT")
    out.setInput(0, node)
    out.setDisplayFlag(True)

    rop = net.createNode("rop_image", "write_comp")
    rop.setInput(0, out)
    rop.parm("copoutput").set(os.path.dirname(seq) + "/comp/" + name + "_comp.$F4.exr")
    if first is not None:
        rop.parm("trange").set(1)
        for parm, v in (("f1", first), ("f2", last), ("f3", 1)):
            rop.parm(parm).deleteAllKeyframes()
            rop.parm(parm).set(v)

    net.layoutChildren()
    return net


def grade(net, inp, label, out_index=0):
    """Per-pass knob: bright = gain (0 mutes, -1 subtracts twice), tint = color."""
    g = net.createNode("bright", label)
    g.setInput(0, inp, out_index)
    return g


def compFromRender():
    """MK Utils entry: pick a Karma EXR, pick the passes, build the comp."""
    path = hou.ui.selectFile(title="Karma multi-AOV EXR (any frame)",
                             pattern="*.exr", chooser_mode=hou.fileChooserMode.Read)
    if not path:
        return
    path = hou.text.expandString(path)
    probe = hou.node("/obj").createNode("copnet")
    try:
        f = probe.createNode("file")
        f.parm("filename").set(path)
        aovs = sorted(a for a in read_aovs(f)
                      if a != "C" and not a.startswith("Crypto"))
    finally:
        probe.destroy()
    default = light_passes(aovs)
    picked = hou.ui.selectFromList(
        aovs, default_choices=[aovs.index(a) for a in default],
        title="Copernicus Comp", column_header="Passes",
        message="Passes added back on the beauty.\n"
                "Pick passes that don't overlap (combined X = direct X + indirect X);\n"
                "what they don't cover goes to 'residual'.")
    if not picked:
        return
    net = build(path, [aovs[i] for i in picked])
    net.setCurrent(True, clear_all_selected=True)
    pane = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
    if pane:
        pane.setPwd(net)
    hou.ui.setStatusMessage("Comp built in %s" % net.path())
