"""Scene checker run before sending to Deadline (and from MK Utils > Vérifier la scène).

Each problem is (level, node path or '', message) with level 'error' (the night job would fail or lose data)
or 'warning' (worth a look). Checks are cheap: no cooking, only parameters and the file system.
"""
import os
import re
import shutil

import hou

import mke_project

FRAME_TOKENS = re.compile(r"\$F\d*|\$T|\$SF|<UDIM>|<UVTILE>|%\(UDIM\)d|\$\{F\d*\}|\$FF|\$N|#")
OUTPUT_PARMS = {"sopoutput", "lopoutput", "vm_picture", "picture", "outputimage", "copoutput", "dopoutput"}


def _norm(path):
    return os.path.normcase(os.path.normpath(path))


def _upstream(nodes):
    scope = set()
    for node in nodes:
        scope.add(node)
        scope.update(node.inputAncestors())
    return scope


def check(nodes=None):
    """Problems for `nodes` and everything upstream of them (or the whole scene). Sorted errors first."""
    problems = []
    scope = _upstream(nodes) if nodes else None
    in_scope = (lambda n: n in scope) if scope is not None else (lambda n: True)
    info = None if hou.hipFile.isNewFile() else mke_project.find_project(os.path.dirname(hou.hipFile.path()))
    hfs = _norm(hou.getenv("HFS") or "")

    # nodes already in error
    for node in (scope or hou.node("/").allSubChildren(recurse_in_locked_nodes=False)):
        try:
            errors = node.errors()
        except hou.OperationFailed:
            continue
        own = [e for e in errors if not e.startswith("Invalid source")]  # skip errors only inherited from inputs
        if own:
            problems.append(("error", node.path(), f"Node en erreur : {own[0][:160]}"))

    # files read by the scene: missing, or outside the project
    for parm, path in hou.fileReferences():
        node = parm.node() if parm else None
        if node is None or not in_scope(node) or parm.name() in OUTPUT_PARMS or node.isBypassed():
            continue
        template = parm.parmTemplate()
        if (getattr(template, "stringType", lambda: None)() != hou.stringParmType.FileReference
                or node.type().nameComponents()[2] == "filecache"  # its own paths are outputs, checked below
                or node.type().category() == hou.ropNodeTypeCategory()):
            continue
        try:
            if node.isDisabled() if hasattr(node, "isDisabled") else False:
                continue
        except hou.OperationFailed:
            pass
        expanded = hou.text.expandString(path)
        if not expanded or expanded.startswith(("op:", "opdef:", "oplib:", "temp:")) or _norm(expanded).startswith(hfs):
            continue
        if not FRAME_TOKENS.search(path) and not os.path.exists(expanded):
            problems.append(("warning", node.path(), f"Fichier introuvable : {expanded}"))
        elif info and not _norm(expanded).startswith(_norm(info["root"])):
            problems.append(("warning", node.path(), f"Fichier hors du projet (pense à le copier dans IN) : {expanded}"))

    # what the nodes will write
    for node in (nodes or []):
        problems += _check_output(node, info)
    return sorted(problems, key=lambda p: p[0] != "error")


def _check_output(node, info):
    problems = []
    is_cache = node.type().nameComponents()[2] == "filecache"
    if is_cache and node.parm("enableversion") is not None and not node.evalParm("enableversion"):
        problems.append(("warning", node.path(), "Versions désactivées : le cache écrasera le précédent."))
    folder = ""
    if node.parm("cachedir") is not None:
        folder = node.parm("cachedir").evalAsString()
    elif node.parm("sopoutput") is not None:
        folder = os.path.dirname(node.parm("sopoutput").evalAsString())
    if folder and os.path.isdir(folder):
        existing = [f for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f))]
        if existing:
            problems.append(("warning", node.path(), f"{len(existing)} fichier(s) existent déjà dans {folder} : ils seront écrasés "
                                                     "(monte la version du cache pour les garder)."))
    if folder:
        needed = _previous_version_size(folder)
        drive = folder
        while drive and not os.path.exists(drive):
            drive = os.path.dirname(drive)
        if needed and drive:
            free = shutil.disk_usage(drive).free
            if free < needed * 1.2:
                problems.append(("error", node.path(), f"Espace disque insuffisant : ~{needed / 1e9:.1f} Go attendus "
                                                       f"(d'après la version précédente), {free / 1e9:.1f} Go libres."))
    if info and node.parm("f1") is not None and node.parm("trange") is not None and node.evalParm("trange") != 0:
        shot = None if hou.hipFile.isNewFile() else mke_project.shot_for_path(info, hou.hipFile.path())
        if shot:
            start, end = mke_project.shot_range(info, shot)
            f1, f2 = int(node.evalParm("f1")), int(node.evalParm("f2"))
            if (f1, f2) != (start, end):
                problems.append(("warning", node.path(), f"Frames {f1}-{f2} alors que le plan {shot} fait {start}-{end}."))
    return problems


def _previous_version_size(folder):
    """Size of the newest sibling vN folder (same cache, previous version), 0 if none."""
    parent, name = os.path.split(folder.rstrip("/\\"))
    if not re.match(r"^v\d+$", name) or not os.path.isdir(parent):
        return 0
    versions = sorted((int(d[1:]), d) for d in os.listdir(parent) if re.match(r"^v\d+$", d) and d != name)
    if not versions:
        return 0
    total = 0
    for root, _, files in os.walk(os.path.join(parent, versions[-1][1])):
        total += sum(os.path.getsize(os.path.join(root, f)) for f in files)
    return total


# ---------------------------------------------------------------- UI

def report(problems, title="Vérification de la scène", allow_continue=True):
    """Show the problems. Returns True when the user chooses to go on (always True when nothing was found)."""
    if not problems:
        return True
    errors = sum(1 for p in problems if p[0] == "error")
    lines = [f"{'⛔' if level == 'error' else '⚠'}  {path}\n      {message}" if path else f"⚠  {message}"
             for level, path, message in problems[:25]]
    if len(problems) > 25:
        lines.append(f"... et {len(problems) - 25} autres")
    head = f"{errors} erreur(s), {len(problems) - errors} avertissement(s) :\n\n"
    buttons = ("Envoyer quand même", "Annuler") if allow_continue else ("OK",)
    choice = hou.ui.displayMessage(head + "\n".join(lines), buttons=buttons, default_choice=len(buttons) - 1,
                                   close_choice=len(buttons) - 1, title=title,
                                   severity=hou.severityType.Error if errors else hou.severityType.Warning)
    return allow_continue and choice == 0


def check_selection():
    """MK Utils > Vérifier la scène: the selected nodes (and upstream), or the whole scene."""
    nodes = list(hou.selectedNodes())
    problems = check(nodes or None)
    if not problems:
        hou.ui.displayMessage("Rien à signaler.", title="Vérification de la scène")
    else:
        report(problems, allow_continue=False)
