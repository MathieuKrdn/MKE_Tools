"""Outdated-cache detection: when a cache is written, store a fingerprint of everything upstream of it.

If a node feeding the cache changes afterwards (a parameter, an expression, a new node...), the fingerprint no longer
matches and the cache is reported as outdated. Fingerprints live in the project (PIPELINE/cache_state.json), or in the
Houdini prefs for scenes outside a project, keyed by the cache's output folder.
"""
import datetime
import hashlib
import json
import os

import hou

import mke_project

STATE_FILE = "PIPELINE/cache_state.json"
# parameters that say where/how the cache is stored or how to notify, not what is cached
IGNORED = {"execute", "executebackground", "reload", "loadfromdisk", "version", "enableversion", "basedir", "basename",
           "file", "cachedir", "sopoutput", "lopoutput", "cachename", "versionstr", "filemethod", "filetype",
           "openfiledir", "openbasedir", "dirtyall", "cookoutputnode", "hardenbasename", "targettopnetwork",
           "discord_notify", "discord_message", "discord_test", "tprerender", "prerender", "lprerender",
           "tpostrender", "postrender", "lpostrender", "tpreframe", "preframe", "lpreframe", "tpostframe",
           "postframe", "lpostframe", "tpostwrite", "postwrite", "lpostwrite", "loadfromdiskonsave", "missingfile"}


def output_dir(node):
    for name in ("cachedir", "sopoutput", "lopoutput"):
        parm = node.parm(name)
        if parm is not None:
            start = node.evalParm("f1") if node.parm("f1") is not None else hou.frame()
            value = parm.evalAtFrame(start)
            return os.path.normcase(os.path.normpath(value if name == "cachedir" else os.path.dirname(value)))
    return ""


def _parm_value(parm):
    try:
        if parm.keyframes():
            return "expr:" + "|".join(k.expression() if k.isExpressionSet() else repr(k.value()) for k in parm.keyframes())
        if parm.parmTemplate().type() == hou.parmTemplateType.String:
            return parm.unexpandedString()
        return repr(parm.eval())
    except (hou.OperationFailed, AttributeError):
        return repr(parm.eval())


def fingerprint(node):
    """Hash of the node and everything upstream of it. An upstream cache that reads from disk counts by its files."""
    digest = hashlib.sha1()
    for current in [node] + sorted(node.inputAncestors(), key=lambda n: n.path()):
        digest.update(f"{current.path()}|{current.type().name()}|{current.isBypassed()}".encode())
        reads_disk = current is not node and current.parm("loadfromdisk") is not None and current.evalParm("loadfromdisk")
        if reads_disk:
            folder = output_dir(current)
            stamp = max((os.path.getmtime(os.path.join(folder, f)) for f in os.listdir(folder)), default=0) \
                if os.path.isdir(folder) else 0
            digest.update(f"disk:{folder}:{stamp}".encode())
            continue
        for parm in current.parms():
            if parm.name() not in IGNORED:
                digest.update(f"{parm.name()}={_parm_value(parm)};".encode("utf-8", "replace"))
    return digest.hexdigest()


def _state_path():
    info = None if hou.hipFile.isNewFile() else mke_project.find_project(os.path.dirname(hou.hipFile.path()))
    if info:
        return os.path.join(info["root"], STATE_FILE)
    return os.path.join(hou.getenv("HOUDINI_USER_PREF_DIR") or os.path.expanduser("~"), "mke_cache_state.json")


def _read():
    try:
        with open(_state_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def record(node):
    """Call right after a cache was written (post-render hook, re-cache tools, Deadline cook script)."""
    folder = output_dir(node)
    if not folder:
        return None
    state = _read()
    state[folder] = {"hash": fingerprint(node), "node": node.path(), "hip": hou.hipFile.path(),
                     "date": datetime.datetime.now().isoformat(timespec="seconds")}
    path = _state_path()
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1)
    os.replace(path + ".tmp", path)
    return state[folder]


def is_outdated(node, state=None):
    """True / False, or None when the cache was never fingerprinted (written before this tool existed)."""
    state = state if state is not None else _read()
    entry = state.get(output_dir(node))
    if not entry:
        return None
    return entry["hash"] != fingerprint(node)


def load_state():
    return _read()
