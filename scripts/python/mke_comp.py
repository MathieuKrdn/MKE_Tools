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


def _shorten(names, unique=True):
    """Drop what all names share, cut on '_'. None if a name ends up empty
    (or, with unique, if two names end up equal)."""
    if len(names) == 1:
        return names
    pre = os.path.commonprefix(names).rfind("_") + 1
    suf = os.path.commonprefix([n[::-1] for n in names]).rfind("_") + 1
    short = [n[pre:len(n) - suf].strip("_") for n in names]
    if not all(short) or (unique and len(set(short)) < len(short)):
        return None
    return short


def _number_duplicates(names):
    """rop_character twice -> rop_character, rop_character_2."""
    seen = {}
    out = []
    for n in names:
        seen[n] = seen.get(n, 0) + 1
        out.append(n if seen[n] == 1 else "%s_%d" % (n, seen[n]))
    return out


def layer_labels(paths):
    """Short unique layer names. File names first, without what they share
    (shot.usdrender_rop_character -> rop_character, re-renders numbered _2),
    then the folders (.../withFX/shot_v0002 -> withFX), then the versions."""
    clean = lambda t: re.sub(r"[^A-Za-z0-9_]", "_", t)
    seqs = [sequence_path(p)[0] for p in paths]
    bases = [clean(re.sub(r"[._]?\$F\d.*$", "", os.path.basename(s))) for s in seqs]
    keys = [clean(re.sub(r"/v\d+(?=/|$)", "", os.path.dirname(s)) + "/" +
                  re.sub(r"_v\d+$", "", b)) for s, b in zip(seqs, bases)]
    by_file = _shorten([re.sub(r"_v\d+$", "", b) for b in bases], unique=False)
    if len(bases) == 1:
        names = bases
    elif by_file and len(set(by_file)) > 1:
        names = _number_duplicates(by_file)
    else:
        names = _shorten(keys) or _shorten(bases) or bases
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


# ---------------------------------------------------------------- layer types
# keyword at the start of a name token -> type; colour shared by the window and the network
TYPE_KEYS = (("FX", ("fx", "pyro", "flip", "smoke", "wave", "splash")),
             ("CHAR", ("char", "hero", "crowd")),
             ("CAR", ("car", "vehicle")),
             ("UI", ("ui", "hud", "text", "title")),
             ("BG", ("bg", "background", "env", "set", "sky")))
TYPES = ("BG", "CAR", "CHAR", "FX", "UI", "OTHER")
TYPE_COLORS = {"BG": "#6f9be0", "CAR": "#4fc1b3", "CHAR": "#f0a24a",
               "FX": "#b392f0", "UI": "#b5b5b5", "OTHER": "#8c96a8"}


def layer_type(label):
    tokens = [t for t in label.lower().split("_") if t]
    for kind, keys in TYPE_KEYS:
        if any(t.startswith(k) for t in tokens for k in keys):
            return kind
    return "OTHER"


def hou_color(kind):
    h = TYPE_COLORS.get(kind, TYPE_COLORS["OTHER"]).lstrip("#")
    return hou.Color(*(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)))


def frame_info(path):
    """(first, last, missing frames) of the sequence path belongs to."""
    seq, first, last = sequence_path(path)
    if first is None:
        return None, None, 0
    m = FRAME_RE.search(path.replace("\\", "/"))
    head = os.path.basename(path.replace("\\", "/")[:m.start(1)])
    count = sum(1 for f in os.listdir(os.path.dirname(path))
                if f.startswith(head) and FRAME_RE.search(f)
                and len(FRAME_RE.search(f).group(1)) == len(m.group(1)))
    return first, last, (last - first + 1) - count


# ---------------------------------------------------------------- one layer = one subnet
GRID_X, GRID_Y = 3.2, 1.3  # network units between columns / rows inside a layer


def knob_values(sub):
    """Spare parm values of a layer node, to carry over a rebuild."""
    return {p.name(): p.eval() for p in sub.spareParms()
            if p.parmTemplate().type() in (hou.parmTemplateType.Float,
                                           hou.parmTemplateType.Toggle)}


def _knob_templates(passes):
    layer = hou.FolderParmTemplate("layer_f", "Layer", folder_type=hou.folderType.Simple)
    layer.addParmTemplate(hou.FloatParmTemplate("exposure", "Exposure (stops)", 1, (0,),
                                                min=-5, max=5))
    layer.addParmTemplate(hou.FloatParmTemplate("opacity", "Opacity", 1, (1,), min=0, max=1,
                                                min_is_strict=True, max_is_strict=True))
    layer.addParmTemplate(hou.FloatParmTemplate("residual", "Residual Gain", 1, (1,), min=0, max=2,
                                                help="What the passes don't cover (beauty - passes)."))
    folder = hou.FolderParmTemplate("passes_f", "Passes", folder_type=hou.folderType.Simple)
    if not passes:
        folder.addParmTemplate(hou.LabelParmTemplate("nopass", "Passes", ("Beauty only",)))
    for p in passes:
        folder.addParmTemplate(hou.FloatParmTemplate("gain_" + p, p, 1, (1,), min=0, max=2,
                                                     join_with_next=True))
        folder.addParmTemplate(hou.FloatParmTemplate("tint_" + p, "Tint", 3, (1, 1, 1),
                                                     look=hou.parmLook.ColorSquare,
                                                     naming_scheme=hou.parmNamingScheme.RGBA,
                                                     join_with_next=True))
        folder.addParmTemplate(hou.ToggleParmTemplate("solo_" + p, "Solo", join_with_next=True))
        folder.addParmTemplate(hou.ToggleParmTemplate("mute_" + p, "Mute"))
    source = hou.FolderParmTemplate("source_f", "Source", folder_type=hou.folderType.Simple)
    source.addParmTemplate(hou.StringParmTemplate("source", "Render (info, use Swap)", 1,
                                                  string_type=hou.stringParmType.FileReference))
    for name, label, func in (("reload", "Reload AOVs", "on_reload"),
                              ("swap", "Swap to New Version...", "on_swap"),
                              ("reset", "Reset Gains", "on_reset")):
        source.addParmTemplate(hou.ButtonParmTemplate(
            name, label, join_with_next=name != "reset",
            script_callback="import mke_comp; mke_comp.%s(kwargs)" % func,
            script_callback_language=hou.scriptLanguage.Python))
    return layer, folder, source


def populate_layer(sub, path, passes=None, values=None):
    """(Re)build a layer subnet from one EXR (any frame): file on top, residual
    column on the left, one column per pass, the sum along the bottom, then
    layer_out (exposure, opacity). Knobs live on the subnet. Returns the passes."""
    for c in sub.children():
        if c.type().name() not in ("input", "output"):
            c.destroy()
    path = path.replace("\\", "/")
    seq = sequence_path(path)[0]
    src = sub.createNode("file", "render")
    src.parm("filename").set(path)  # a frame that exists, $F4 breaks addaovs
    aovs = read_aovs(src)
    src.parm("filename").set(seq)
    if "C" not in aovs:
        raise hou.Error("No beauty (C) AOV in %s" % path)
    passes = [p for p in (light_passes(aovs) if passes is None else passes) if p in aovs]

    group = sub.parmTemplateGroup()
    for name in ("layer_f", "passes_f", "source_f"):
        if group.find(name):
            group.remove(name)
    for t in _knob_templates(passes):
        group.append(t)
    sub.setParmTemplateGroup(group)
    sub.parm("source").set(seq)
    for name, v in (values or {}).items():
        parm = sub.parm(name)
        if parm is not None:
            parm.set(v)
    sub.setUserData("mke_comp_path", path)
    sub.setUserData("mke_comp_passes", ",".join(passes))

    solos = " + ".join('ch("../solo_%s")' % p for p in passes) or "0"
    top = -0.22 * len(aovs) - 1.6  # the file tile grows with its outputs
    src.setPosition(hou.Vector2(0, 0))

    def at(node, col, row):
        node.setPosition(hou.Vector2(col * GRID_X, top - row * GRID_Y))
        return node

    def blend(mode, bg, fg, fg_index, name, col, row):
        b = at(sub.createNode("blend", name), col, row)
        b.parm("mode").set(mode)
        b.parm("scopergba").set(7)  # rgb only, alpha stays the beauty's
        b.setInput(0, bg)
        b.setInput(1, fg, fg_index)
        return b

    node = at(sub.createNode("null", "beauty"), 0, 0)
    node.setInput(0, src, src.outputIndex("C"))
    for i, p in enumerate(passes):
        node = blend("subtract", node, src, src.outputIndex(p), "minus_" + p, 0, i + 1)
    chain = node
    node = at(sub.createNode("bright", "residual"), 0, len(passes) + 1)
    node.setInput(0, chain)
    node.parm("bright").setExpression('ch("../residual") * ((%s) == 0)' % solos)
    node.setColor(hou.Color(0.45, 0.45, 0.45))

    row = len(passes) + 2
    for i, p in enumerate(passes):
        g = at(sub.createNode("bright", p), i + 1, 0)
        g.setInput(0, src, src.outputIndex(p))
        g.parm("bright").setExpression(
            'ch("../gain_{0}") * (1 - ch("../mute_{0}")) * (ch("../solo_{0}") || (({1}) == 0))'
            .format(p, solos))
        for c in "rgb":
            g.parm("brighttint" + c).setExpression('ch("../tint_%s%s")' % (p, c))
        g.setColor(hou.Color(0.85, 0.65, 0.25))
        node = blend("add", node, g, 0, "plus_" + p, i + 1, row)

    out = at(sub.createNode("bright", "layer_out"), len(passes) + 1, row)
    out.setInput(0, node)
    out.parm("scopergba").set(15)  # opacity scales rgba (premultiplied), exposure only rgb via tint
    out.parm("bright").setExpression('ch("../opacity")')
    for c in "rgb":
        out.parm("brighttint" + c).setExpression('pow(2, ch("../exposure"))')
    out.setColor(hou.Color(0.9, 0.53, 0.16))
    sub.node("outputs").setInput(0, out)
    at(sub.node("outputs"), len(passes) + 1, row + 1)
    sub.node("inputs").setPosition(hou.Vector2(-GRID_X, 0))
    return passes


# ---------------------------------------------------------------- the whole comp
LAYER_DY = 1.6  # network units between layer nodes at the top level


def read_comp(net):
    """Layers of a comp this tool built, top (foreground) first:
    [{label, path, passes, type, values}]."""
    subs = [c for c in net.children() if c.userData("mke_comp_path")]
    subs.sort(key=lambda s: -s.position()[1])
    return [{"label": s.name(), "path": s.userData("mke_comp_path"),
             "passes": [p for p in (s.userData("mke_comp_passes") or "").split(",") if p],
             "type": s.userData("mke_comp_type") or layer_type(s.name()),
             "values": knob_values(s)} for s in subs]


def default_output(paths, name):
    return os.path.dirname(sequence_path(paths[-1])[0]) + "/comp/" + name + "_comp.$F4.exr"


LAST_CHANGES = []  # what the last build() created, rebuilt or removed (for the window's status)


def build(paths, passes=None, parent=None, name=None, output=None, types=None,
          values=None, replace=False):
    """Create the comp copnet, or update it in place. paths: one EXR (any frame)
    per render layer, BOTTOM first. passes: None -> light_passes() per layer, a
    list for every layer, or {path: list}. types: {path: 'BG'|...}. values:
    {label: knob values} for new layers. replace: update an existing comp of that
    name: only layers whose passes changed are rebuilt (knobs kept), new ones are
    added, missing ones removed; the rest of the network is left alone."""
    del LAST_CHANGES[:]
    if isinstance(paths, str):
        paths = [paths]
    # layers are matched by path (userData stores it with '/'): normalise so D:\x and D:/x are one layer
    paths = [p.replace("\\", "/") for p in paths]
    if isinstance(passes, dict):
        passes = {k.replace("\\", "/"): v for k, v in passes.items()}
    types = {k.replace("\\", "/"): v for k, v in (types or {}).items()}
    labels = layer_labels(paths)
    seq = sequence_path(paths[0])[0]
    name = name or re.sub(r"[^A-Za-z0-9_]", "_", os.path.basename(seq).split(".")[0])
    parent = parent or hou.node("/img") or hou.node("/obj")
    net = parent.node("comp_" + name)
    if net is not None and not replace:
        raise hou.Error("%s already exists" % net.path())
    if net is None:
        net = parent.createNode("copnet", "comp_" + name)
    existing = {s.userData("mke_comp_path"): s for s in net.children() if s.userData("mke_comp_path")}
    old_order = [s for s in sorted(existing.values(), key=lambda s: s.position()[1])]

    n = len(paths)
    subs = []
    first = last = None
    for i, (path, label) in enumerate(zip(paths, labels)):
        kind = (types or {}).get(path) or layer_type(label)
        want = passes.get(path) if isinstance(passes, dict) else passes
        sub = existing.pop(path, None)
        if sub is None:
            sub = net.createNode("subnet", label)
            sub.setPosition(hou.Vector2(0, -(n - 1 - i) * LAYER_DY))  # foreground on top
            populate_layer(sub, path, want, (values or {}).get(label))
            LAST_CHANGES.append(label + " added")
        else:
            src = sub.node("render")
            aovs = src.outputNames() if src is not None else ()
            target = [p for p in (light_passes(aovs) if want is None else want) if p in aovs]
            current = [p for p in (sub.userData("mke_comp_passes") or "").split(",") if p]
            if src is None or set(target) != set(current):
                populate_layer(sub, path, want, knob_values(sub))
                LAST_CHANGES.append(sub.name() + " passes updated")
        if sub.userData("mke_comp_type") != kind:
            sub.setUserData("mke_comp_type", kind)
            sub.setColor(hou_color(kind))
        subs.append(sub)
        f1, f2 = sequence_path(path)[1:]
        if f1 is not None:
            first = f1 if first is None else min(first, f1)
            last = f2 if last is None else max(last, f2)
    gone = list(existing.values())
    kept = [s for s in old_order if s not in gone]
    for sub in gone:  # layers taken out of the list
        LAST_CHANGES.append(sub.name() + " removed")
        sub.destroy()
    if kept != [s for s in subs if s in kept]:  # reordered: back on the grid
        LAST_CHANGES.append("layer order")
        for i, sub in enumerate(subs):
            sub.setPosition(hou.Vector2(0, -(n - 1 - i) * LAYER_DY))

    # over stack: reuse over_<layer> nodes, rewire, drop the unused ones
    node = subs[0]
    used = set()
    for sub in subs[1:]:
        over = net.node("over_" + sub.name())
        if over is None:
            over = net.createNode("blend", "over_" + sub.name())
            over.parm("mode").set("over")
            over.setPosition(hou.Vector2(4, sub.position()[1]))
        elif "layer order" in LAST_CHANGES:
            over.setPosition(hou.Vector2(4, sub.position()[1]))
        if over.input(0) != node:
            over.setInput(0, node)
        if over.input(1) != sub:
            over.setInput(1, sub)
        used.add(over)
        node = over
    for c in net.children():
        if c.name().startswith("over_") and c not in used:
            c.destroy()

    grade_node = net.node("final_grade")
    if grade_node is None:
        grade_node = net.createNode("bright", "final_grade")
        grade_node.setPosition(hou.Vector2(8, 0))
    if grade_node.input(0) != node:
        grade_node.setInput(0, node)
    out = net.node("OUT")
    if out is None:
        out = net.createNode("null", "OUT")
        out.setInput(0, grade_node)
        out.setDisplayFlag(True)
        out.setColor(hou.Color(0.9, 0.53, 0.16))
        out.setPosition(hou.Vector2(8, -LAYER_DY))
    rop = net.node("write_comp")
    if rop is None:
        rop = net.createNode("rop_image", "write_comp")
        rop.setInput(0, out)
        rop.setPosition(hou.Vector2(8, -2 * LAYER_DY))
        rop.parm("size1").set("float16")  # EXR half float
        rop.parm("copoutput").set(output or default_output(paths, name))
    elif output and rop.parm("copoutput").unexpandedString() != output:
        rop.parm("copoutput").set(output)
    if first is not None and (rop.evalParm("trange") != 1 or (rop.evalParm("f1"), rop.evalParm("f2")) != (first, last)):
        rop.parm("trange").set(1)
        for parm, v in (("f1", first), ("f2", last), ("f3", 1)):
            rop.parm(parm).deleteAllKeyframes()
            rop.parm(parm).set(v)
    net.setUserData("mke_comp", name)
    return net


# ---------------------------------------------------------------- buttons on a layer node
def _rebuild(sub, path, passes):
    keep = knob_values(sub)
    populate_layer(sub, path, passes, keep)


def on_reload(kwargs):
    sub = kwargs["node"]
    passes = [p for p in (sub.userData("mke_comp_passes") or "").split(",") if p]
    _rebuild(sub, sub.userData("mke_comp_path"), passes)


def on_reset(kwargs):
    for p in kwargs["node"].spareParms():
        if p.name() != "source":
            p.revertToDefaults()


def on_swap(kwargs):
    sub = kwargs["node"]
    old = sub.userData("mke_comp_path")
    start = os.path.dirname(os.path.dirname(old))
    picked = hou.ui.selectFile(start_directory=start + "/", title="New version: folder or EXR of this layer",
                               chooser_mode=hou.fileChooserMode.Read)
    if not picked:
        return
    picked = parse_paths(picked)[0]
    found = [picked] if picked.lower().endswith(".exr") else find_layers(picked)
    if not found:
        hou.ui.displayMessage("No EXR in " + picked, severity=hou.severityType.Warning)
        return
    if len(found) > 1:
        sel = hou.ui.selectFromList([os.path.basename(f) for f in found], exclusive=True,
                                    title="Which sequence is this layer?")
        if not sel:
            return
        found = [found[sel[0]]]
    passes = [p for p in (sub.userData("mke_comp_passes") or "").split(",") if p]
    _rebuild(sub, found[0], passes)
    rop = sub.parent().node("write_comp")
    f1, f2 = sequence_path(found[0])[1:]
    if rop is not None and f1 is not None:
        rop.parm("f1").set(min(rop.evalParm("f1"), f1))
        rop.parm("f2").set(max(rop.evalParm("f2"), f2))


def layer_aovs(path):
    """AOV names of one EXR (reads the header through a temporary file COP)."""
    probe = hou.node("/obj").createNode("copnet")
    try:
        f = probe.createNode("file")
        f.parm("filename").set(path)
        return read_aovs(f)
    finally:
        probe.destroy()


def compFromRender():
    """MK Utils entry: the comp window."""
    global _dialog
    _dialog = CompDialog(hou.qt.mainWindow())
    _dialog.show()
    return _dialog


_dialog = None

def parse_paths(text):
    """Pasted text -> folders. One path per line (or ';'), Explorer "Copy as path"
    quotes, file:/// links and $VARS accepted; a pasted .exr gives its folder."""
    out = []
    for line in re.split(r"[\r\n;]+", text):
        p = line.strip().strip('"').strip()
        if p.lower().startswith("file:///"):
            p = p[8:]
        if not p:
            continue
        p = hou.text.expandString(p).replace("\\", "/")
        out.append(os.path.dirname(p) if os.path.isfile(p) else p)
    return out


from hutil.Qt import QtCore, QtGui, QtWidgets  # noqa: E402  (UI only below)

QSS = """
QDialog { background: #262626; color: #dcdcdc; }
QFrame#bar { background: #1e1e1e; border: 0; }
QLabel { color: #dcdcdc; }
QLabel#title { font-size: 11pt; font-weight: bold; }
QLabel#muted { color: #9a9a9a; }
QLabel#section { color: #a8a8a8; font-size: 8pt; font-weight: bold; letter-spacing: 1px; }
QLabel#mono { color: #8f8f8f; font-family: Consolas, monospace; font-size: 8pt; }
QLabel#warn { color: #f0a24a; }
QLabel#drop { color: #9a9a9a; border: 1px dashed #555; border-radius: 4px; padding: 12px; }
QLineEdit, QPlainTextEdit, QComboBox { background: #333; border: 1px solid #4a4a4a; border-radius: 3px;
    color: #e6e6e6; padding: 4px 6px; }
QPushButton { background: #333; border: 1px solid #4a4a4a; border-radius: 3px; color: #dcdcdc; padding: 5px 12px; }
QPushButton:hover { background: #3d3d3d; }
QPushButton#primary { background: #e8862a; border: 0; color: #1a1a1a; font-weight: bold; padding: 7px 22px; }
QPushButton#primary:hover { background: #f29a45; }
QPushButton#preset { border-radius: 0; padding: 5px 12px; }
QTreeWidget { background: #262626; border: 0; color: #e0e0e0; alternate-background-color: #292929; }
QTreeWidget::item { height: 36px; border-bottom: 1px solid #2f2f2f; }
QTreeWidget::item:selected { background: #36465c; color: #ffffff; }
QHeaderView::section { background: #262626; color: #9a9a9a; border: 0; border-bottom: 1px solid #333; padding: 4px; }
QCheckBox { color: #e6e6e6; spacing: 8px; }
QCheckBox::indicator { width: 13px; height: 13px; border: 1px solid #7a7a7a; border-radius: 2px; background: #333; }
QCheckBox::indicator:checked { background: #e8862a; border-color: #e8862a; }
QCheckBox::indicator:indeterminate { background: #8a5a2a; border-color: #e8862a; }
QScrollArea { border: 0; background: transparent; }
QFrame#card { background: #2f2f2f; border-radius: 4px; }
"""


class LayerTree(QtWidgets.QTreeWidget):
    """Layer table: reorders by drag inside (never nests), takes folders/EXRs
    dropped from the Explorer."""
    dropped = QtCore.Signal(list)
    reordered = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(5)
        self.setHeaderLabels(["", "Layer", "Type", "Passes", "Frames"])
        self.setRootIsDecorated(False)
        self.setIndentation(0)
        self.setUniformRowHeights(True)
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragDrop)
        self.setDefaultDropAction(QtCore.Qt.MoveAction)
        self.setDropIndicatorShown(True)
        head = self.header()
        head.setStretchLastSection(False)
        head.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        for col, w in ((0, 26), (2, 60), (3, 110), (4, 110)):
            head.setSectionResizeMode(col, QtWidgets.QHeaderView.Fixed)
            self.setColumnWidth(col, w)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.dropped.emit(parse_paths("\n".join(
                u.toLocalFile() for u in event.mimeData().urls())))
        else:
            super().dropEvent(event)
            self.reordered.emit()


def _label(text, name=None, wrap=False):
    label = QtWidgets.QLabel(text)
    label.setWordWrap(wrap)
    if name:
        label.setObjectName(name)
    return label


def _swatch(hex_color, size=12):
    pix = QtGui.QPixmap(size, size)
    pix.fill(QtGui.QColor(hex_color))
    return QtGui.QIcon(pix)


def _is_lpe(aov):
    return any(aov in (c, "combined" + c, "direct" + c, "indirect" + c) for c in COMPONENTS)


class CompDialog(QtWidgets.QDialog):
    """Render layers (top = foreground) + per-layer passes -> build()."""

    def __init__(self, parent=None):
        import mke_project
        super().__init__(parent)
        self.prefs = mke_project
        self.setWindowTitle("Copernicus Comp")
        self.setStyleSheet(QSS)
        self.setAcceptDrops(True)
        self.resize(1180, 760)
        self.aovs = {}     # exr path -> AOV names
        self.picked = {}   # exr path -> passes ticked
        self.types = {}    # exr path -> BG/CHAR/...
        self.frames = {}   # exr path -> (first, last, missing)
        self.labels = {}
        self.name_edited = self.output_edited = False
        self.loaded = None  # name of the comp loaded with Load existing comp

        main = QtWidgets.QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)
        main.addWidget(self._header())
        body = QtWidgets.QHBoxLayout()
        body.setSpacing(0)
        body.addWidget(self._layers_panel(), 11)
        line = QtWidgets.QFrame()
        line.setFixedWidth(1)
        line.setStyleSheet("background: #111;")
        body.addWidget(line)
        body.addWidget(self._inspector_panel(), 9)
        main.addLayout(body, 1)
        main.addWidget(self._footer())
        self.refresh()

    # ------------------------------------------------------------ layout
    def _header(self):
        bar = QtWidgets.QFrame()
        bar.setObjectName("bar")
        row = QtWidgets.QHBoxLayout(bar)
        row.setContentsMargins(16, 10, 16, 10)
        dot = QtWidgets.QFrame()
        dot.setFixedSize(10, 10)
        dot.setStyleSheet("background: #e8862a; border-radius: 2px;")
        row.addWidget(dot)
        row.addWidget(_label("Copernicus Comp", "title"))
        row.addWidget(_label("MK Utils", "muted"))
        row.addStretch(1)
        row.addWidget(_label("Name", "muted"))
        self.name = QtWidgets.QLineEdit()
        self.name.setFixedWidth(240)
        self.name.textEdited.connect(self._name_edited)
        row.addWidget(self.name)
        load = QtWidgets.QPushButton("Load existing comp...")
        load.clicked.connect(self.load_existing)
        row.addWidget(load)
        return bar

    def _layers_panel(self):
        panel = QtWidgets.QWidget()
        col = QtWidgets.QVBoxLayout(panel)
        col.setContentsMargins(16, 12, 16, 12)
        top = QtWidgets.QHBoxLayout()
        top.addWidget(_label("RENDER LAYERS", "section"))
        self.count = _label("", "muted")
        top.addWidget(self.count)
        top.addStretch(1)
        paste = QtWidgets.QPushButton("Paste paths")
        paste.setCheckable(True)
        browse = QtWidgets.QPushButton("Browse...")
        remove = QtWidgets.QPushButton("Remove")
        for b in (paste, browse, remove):
            top.addWidget(b)
        col.addLayout(top)

        self.paste_row = QtWidgets.QWidget()
        prow = QtWidgets.QHBoxLayout(self.paste_row)
        prow.setContentsMargins(0, 0, 0, 0)
        self.paste = QtWidgets.QPlainTextEdit()
        self.paste.setPlaceholderText('One folder per line. "Copy as path" quotes, file:/// links, '
                                      "$JOB/... and .exr files are fine.")
        self.paste.setFixedHeight(58)
        add = QtWidgets.QPushButton("Add")
        prow.addWidget(self.paste, 1)
        prow.addWidget(add)
        self.paste_row.setVisible(False)
        col.addWidget(self.paste_row)

        self.tree = LayerTree()
        col.addWidget(self.tree, 1)
        col.addWidget(_label("Drop render layer folders here (Explorer), or Ctrl+V paths. "
                             "Drag rows to reorder.", "drop", wrap=True))

        paste.toggled.connect(self.paste_row.setVisible)
        add.clicked.connect(self.add_pasted)
        browse.clicked.connect(self.browse)
        remove.clicked.connect(self.remove_selected)
        self.tree.dropped.connect(self.add_folders)
        self.tree.reordered.connect(self.refresh)
        self.tree.itemSelectionChanged.connect(self.show_inspector)
        return panel

    def _inspector_panel(self):
        panel = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout(panel)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(8)
        self.empty = _label("Select one or more layers to choose their passes.", "muted", wrap=True)
        outer.addWidget(self.empty)
        self.insp_box = QtWidgets.QWidget()  # hidden while no layer is selected
        col = QtWidgets.QVBoxLayout(self.insp_box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(8)
        outer.addWidget(self.insp_box, 1)
        self.empty_stretch = QtWidgets.QWidget()
        outer.addWidget(self.empty_stretch, 1)
        self.insp_title = _label("LAYER", "section")
        self.insp_path = _label("", "mono", wrap=True)
        col.addWidget(self.insp_title)
        col.addWidget(self.insp_path)

        trow = QtWidgets.QHBoxLayout()
        trow.addWidget(_label("Type", "muted"))
        self.type_box = QtWidgets.QComboBox()
        for t in TYPES:
            self.type_box.addItem(_swatch(TYPE_COLORS[t]), t)
        self.type_box.activated.connect(self.set_type)
        trow.addWidget(self.type_box)
        trow.addStretch(1)
        col.addLayout(trow)

        prow = QtWidgets.QHBoxLayout()
        prow.setSpacing(0)
        self.presets = []
        for name, key in (("Light passes", "lpe"), ("Light groups", "groups"), ("Beauty only", "none")):
            b = QtWidgets.QPushButton(name)
            b.setObjectName("preset")
            b.clicked.connect(lambda _=False, k=key: self.apply_preset(k))
            prow.addWidget(b)
            self.presets.append(b)
        prow.addStretch(1)
        col.addLayout(prow)

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.viewport().setStyleSheet("background: #262626;")
        col.addWidget(self.scroll, 1)

        card = QtWidgets.QFrame()
        card.setObjectName("card")
        ccol = QtWidgets.QVBoxLayout(card)
        ccol.addWidget(_label("OUTPUT", "section"))
        self.output = QtWidgets.QLineEdit()
        self.output.textEdited.connect(self._output_edited)
        ccol.addWidget(self.output)
        self.frames_label = _label("", "muted", wrap=True)
        ccol.addWidget(self.frames_label)
        outer.addWidget(card)
        return panel

    def _footer(self):
        bar = QtWidgets.QFrame()
        bar.setObjectName("bar")
        row = QtWidgets.QHBoxLayout(bar)
        row.setContentsMargins(16, 10, 16, 10)
        self.warnings = _label("", "warn", wrap=True)
        row.addWidget(self.warnings, 1)
        cancel = QtWidgets.QPushButton("Cancel")
        cancel.clicked.connect(self.close)
        build_btn = QtWidgets.QPushButton("Build comp")
        build_btn.setObjectName("primary")
        build_btn.setDefault(True)
        build_btn.clicked.connect(self.build)
        row.addWidget(cancel)
        row.addWidget(build_btn)
        return bar

    # ------------------------------------------------------------ adding layers
    def browse(self):
        start = self.prefs.get_pref("comp_last_dir") or hou.text.expandString("$JOB")
        dlg = QtWidgets.QFileDialog(self, "Render layer folders (Ctrl/Shift for several)", start)
        dlg.setFileMode(QtWidgets.QFileDialog.Directory)
        dlg.setOption(QtWidgets.QFileDialog.DontUseNativeDialog, True)  # the native one picks a single folder
        dlg.setOption(QtWidgets.QFileDialog.ShowDirsOnly, True)
        for view in dlg.findChildren(QtWidgets.QAbstractItemView):
            view.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        if dlg.exec_():
            folders = dlg.selectedFiles()
            if folders:
                self.prefs.set_pref("comp_last_dir", os.path.dirname(folders[0].rstrip("/")))
            self.add_folders(folders)

    def add_pasted(self):
        self.add_folders(parse_paths(self.paste.toPlainText()))
        self.paste.clear()

    def keyPressEvent(self, event):
        # Ctrl+V anywhere but a text field adds the clipboard paths directly
        focus = QtWidgets.QApplication.focusWidget()
        if event.matches(QtGui.QKeySequence.Paste) and not isinstance(
                focus, (QtWidgets.QLineEdit, QtWidgets.QPlainTextEdit)):
            self.add_folders(parse_paths(QtWidgets.QApplication.clipboard().text()))
            return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.add_folders(parse_paths("\n".join(
            u.toLocalFile() for u in event.mimeData().urls())))

    def add_folders(self, folders, layers=None):
        """folders -> new layers on top. layers: [(path, passes, type)] to add as is."""
        known = set(self.paths())
        empty, added = [], []
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            todo = list(layers or [])
            for folder in folders:
                found = find_layers(folder)
                if not found:
                    empty.append(os.path.basename(folder.rstrip("/\\")) or folder)
                todo += [(p, None, None) for p in found]
            for path, passes, kind in reversed(todo):
                if path in known:
                    continue
                known.add(path)
                self.aovs[path] = layer_aovs(path)
                self.picked[path] = set(light_passes(self.aovs[path]) if passes is None else passes)
                self.types[path] = kind
                self.frames[path] = frame_info(path)
                item = QtWidgets.QTreeWidgetItem()
                item.setData(0, QtCore.Qt.UserRole, path)
                item.setFlags(QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled |
                              QtCore.Qt.ItemIsDragEnabled)  # no drop: rows never nest
                self.tree.insertTopLevelItem(0, item)  # new layers land on top
                added.append(item)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self.empty_folders = empty
        self.refresh()
        if added and not self.tree.selectedItems():
            added[-1].setSelected(True)

    def remove_selected(self):
        for item in self.tree.selectedItems():
            self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(item))
        self.refresh()

    def paths(self):
        """Top (foreground) first."""
        return [self.tree.topLevelItem(i).data(0, QtCore.Qt.UserRole)
                for i in range(self.tree.topLevelItemCount())]

    # ------------------------------------------------------------ table
    def refresh(self):
        paths = self.paths()
        self.labels = dict(zip(paths, layer_labels(paths))) if paths else {}
        for p in paths:
            if self.types.get(p) is None:
                self.types[p] = layer_type(self.labels[p])
        for i, p in enumerate(paths):
            item = self.tree.topLevelItem(i)
            kind = self.types[p]
            item.setIcon(0, _swatch(TYPE_COLORS[kind]))
            item.setText(1, self.labels[p])
            item.setToolTip(1, p)
            item.setText(2, kind)
            item.setForeground(2, QtGui.QBrush(QtGui.QColor(TYPE_COLORS[kind])))
            n = len(self.picked[p])
            item.setText(3, "beauty only" if not n else "%d of %d AOVs" % (n, len(self.aovs[p])))
            f1, f2, missing = self.frames[p]
            item.setText(4, "%04d-%04d" % (f1, f2) if f1 is not None else "single")
            item.setForeground(4, QtGui.QBrush(QtGui.QColor("#f0a24a" if missing else "#c8c8c8")))
        self.count.setText("%d layer%s · top = foreground" % (len(paths), "" if len(paths) == 1 else "s")
                           if paths else "")
        if paths and not self.name_edited:
            self.name.setText(self.default_name(paths))
        self.update_output()
        self.update_warnings()
        self.show_inspector()

    def default_name(self, paths):
        bases = [re.sub(r"[._]?\$F\d.*$", "", os.path.basename(sequence_path(p)[0])) for p in paths]
        common = os.path.commonprefix(bases) if len(bases) > 1 else bases[0]
        common = re.sub(r"[._](usd)?render.*$", "", common).strip("._")
        return re.sub(r"[^A-Za-z0-9_]", "_", common) or "comp"

    def _name_edited(self, _text):
        self.name_edited = True
        self.update_output()

    def _output_edited(self, _text):
        self.output_edited = True

    def update_output(self):
        paths = self.paths()
        ranges = [self.frames[p][:2] for p in paths if self.frames[p][0] is not None]
        if ranges:
            self.frames_label.setText("Frames %04d-%04d (union of the layers) · EXR half float" % (
                min(r[0] for r in ranges), max(r[1] for r in ranges)))
        if self.output_edited or not paths:
            return
        name = self.name.text().strip() or "comp"
        job = hou.text.expandString("$JOB")
        if job and os.path.isdir(os.path.join(job, "OUT")):
            out = "%s/OUT/comp/%s/%s_comp.$F4.exr" % (job.replace("\\", "/"), name, name)
        else:
            out = default_output(list(reversed(paths)), name)
        self.output.setText(out)

    def update_warnings(self):
        paths = self.paths()
        lines = []
        ranges = [self.frames[p][:2] for p in paths if self.frames[p][0] is not None]
        if ranges:
            usual = max(set(ranges), key=ranges.count)
            odd = ["%s %04d-%04d" % (self.labels[p], *self.frames[p][:2]) for p in paths
                   if self.frames[p][0] is not None and self.frames[p][:2] != usual]
            if odd:
                lines.append("Frame range differs from %04d-%04d: %s" % (usual + (", ".join(odd),)))
        gaps = ["%s (%d)" % (self.labels[p], self.frames[p][2]) for p in paths if self.frames[p][2]]
        if gaps:
            lines.append("Missing frames: " + ", ".join(gaps))
        no_beauty = [self.labels[p] for p in paths if "C" not in self.aovs[p]]
        if no_beauty:
            lines.append("No beauty (C) AOV: " + ", ".join(no_beauty))
        if getattr(self, "empty_folders", None):
            lines.append("No EXR in: " + ", ".join(self.empty_folders))
        self.warnings.setText("\n".join(lines))

    # ------------------------------------------------------------ inspector
    def targets(self):
        return [i.data(0, QtCore.Qt.UserRole) for i in self.tree.selectedItems()]

    def show_inspector(self):
        targets = self.targets()
        self.insp_box.setVisible(bool(targets))
        self.empty.setVisible(not targets)
        self.empty_stretch.setVisible(not targets)
        if not targets:
            return
        if len(targets) == 1:
            self.insp_title.setText("LAYER · " + self.labels[targets[0]])
            self.insp_path.setText(sequence_path(targets[0])[0])
        else:
            self.insp_title.setText("%d LAYERS" % len(targets))
            self.insp_path.setText(", ".join(self.labels[p] for p in targets))
        kinds = {self.types[p] for p in targets}
        self.type_box.setCurrentIndex(TYPES.index(kinds.pop()) if len(kinds) == 1 else -1)

        names = sorted({a for p in targets for a in self.aovs[p] if a != "C"})
        lpe = [a for a in names if _is_lpe(a)]
        groups = [a for a in names if a.startswith("C_")]
        other = [a for a in names if a not in lpe and a not in groups]
        crypto = [a for a in other if a.startswith("Crypto")]
        utility = [a for a in other if not a.startswith("Crypto")]
        any_lpe_on = any(self.picked[p] & set(lpe) for p in targets)

        box = QtWidgets.QWidget()
        box.setStyleSheet("background: #262626;")
        lay = QtWidgets.QVBoxLayout(box)
        lay.setContentsMargins(0, 4, 0, 4)
        lay.setSpacing(2)
        for title, aovs in (("LIGHT PASSES (LPE) · ADDED BACK", lpe), ("LIGHT GROUPS", groups)):
            if not aovs:
                continue
            lay.addWidget(_label(title, "section"))
            for a in aovs:
                lay.addLayout(self._pass_row(a, targets, any_lpe_on))
            lay.addSpacing(10)
        if utility or crypto:
            lay.addWidget(_label("UTILITY · KEPT AS OUTPUTS, NEVER SUMMED", "section"))
            text = " · ".join(utility + (["Cryptomatte (%d)" % len(crypto)] if crypto else []))
            lay.addWidget(_label(text, "muted", wrap=True))
        lay.addStretch(1)
        self.scroll.setWidget(box)

    def _pass_row(self, aov, targets, any_lpe_on):
        having = [p for p in targets if aov in self.aovs[p]]
        on = sum(aov in self.picked[p] for p in having)
        row = QtWidgets.QHBoxLayout()
        text = aov if len(having) == len(targets) else "%s   (%d/%d)" % (aov, len(having), len(targets))
        cb = QtWidgets.QCheckBox(text)
        cb.setTristate(True)
        cb.setCheckState(QtCore.Qt.Unchecked if not on else
                         QtCore.Qt.Checked if on == len(having) else QtCore.Qt.PartiallyChecked)
        cb.clicked.connect(lambda _=False, a=aov, all_on=(on == len(having)): self.toggle(a, not all_on))
        row.addWidget(cb)
        row.addWidget(_label(self._overlap(aov, having, any_lpe_on), "warn"))
        row.addStretch(1)
        return row

    def _overlap(self, aov, having, any_lpe_on):
        """Short note when a ticked pass is already inside another ticked one."""
        m = re.match(r"(direct|indirect)(\w+)$", aov)
        if m and any("combined" + m.group(2) in self.picked[p] and aov in self.picked[p] for p in having):
            return "inside combined" + m.group(2)
        if aov.startswith("C_") and any_lpe_on and any(aov in self.picked[p] for p in having):
            return "overlaps the light passes"
        return ""

    def toggle(self, aov, on):
        for p in self.targets():
            if aov in self.aovs[p]:
                (self.picked[p].add if on else self.picked[p].discard)(aov)
        self.refresh()

    def apply_preset(self, key):
        for p in self.targets():
            aovs = self.aovs[p]
            if key == "lpe":
                self.picked[p] = set(light_passes([a for a in aovs if not a.startswith("C_")]))
            elif key == "groups":
                self.picked[p] = {a for a in aovs if a.startswith("C_")}
            else:
                self.picked[p] = set()
        self.refresh()

    def set_type(self, index):
        for p in self.targets():
            self.types[p] = TYPES[index]
        self.refresh()

    # ------------------------------------------------------------ existing comps
    def load_existing(self):
        comps = [n for n in (hou.node("/img") or hou.node("/obj")).children() if n.userData("mke_comp")]
        if not comps:
            hou.ui.displayMessage("No comp built by this tool in /img yet.")
            return
        if len(comps) > 1:
            sel = hou.ui.selectFromList([c.name() for c in comps], exclusive=True,
                                        title="Load existing comp")
            if not sel:
                return
            comps = [comps[sel[0]]]
        net = comps[0]
        self.tree.clear()
        layers = read_comp(net)  # top first
        self.add_folders([], [(l["path"], l["passes"], l["type"]) for l in layers])
        self.name.setText(net.userData("mke_comp"))
        self.name_edited = True
        rop = net.node("write_comp")
        if rop is not None:
            self.output.setText(rop.parm("copoutput").unexpandedString())
            self.output_edited = True
        self.loaded = net.userData("mke_comp")
        self.refresh()

    # ------------------------------------------------------------ build
    def build(self):
        paths = self.paths()
        if not paths:
            self.warnings.setText("Add at least one render layer.")
            return
        name = re.sub(r"[^A-Za-z0-9_]", "_", self.name.text().strip()) or "comp"
        parent = hou.node("/img") or hou.node("/obj")
        replace = False
        if parent.node("comp_" + name) is not None:
            if self.loaded != name and QtWidgets.QMessageBox.question(
                    self, "Copernicus Comp",
                    "comp_%s already exists.\nUpdate it? Only the layers you changed are rebuilt "
                    "(their knobs kept); the rest of the network is left as is." % name
            ) != QtWidgets.QMessageBox.Yes:
                return
            replace = True
        try:
            # build() stacks bottom first
            net = build(list(reversed(paths)), {p: sorted(self.picked[p]) for p in paths},
                        parent=parent, name=name, output=self.output.text().strip() or None,
                        types=dict(self.types), replace=replace)
        except hou.Error as e:
            self.warnings.setText(e.instanceMessage())
            return
        net.setCurrent(True, clear_all_selected=True)
        if hou.isUIAvailable():
            pane = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
            if pane and not replace:
                pane.setPwd(net)
                pane.frameAll()
            hou.ui.setStatusMessage("%s: %s" % (net.path(), ", ".join(LAST_CHANGES) or "nothing changed"))
        self.close()
