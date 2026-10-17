"""Freelance day-to-day: time spent per project/shot, notes and statuses per shot, cache disk usage.

Everything is stored in the project's PIPELINE folder (time_log.json, notes.json) so it travels with the project.
No UI here; the Projects dashboard shows it.
"""
import csv
import datetime
import json
import os
import re
import sys
import time

import hou

import mke_project

TIME_FILE = "PIPELINE/time_log.json"
NOTES_FILE = "PIPELINE/notes.json"
PROJECT_KEY = "projet"
TICK_SECONDS = 60
IDLE_SECONDS = 5 * 60


# ---------------------------------------------------------------- shared helpers

def _read(info, rel):
    try:
        with open(os.path.join(info["root"], rel), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _write(info, rel, data):
    path = os.path.join(info["root"], rel)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)  # never leave a half-written file if Houdini crashes mid-save


def entity_key(kind="project", **names):
    """'projet', 'SEQ010/SH0010' or 'asset:Rocher': the same keys for time and notes."""
    if kind == "shot":
        return f"{names['seq']}/{names['shot']}"
    if kind == "asset":
        return f"asset:{names['asset']}"
    return PROJECT_KEY


def key_label(key):
    return "Scènes du projet" if key == PROJECT_KEY else key.replace("asset:", "Asset ")


def key_for_scene(info, hip):
    folder = os.path.dirname(hip).replace("\\", "/")
    if os.path.basename(folder) == mke_project.AUTOSAVE_DIR:
        folder = os.path.dirname(folder)
    rel = os.path.relpath(folder, os.path.join(info["root"], mke_project.scenes_dir(info))).replace("\\", "/")
    if rel in info["shots"]:
        return rel
    if rel.startswith("ASSETS/") and rel[7:] in info["assets"]:
        return f"asset:{rel[7:]}"
    return PROJECT_KEY


# ---------------------------------------------------------------- 1. time tracking

_last_activity = time.time()
_timer = None
_filter = None


def add_time(info, key, seconds, day=None):
    day = (day or datetime.date.today()).isoformat()
    log = _read(info, TIME_FILE)
    log.setdefault(day, {})
    log[day][key] = log[day].get(key, 0) + seconds
    _write(info, TIME_FILE, log)


def tick(now=None):
    """Once a minute: if the artist touched Houdini in the last 5 minutes, credit the minute to the open scene's shot."""
    now = now or time.time()
    if now - _last_activity > IDLE_SECONDS or hou.hipFile.isNewFile():
        return None
    info = mke_project.find_project(os.path.dirname(hou.hipFile.path()))
    if not info:
        return None
    key = key_for_scene(info, hou.hipFile.path())
    add_time(info, key, TICK_SECONDS)
    return key


def mark_activity():
    global _last_activity
    _last_activity = time.time()


def start_tracking():
    """Started once from mke_project.startup(): an app-wide event filter for activity, a 1 minute timer."""
    global _timer, _filter
    if _timer is not None or not hou.isUIAvailable():
        return
    from hutil.Qt import QtCore, QtWidgets

    active = {QtCore.QEvent.MouseButtonPress, QtCore.QEvent.KeyPress, QtCore.QEvent.Wheel, QtCore.QEvent.MouseMove}

    class ActivityFilter(QtCore.QObject):
        def eventFilter(self, obj, event):
            if event.type() in active:
                mark_activity()
            return False

    _filter = ActivityFilter()
    QtWidgets.QApplication.instance().installEventFilter(_filter)
    _timer = QtCore.QTimer()
    _timer.timeout.connect(lambda: _safe(tick))
    _timer.start(TICK_SECONDS * 1000)


def _safe(fn):
    try:
        fn()
    except Exception as error:  # tracking must never bother the artist
        print(f"[MKE temps] {error}")


def week_start(day):
    return day - datetime.timedelta(days=day.weekday())


def time_summary(info, today=None):
    """{'today', 'week', 'total'} in seconds, 'days': [(date, seconds, {key: seconds})] newest first, 'keys': totals."""
    today = today or datetime.date.today()
    log = _read(info, TIME_FILE)
    days, keys = [], {}
    for day in sorted(log, reverse=True):
        per_key = log[day]
        days.append((datetime.date.fromisoformat(day), sum(per_key.values()), per_key))
        for key, seconds in per_key.items():
            keys[key] = keys.get(key, 0) + seconds
    monday = week_start(today)
    return {
        "today": sum(s for d, s, _ in days if d == today),
        "week": sum(s for d, s, _ in days if d >= monday),
        "total": sum(s for _, s, _ in days),
        "days": days, "keys": keys,
    }


def hours(seconds):
    h, m = divmod(int(seconds) // 60, 60)
    return f"{h} h {m:02d}" if h else f"{m} min"


def export_csv(info, path):
    """One row per day and shot, hours as decimals: ready for an invoice spreadsheet."""
    summary = time_summary(info)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["Date", "Projet", "Plan / asset", "Heures"])
        for day, _, per_key in sorted(summary["days"]):
            for key, seconds in sorted(per_key.items()):
                writer.writerow([day.isoformat(), info["name"], key_label(key), f"{seconds / 3600:.2f}".replace(".", ",")])
        writer.writerow(["Total", info["name"], "", f"{summary['total'] / 3600:.2f}".replace(".", ",")])
    return path


# ---------------------------------------------------------------- 2. notes and statuses

STATUSES = [  # key, label, color
    ("todo", "À faire", "#8a8a8a"),
    ("wip", "WIP", "#4f86c6"),
    ("review", "En review", "#d1a33a"),
    ("retours", "Retours client", "#d0603f"),
    ("ok", "Validé", "#4caf61"),
]
STATUS = {key: (label, color) for key, label, color in STATUSES}


def entity_notes(info, key):
    data = _read(info, NOTES_FILE).get(key, {})
    return {"status": data.get("status", "todo"), "notes": data.get("notes", [])}


def all_statuses(info):
    return {key: value.get("status", "todo") for key, value in _read(info, NOTES_FILE).items()}


def _update(info, key, change):
    data = _read(info, NOTES_FILE)
    entry = data.setdefault(key, {"status": "todo", "notes": []})
    change(entry)
    _write(info, NOTES_FILE, data)
    return entry


def set_status(info, key, status):
    assert status in STATUS, status
    return _update(info, key, lambda e: e.__setitem__("status", status))


def add_note(info, key, text, client=False):
    note = {"id": f"{time.time():.6f}", "text": text.strip(), "client": client, "done": False,
            "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "author": mke_project.user_trigram()}
    _update(info, key, lambda e: e["notes"].append(note))
    return note


def set_note_done(info, key, note_id, done):
    def change(entry):
        for note in entry["notes"]:
            if note["id"] == note_id:
                note["done"] = done
    return _update(info, key, change)


def delete_note(info, key, note_id):
    return _update(info, key, lambda e: e.__setitem__("notes", [n for n in e["notes"] if n["id"] != note_id]))


def open_count(info, key):
    return sum(not n["done"] for n in entity_notes(info, key)["notes"])


# ---------------------------------------------------------------- 3. cache disk usage

VERSION_DIR_RE = re.compile(r"^v\d+$")
SKIP_DIRS = {"backup", mke_project.AUTOSAVE_DIR, mke_project.THUMBS_DIR, "PIPELINE"}


def folder_size(path):
    total, newest = 0, 0
    for folder, _, files in os.walk(path):
        for name in files:
            try:
                stat = os.stat(os.path.join(folder, name))
            except OSError:
                continue
            total += stat.st_size
            newest = max(newest, stat.st_mtime)
    return total, newest


def scan_caches(info, progress=None):
    """Every '<cache>/vN' folder in the project (File Cache layout), with size and last write.
    Returns {cache_rel_path: [version dicts newest first]}. progress(path) is called per version found."""
    root = info["root"]
    caches = {}
    for folder, dirs, _ in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        versions = [d for d in dirs if VERSION_DIR_RE.match(d)]
        for version in versions:
            path = os.path.join(folder, version)
            if progress:
                progress(path)
            size, mtime = folder_size(path)
            if size:
                caches.setdefault(os.path.relpath(folder, root).replace("\\", "/"), []).append({
                    "version": version, "number": int(version[1:]), "path": path.replace("\\", "/"),
                    "size": size, "mtime": mtime})
        dirs[:] = [d for d in dirs if d not in versions]
    for versions in caches.values():
        versions.sort(key=lambda v: v["number"], reverse=True)
    return caches


OUTPUT_PARMS = ("cachedir", "sopoutput", "lopoutput", "file", "outputfile", "picture", "vm_picture", "saveDir", "filename")


def _norm(path):
    return os.path.normcase(os.path.normpath(path)).replace("\\", "/") if path else ""


def writer_nodes(folders):
    """{folder: [nodes]} for the nodes of the OPEN scene whose output path lives in each cache folder
    (File Cache cachedir, ROP outputs...). Only the open scene can be searched."""
    wanted = {f: _norm(f) + "/" for f in folders}
    found = {f: [] for f in folders}
    for node in hou.node("/").allSubChildren(recurse_in_locked_nodes=False):
        paths = set()
        for name in OUTPUT_PARMS:
            parm = node.parm(name)
            if parm is not None and parm.parmTemplate().type() == hou.parmTemplateType.String:
                try:
                    paths.add(_norm(parm.evalAsString()))
                except hou.OperationFailed:
                    pass
        for folder, prefix in wanted.items():
            if any(p.startswith(prefix) for p in paths) and node not in found[folder]:
                found[folder].append(node)
    return found


def show_node(node):
    """Select the node, make it current in the Network Editor and frame it."""
    node.setSelected(True, clear_all_selected=True)
    if hou.isUIAvailable():
        editor = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
        if editor is not None:
            editor.setCurrentNode(node)
            editor.homeToSelection()


def old_versions(caches, keep=2):
    """Paths of every version older than the `keep` newest of each cache."""
    return [v["path"] for versions in caches.values() for v in versions[keep:]]


def human(size):
    for unit in ("o", "Ko", "Mo", "Go"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit in ("o", "Ko") else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.2f} To"


def recycle(paths):
    """Send folders to the Windows Recycle Bin (recoverable). Windows itself warns if something is too big for it."""
    if not paths:
        return
    if sys.platform != "win32":
        raise RuntimeError("Corbeille disponible seulement sous Windows.")
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

    FO_DELETE, FOF_ALLOWUNDO, FOF_NOCONFIRMATION, FOF_WANTNUKEWARNING = 3, 0x40, 0x10, 0x4000
    files = "\0".join(os.path.normpath(p) for p in paths) + "\0\0"
    op = SHFILEOPSTRUCTW(None, FO_DELETE, files, None, FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_WANTNUKEWARNING,
                         False, None, None)
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if result != 0 or op.fAnyOperationsAborted:
        raise RuntimeError(f"Suppression interrompue (code {result}).")
