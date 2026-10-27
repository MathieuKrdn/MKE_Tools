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


def load_sources(net, paths):
    """One file COP per EXR. Returns ({pass: (file node, output index)}, frame range).
    A pass is the AOV name, the file name for a one-AOV file (pass per file),
    or <file>_<aov> when several files share that AOV."""
    found = []
    first = last = None
    for path in paths:
        path = path.replace("\\", "/")
        seq, f1, f2 = sequence_path(path)
        label = re.sub(r"[^A-Za-z0-9_]", "_", os.path.basename(seq).split(".")[0])
        f = net.createNode("file", "in_" + label if not net.node("in_" + label) else None)
        f.parm("filename").set(path)  # a frame that exists, $F4 breaks addaovs
        aovs = read_aovs(f)
        f.parm("filename").set(seq)
        found += [(label, a, f, len(aovs) == 1) for a in aovs]
        if f1 is not None:
            first = f1 if first is None else min(first, f1)
            last = f2 if last is None else max(last, f2)
    count = {}
    for _, a, _, _ in found:
        count[a] = count.get(a, 0) + 1
    sources = {}
    for label, a, f, alone in found:
        key = label if alone else a if count[a] == 1 else "%s_%s" % (label, a)
        sources[key] = (f, f.outputIndex(a))
    return sources, first, last


def find_beauty(sources):
    """'C', else a pass file named *beauty*."""
    if "C" in sources:
        return "C"
    return next((k for k in sources if "beauty" in k.lower()), None)


def pass_choices(sources):
    """Passes offered to the user (not the beauty, not cryptomattes)."""
    beauty = find_beauty(sources)
    return sorted(k for k in sources if k != beauty and "Crypto" not in k)


def build(paths, passes=None, parent=None, name=None):
    """Create the copnet from one or more EXRs. passes=None -> light_passes()."""
    if isinstance(paths, str):
        paths = [paths]
    seq = sequence_path(paths[0].replace("\\", "/"))[0]
    name = name or re.sub(r"[^A-Za-z0-9_]", "_",
                          os.path.basename(seq).split(".")[0])
    parent = parent or hou.node("/img") or hou.node("/obj")
    net = parent.createNode("copnet", "comp_" + name)

    sources, first, last = load_sources(net, paths)
    beauty = sources.get(find_beauty(sources))
    choices = pass_choices(sources)
    passes = [p for p in (passes or light_passes(choices) or choices)
              if p in sources]
    if not passes:
        raise hou.Error("No light pass found in %s" % ", ".join(paths))

    def blend(mode, bg, fg, fg_index, label):
        b = net.createNode("blend", label)
        b.parm("mode").set(mode)
        b.parm("scopergba").set(7)  # rgb only, alpha stays the beauty's
        b.setInput(0, bg)
        b.setInput(1, fg, fg_index)
        return b

    node = None
    if beauty:
        # residual = C - passes: whatever the passes don't cover (keeps comp == beauty)
        node = net.createNode("null", "beauty")
        node.setInput(0, *beauty)
        for p in passes:
            node = blend("subtract", node, sources[p][0], sources[p][1], "minus_" + p)
        node = grade(net, node, "residual")
        node.setColor(hou.Color(0.4, 0.4, 0.4))

    for p in passes:
        g = grade(net, sources[p][0], p, sources[p][1])
        g.setColor(hou.Color(1, 0.8, 0.2))
        # no beauty: plain sum of the passes, alpha from the first one
        node = blend("add", node, g, 0, "plus_" + p) if node else g

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
    """MK Utils entry: pick one or more EXRs, pick the passes, build the comp."""
    picked_files = hou.ui.selectFile(
        title="Render EXRs: one multi-AOV file or several pass files (any frame)",
        pattern="*.exr", chooser_mode=hou.fileChooserMode.Read, multiple_select=True)
    paths = [hou.text.expandString(p.strip())
             for p in picked_files.split(";") if p.strip()]
    if not paths:
        return
    probe = hou.node("/obj").createNode("copnet")
    try:
        aovs = pass_choices(load_sources(probe, paths)[0])
    finally:
        probe.destroy()
    default = light_passes(aovs) or aovs  # pass files: all of them
    picked = hou.ui.selectFromList(
        aovs, default_choices=[aovs.index(a) for a in default],
        title="Copernicus Comp", column_header="Passes",
        message="Passes added back on the beauty (C).\n"
                "Pick passes that don't overlap (combined X = direct X + indirect X);\n"
                "what they don't cover goes to 'residual'.")
    if not picked:
        return
    net = build(paths, [aovs[i] for i in picked])
    net.setCurrent(True, clear_all_selected=True)
    pane = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
    if pane:
        pane.setPwd(net)
    hou.ui.setStatusMessage("Comp built in %s" % net.path())
