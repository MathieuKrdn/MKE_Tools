"""Copernicus comp from Karma render layers (After Effects replacement).

One multi-AOV EXR sequence per render layer. Per layer, subtractive build:
residual = C - sum(passes), then residual + graded passes. With every gain at
1 each layer is its beauty (alpha from C), so muting a pass (gain 0) removes
exactly its contribution. Layers are then stacked with 'over', first picked
at the bottom.
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


def _shorten(names):
    """Drop what all names share, cut on '_'. None if that isn't unique."""
    if len(names) == 1:
        return names
    pre = os.path.commonprefix(names).rfind("_") + 1
    suf = os.path.commonprefix([n[::-1] for n in names]).rfind("_") + 1
    short = [n[pre:len(n) - suf].strip("_") for n in names]
    return short if all(short) and len(set(short)) == len(short) else None


def layer_labels(paths):
    """Short unique layer names. Tries the folders+file name without versions
    (.../withFX/shot_v0002 -> withFX), then the file names (shot_v0001 -> v0001)."""
    clean = lambda t: re.sub(r"[^A-Za-z0-9_]", "_", t)
    seqs = [sequence_path(p)[0] for p in paths]
    bases = [clean(re.sub(r"[._]?\$F\d.*$", "", os.path.basename(s))) for s in seqs]
    keys = [clean(re.sub(r"/v\d+(?=/|$)", "", os.path.dirname(s)) + "/" +
                  re.sub(r"_v\d+$", "", b)) for s, b in zip(seqs, bases)]
    names = bases if len(bases) == 1 else _shorten(keys) or _shorten(bases) or bases
    return ["L" + n if n[:1].isdigit() else n for n in names]


def find_layers(root):
    """Render layers under a folder: one EXR per sequence, latest vNNN folder only.
    Skips comp outputs and backups."""
    latest = {}
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != "comp" and not d.startswith("_")]
        folder = folder.replace("\\", "/")
        seqs = {}
        for f in sorted(files):
            m = FRAME_RE.search(f)
            if m:
                seqs.setdefault(f[:m.start(1)], folder + "/" + f)
        for head, path in seqs.items():
            m = re.search(r"/v(\d+)$", folder)
            key = (folder[:m.start()] if m else folder, re.sub(r"(_v\d+)?[._]*$", "", head))
            version = int(m.group(1)) if m else 0
            if key not in latest or version > latest[key][0]:
                latest[key] = (version, path)
    return [p for _, p in sorted(latest.values(), key=lambda v: v[1])]


def build_layer(net, path, label, passes=None):
    """File COP + subtractive rebuild of one render layer. Returns its last node."""
    seq = sequence_path(path)[0]
    src = net.createNode("file", label)
    src.parm("filename").set(path.replace("\\", "/"))  # a frame that exists, $F4 breaks addaovs
    aovs = read_aovs(src)
    src.parm("filename").set(seq)
    if "C" not in aovs:
        raise hou.Error("No beauty (C) AOV in %s" % path)
    # a layer with none of the picked passes stays its beauty (residual only)
    passes = [p for p in (passes or light_passes(aovs)) if p in aovs]
    nodes = [src]

    def blend(mode, bg, fg, fg_index, name):
        b = net.createNode("blend", "%s_%s" % (label, name))
        b.parm("mode").set(mode)
        b.parm("scopergba").set(7)  # rgb only, alpha stays the beauty's
        b.setInput(0, bg)
        b.setInput(1, fg, fg_index)
        nodes.append(b)
        return b

    # residual = C - passes: whatever the passes don't cover (keeps comp == beauty)
    node = net.createNode("null", label + "_beauty")
    node.setInput(0, src, src.outputIndex("C"))
    nodes.append(node)
    for p in passes:
        node = blend("subtract", node, src, src.outputIndex(p), "minus_" + p)
    node = grade(net, node, label + "_residual")
    node.setColor(hou.Color(0.4, 0.4, 0.4))
    nodes.append(node)

    for p in passes:
        g = grade(net, src, "%s_%s" % (label, p), src.outputIndex(p))
        g.setColor(hou.Color(1, 0.8, 0.2))
        nodes.append(g)
        node = blend("add", node, g, 0, "plus_" + p)

    box = net.createNetworkBox(label + "_box")
    box.setComment(label)
    for n in nodes:
        box.addItem(n)
    return node


def build(paths, passes=None, parent=None, name=None):
    """Create the copnet. paths: one EXR (any frame) per render layer, bottom first.
    passes=None -> light_passes() per layer."""
    if isinstance(paths, str):
        paths = [paths]
    seq = sequence_path(paths[0])[0]
    name = name or re.sub(r"[^A-Za-z0-9_]", "_",
                          os.path.basename(seq).split(".")[0])
    parent = parent or hou.node("/img") or hou.node("/obj")
    net = parent.createNode("copnet", "comp_" + name)

    node = None
    first = last = None
    for path, label in zip(paths, layer_labels(paths)):
        top = build_layer(net, path, label, passes)
        if node is None:
            node = top
        else:
            over = net.createNode("blend", "over_" + label)
            over.parm("mode").set("over")
            over.setInput(0, node)
            over.setInput(1, top)
            node = over
        f1, f2 = sequence_path(path)[1:]
        if f1 is not None:
            first = f1 if first is None else min(first, f1)
            last = f2 if last is None else max(last, f2)

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
    for box in net.networkBoxes():
        box.fitAroundContents()
    return net


def grade(net, inp, label, out_index=0):
    """Per-pass knob: bright = gain (0 mutes, -1 subtracts twice), tint = color."""
    g = net.createNode("bright", label)
    g.setInput(0, inp, out_index)
    return g


def compFromRender():
    """MK Utils entry: pick the render layers, pick the passes, build the comp."""
    mode = hou.ui.displayMessage(
        "Build the comp from:", buttons=("Render folder", "EXR files", "Cancel"),
        default_choice=0, close_choice=2, title="Copernicus Comp",
        details="Render folder: every EXR sequence below it is a layer "
                "(latest vNNN folder only, 'comp' and '_backup' folders skipped).")
    if mode == 2:
        return
    if mode == 0:
        root = hou.ui.selectFile(title="Render folder holding the layers",
                                 file_type=hou.fileType.Directory)
        paths = find_layers(hou.text.expandString(root)) if root else []
        if root and not paths:
            raise hou.Error("No EXR sequence under " + root)
    else:
        picked_files = hou.ui.selectFile(
            title="Render layers: one EXR per layer (any frame)",
            pattern="*.exr", chooser_mode=hou.fileChooserMode.Read, multiple_select=True)
        paths = [hou.text.expandString(p.strip())
                 for p in picked_files.split(";") if p.strip()]
    if not paths:
        return
    if len(paths) > 1:
        labels = layer_labels(paths)
        btn, text = hou.ui.readInput(
            "Stacking order, background first (edit to reorder):",
            buttons=("OK", "Cancel"), title="Copernicus Comp",
            initial_contents=", ".join(labels))
        if btn:
            return
        order = [t.strip() for t in text.split(",") if t.strip()]
        if sorted(order) != sorted(labels):
            raise hou.Error("Order must list these layers once each: " + ", ".join(labels))
        paths = [paths[labels.index(t)] for t in order]
    probe = hou.node("/obj").createNode("copnet")
    try:
        aovs = set()
        for p in paths:
            f = probe.createNode("file")
            f.parm("filename").set(p)
            aovs.update(read_aovs(f))
    finally:
        probe.destroy()
    aovs = sorted(a for a in aovs if a != "C" and not a.startswith("Crypto"))
    default = light_passes(aovs)
    picked = hou.ui.selectFromList(
        aovs, default_choices=[aovs.index(a) for a in default],
        title="Copernicus Comp", column_header="Passes",
        message="Passes added back on each layer's beauty (C).\n"
                "Pick passes that don't overlap (combined X = direct X + indirect X);\n"
                "what they don't cover goes to the layer's 'residual'.")
    if not picked:
        return
    net = build(paths, [aovs[i] for i in picked])
    net.setCurrent(True, clear_all_selected=True)
    pane = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
    if pane:
        pane.setPwd(net)
    hou.ui.setStatusMessage("Comp built in %s" % net.path())
