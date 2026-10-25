"""Project core for MKE Tools: presets, project.json, $JOB/$CACHE, versioning, shots and assets.

No UI here, so everything can run in hython. projectSetup.py is the window on top of it.
"""
import datetime
import json
import os
import re
import unicodedata

import hou

PACKAGE_DIR = os.environ.get("MKETOOLS_DIR") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PRESETS_FILE = os.path.join(PACKAGE_DIR, "config", "project_presets.json")
PROJECT_FILE = "PIPELINE/project.json"
SCENES_DIR = "3D/SCENES"
VERSION_RE = re.compile(r"_v(\d+)$")


def _slash(path):
    return path.replace("\\", "/")


def user_trigram():
    import mke_utils
    return mke_utils.get_user_trigram()


def sanitize_name(name):
    """'Mon projet été' -> 'Mon_projet_ete'. Only letters, digits, _ and -."""
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_")


def load_presets():
    with open(PRESETS_FILE, encoding="utf-8") as f:
        return json.load(f)


def preset_settings(presets, type_):
    """Defaults merged with the type overrides (fps, frame range, resolution, ocio)."""
    settings = dict(presets["defaults"])
    settings.update({k: v for k, v in presets["types"].get(type_, {}).items() if k != "folders"})
    return settings


def preset_folders(presets, type_, cache):
    folders = presets["base_folders"] + presets["types"].get(type_, {}).get("folders", [])
    return [f.format(cache=cache, type=type_) for f in folders]


# ---------------------------------------------------------------- versioning

def version_up_path(path):
    """scene_v0001.hip -> scene_v0002.hip. Keeps the existing padding (_v025 -> _v026), new files get 4 digits."""
    base, ext = os.path.splitext(path)
    match = VERSION_RE.search(base)
    if match:
        digits = match.group(1)
        return VERSION_RE.sub(f"_v{int(digits) + 1:0{len(digits)}d}", base) + ext
    return f"{base}_v0001{ext}"


def free_version_path(path):
    """Never overwrite: bump the version until the file does not exist."""
    while os.path.exists(path):
        path = version_up_path(path)
    return path


# ---------------------------------------------------------------- project file

def find_project(path):
    """Walk up from path to the folder holding PIPELINE/project.json. Returns the project dict or None."""
    path = os.path.abspath(path)
    while True:
        candidate = os.path.join(path, PROJECT_FILE)
        if os.path.isfile(candidate):
            return read_project(path)
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent


def read_project(root):
    with open(os.path.join(root, PROJECT_FILE), encoding="utf-8") as f:
        info = json.load(f)
    info["root"] = _slash(root)  # the real location wins, so a moved project or a new drive letter still works
    return info


def write_project(info):
    data = {k: v for k, v in info.items() if k != "root"}
    with open(os.path.join(info["root"], PROJECT_FILE), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def scenes_dir(info):
    """Folder holding the project's scenes: 3D/SCENES for MKE projects, whatever was adopted otherwise (ex: WORK)."""
    return info.get("scenes", SCENES_DIR)


def cache_dir(info):
    return _slash(os.path.join(info["root"], info["cache"]))


def apply_project(info, scene_settings=True):
    """Set $JOB, $CACHE and $PROJECT as global variables: they are saved inside the .hip."""
    for var, value in (("JOB", info["root"]), ("CACHE", cache_dir(info)), ("PROJECT", info["name"])):
        hou.putenv(var, value)
        hou.hscript(f"set -g {var} = '{value}'")
    if scene_settings:
        hou.setFps(info["fps"])
        hou.playbar.setFrameRange(info["frame_start"], info["frame_end"])
        hou.playbar.setPlaybackRange(info["frame_start"], info["frame_end"])
        hou.setFrame(info["frame_start"])


def apply_to_scene(info):
    """Push edited project settings onto the open scene: variables, fps, and the shot or project frame range."""
    apply_project(info, scene_settings=False)
    hou.setFps(info["fps"])
    shot = None if hou.hipFile.isNewFile() else shot_for_path(info, hou.hipFile.path())
    apply_range(*(shot_range(info, shot) if shot else (info["frame_start"], info["frame_end"])))


def on_scene_load():
    """Called by 456.py: re-point $JOB/$CACHE on the project the .hip lives in."""
    global _origin
    hip = hou.hipFile.path()
    _origin = None if hou.hipFile.isNewFile() else _slash(hip)  # the next version saved is based on this one
    if hou.hipFile.isNewFile() or not os.path.isfile(hip):
        return None
    info = find_project(os.path.dirname(hip))
    if info:
        apply_project(info, scene_settings=False)
        shot = shot_for_path(info, hip)
        if shot:
            apply_range(*shot_range(info, shot))
    return info


def server_warning(root):
    """Message if MKE_SERVER_PATH is set (USD Dependency Checker config) and the project is not on it."""
    server = hou.getenv("MKE_SERVER_PATH") or os.environ.get("MKE_SERVER_PATH")
    if server and not _slash(os.path.abspath(root)).lower().startswith(_slash(server).lower()):
        return f"The project is not on the server ({server}): Deadline will not be able to read its files."
    return ""


# ---------------------------------------------------------------- recent projects

def _recent_file():
    return os.path.join(hou.getenv("HOUDINI_USER_PREF_DIR") or os.path.expanduser("~"), "mke_recent_projects.json")


def recent_projects():
    try:
        with open(_recent_file(), encoding="utf-8") as f:
            return [p for p in json.load(f) if os.path.isfile(os.path.join(p, PROJECT_FILE))]
    except (OSError, ValueError):
        return []


def add_recent(root):
    root = _slash(root)
    projects = [root] + [p for p in recent_projects() if p != root]
    with open(_recent_file(), "w", encoding="utf-8") as f:
        json.dump(projects[:15], f, indent=4)


def _prefs_file():
    return os.path.join(hou.getenv("HOUDINI_USER_PREF_DIR") or os.path.expanduser("~"), "mke_projects_prefs.json")


def get_pref(key, default=None):
    try:
        with open(_prefs_file(), encoding="utf-8") as f:
            return json.load(f).get(key, default)
    except (OSError, ValueError):
        return default


def set_pref(key, value):
    try:
        with open(_prefs_file(), encoding="utf-8") as f:
            prefs = json.load(f)
    except (OSError, ValueError):
        prefs = {}
    prefs[key] = value
    with open(_prefs_file(), "w", encoding="utf-8") as f:
        json.dump(prefs, f, indent=4)


def latest_scene(info):
    scenes = []
    for folder, _, files in os.walk(os.path.join(info["root"], scenes_dir(info))):
        scenes += [os.path.join(folder, f) for f in files if f.endswith((".hip", ".hiplc", ".hipnc"))]
    return _slash(max(scenes, key=os.path.getmtime)) if scenes else None


def open_project(root):
    """Set the project and open its most recent scene (or just set the variables if there is none)."""
    info = read_project(root)
    scene = latest_scene(info)
    if scene:
        hou.hipFile.load(scene, suppress_save_prompt=True, ignore_load_warnings=True)
    apply_project(info, scene_settings=not scene)
    add_recent(info["root"])
    return info, scene


# ---------------------------------------------------------------- creation

def scene_name(info, *parts):
    return "_".join([info["name"], *parts, info["type"], user_trigram(), "v0001"]) + ".hip"


def create_project(parent, name, type_, folders, settings, cache, keep_scene=False, starter=True):
    """Create folders, project.json, README, launcher and the first .hip. Returns (info, hip_path)."""
    name = sanitize_name(name)
    if not name:
        raise ValueError("Empty project name.")
    root = _slash(os.path.join(parent, name))
    if os.path.isfile(os.path.join(root, PROJECT_FILE)):
        raise FileExistsError(root)

    for folder in set(folders) | {cache, SCENES_DIR, "PIPELINE"}:
        os.makedirs(os.path.join(root, folder), exist_ok=True)

    info = {
        "root": root, "name": name, "type": type_, "cache": cache,
        "created": datetime.date.today().isoformat(), "author": user_trigram(),
        "fps": settings["fps"], "frame_start": settings["frame_start"], "frame_end": settings["frame_end"],
        "resolution": list(settings["resolution"]), "ocio": settings.get("ocio", ""),
        "shots": [], "assets": [],
    }
    write_project(info)
    _write_readme(info)
    _write_launcher(info)

    if not keep_scene:
        hou.hipFile.clear(suppress_save_prompt=True)
    apply_project(info)
    if starter:
        build_starter_scene(info)
    hip = free_version_path(_slash(os.path.join(root, SCENES_DIR, scene_name(info))))
    hou.hipFile.save(hip)
    record_version(hip, "Project created")
    add_recent(root)
    return info, hip


def detect_scenes_dir(root):
    """Sub-folder of root holding the most scenes (backup/ and autosave/ ignored), relative, '' for root itself."""
    counts = {}
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in ("backup", AUTOSAVE_DIR, THUMBS_DIR)]
        hips = sum(f.endswith(HIP_EXT) for f in files)
        if hips:
            counts[folder] = hips
    if not counts:
        return SCENES_DIR
    best = max(counts, key=counts.get)
    return _slash(os.path.relpath(best, root)) if best != root else ""


def adopt_project(root, type_, settings, scenes=None, cache=None, name=None):
    """Turn an existing folder into a pipeline project WITHOUT moving anything: only PIPELINE/project.json is written.
    scenes / cache are relative to root (detected / scenes + '/geo' by default)."""
    root = _slash(os.path.abspath(root))
    if os.path.isfile(os.path.join(root, PROJECT_FILE)):
        raise FileExistsError(root)
    scenes = detect_scenes_dir(root) if scenes is None else scenes
    cache = cache or _slash(os.path.join(scenes, "geo")).lstrip("/")
    os.makedirs(os.path.join(root, "PIPELINE"), exist_ok=True)
    info = {
        "root": root, "name": name or sanitize_name(os.path.basename(root)), "type": type_,
        "scenes": scenes, "cache": cache,
        "created": datetime.date.today().isoformat(), "author": user_trigram(), "adopted": True,
        "fps": settings["fps"], "frame_start": settings["frame_start"], "frame_end": settings["frame_end"],
        "resolution": list(settings["resolution"]), "ocio": settings.get("ocio", ""),
        "shots": [], "assets": [],
    }
    write_project(info)
    add_recent(root)
    return info


def _write_readme(info):
    lines = [
        f"# {info['name']}", "",
        f"- Type : {info['type']}",
        f"- Created on {info['created']} by {info['author']}",
        f"- {info['fps']} fps, frames {info['frame_start']}-{info['frame_end']}, {info['resolution'][0]}x{info['resolution'][1]}",
        f"- Cache : `{info['cache']}`",
        f"- OCIO : `{info['ocio'] or 'Houdini default'}`", "",
        "Start Houdini with `PIPELINE/launch_houdini.bat` to get the project's $JOB, $CACHE and OCIO from startup.",
    ]
    with open(os.path.join(info["root"], "README.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _write_launcher(info):
    """OCIO has to be set before Houdini starts, so the project gets its own launcher."""
    exe = _slash(os.path.join(hou.getenv("HFS"), "bin", "houdini.exe"))
    lines = [
        "@echo off",
        'set "JOB=%~dp0.."',
        f'set "CACHE={info["cache"]}"' if os.path.isabs(info["cache"]) else f'set "CACHE=%JOB%\\{info["cache"]}"',
        f'set "PROJECT={info["name"]}"',
    ]
    if info["ocio"]:
        lines.append(f'set "OCIO={info["ocio"]}"')
    lines.append(f'start "" "{exe}"')
    with open(os.path.join(info["root"], "PIPELINE", "launch_houdini.bat"), "w", encoding="utf-8") as f:
        f.write("\r\n".join(lines) + "\r\n")


def build_starter_scene(info):
    """/stage: MKE Import -> MKE File Cache, and Camera -> MKE Render Layer -> MKE Submitter, pointed at the project."""
    stage = hou.node("/stage")
    made = {}

    def make(type_name, node_name, parms, input_node=None):
        try:
            node = stage.createNode(type_name, node_name)
        except hou.OperationFailed:
            return None  # HDA not installed: skip it, the rest of the scene still works
        for parm, value in parms.items():
            if node.parm(parm) is not None:
                node.parm(parm).set(value)
        if input_node is not None:
            node.setInput(0, input_node)
        made[node_name] = node
        return node

    importer = make("MKE.dev::import::1.1", "import", {})
    make("MKE::mke_filecache::1.1", "filecache", {"saveDir": "$JOB/USD"}, importer)
    cam = make("camera", "camera", {"primpath": "/cameras/camera1",
                                    "resolutionx": info["resolution"][0], "resolutiony": info["resolution"][1]})
    layer = make("MKE::mke_render_layer::1.0", "render_layer",
                 {"camera": "/cameras/camera1", "saveDir": f"$JOB/OUT/{info['type']}/RENDER"}, cam)
    make("MKE::mke_submitter::1.0", "submitter", {}, layer)
    stage.layoutChildren()
    return made


def add_entity(info, kind, frame_range=None, **names):
    """kind 'shot' (seq=, shot=) or 'asset' (asset=). Creates its folders and records it in project.json.
    For a shot, frame_range (start, end) is stored; calling again on an existing shot updates it."""
    names = {k: sanitize_name(v) for k, v in names.items()}
    if not all(names.values()):
        raise ValueError("Empty name.")
    presets = load_presets()
    created = []
    for template in presets[f"{kind}_folders"]:
        path = os.path.join(info["root"], template.format(cache=info["cache"], type=info["type"], **names))
        os.makedirs(path, exist_ok=True)
        created.append(_slash(path))
    entry = "/".join(names.values())
    if entry not in info[f"{kind}s"]:
        info[f"{kind}s"].append(entry)
    if kind == "shot":
        info.setdefault("shot_ranges", {})[entry] = list(frame_range or shot_range(info, entry))
    write_project(info)
    return created


def add_shot(info, seq, shot, frame_range=None):
    return add_entity(info, "shot", frame_range, seq=seq, shot=shot)


def add_asset(info, asset):
    return add_entity(info, "asset", asset=asset)


# ---------------------------------------------------------------- shot ranges

def shot_range(info, shot):
    """(start, end) of a 'seq/shot', falling back on the project range."""
    return tuple(info.get("shot_ranges", {}).get(shot, (info["frame_start"], info["frame_end"])))


def apply_range(start, end):
    hou.playbar.setFrameRange(start, end)
    hou.playbar.setPlaybackRange(start, end)
    if not start <= hou.frame() <= end:
        hou.setFrame(start)


def shot_for_path(info, hip):
    """'seq/shot' if the .hip lives in 3D/SCENES/seq/shot, else None."""
    rel = _slash(os.path.relpath(os.path.dirname(hip), os.path.join(info["root"], scenes_dir(info))))
    return rel if rel in info["shots"] else None


# ---------------------------------------------------------------- scene versions (browser)

VERSIONS_FILE = "_versions.json"
THUMBS_DIR = ".thumbs"
HIP_EXT = (".hip", ".hiplc", ".hipnc")


def entity_dir(info, kind="project", **names):
    """Scene folder of the project root, a shot (seq=, shot=) or an asset (asset=)."""
    sub = {"project": "", "shot": "{seq}/{shot}", "asset": "ASSETS/{asset}"}[kind].format(**names)
    return _slash(os.path.join(info["root"], scenes_dir(info), sub)).rstrip("/")


def _read_versions(folder):
    try:
        with open(os.path.join(folder, VERSIONS_FILE), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def thumbnail_path(hip):
    folder, name = os.path.split(hip)
    return _slash(os.path.join(folder, THUMBS_DIR, os.path.splitext(name)[0] + ".jpg"))


COMMENT_PARENT_RE = re.compile(r"\b(?:from|based on|base)\s+v0*(\d+)\b", re.IGNORECASE)  # "back from v58"


def list_versions(folder):
    """Scenes directly in folder, newest first, with their comment, author, date and thumbnail.
    "parent" is the scene a version was made from: recorded at save, else read from a "from v58" comment,
    else the previous number (old versions, "inferred": True). Autosaves hang on the version they autosave."""
    if not os.path.isdir(folder):
        return []
    meta = _read_versions(folder)
    versions = []
    for name in os.listdir(folder):
        if not name.endswith(HIP_EXT):
            continue
        path = _slash(os.path.join(folder, name))
        info = meta.get(name, {})
        match = VERSION_RE.search(os.path.splitext(name)[0])
        mtime = os.path.getmtime(path)
        thumb = thumbnail_path(path)
        versions.append({
            "path": path, "file": name, "mtime": mtime, "autosave": False,
            "number": int(match.group(1)) if match else None,
            "stem": VERSION_RE.sub("", os.path.splitext(name)[0]),
            "version": f"v{int(match.group(1)):04d}" if match else "-",
            "date": info.get("date") or datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M"),
            "user": info.get("user", ""), "comment": info.get("comment", ""),
            "parent": _slash(os.path.join(folder, info["parent"])) if info.get("parent") else None,
            "inferred": False, "thumb": thumb if os.path.isfile(thumb) else None,
        })
    by_number = {(v["stem"], v["number"]): v["path"] for v in versions if v["number"] is not None}
    for v in versions:
        if v["parent"] or v["number"] is None:
            continue
        hint = COMMENT_PARENT_RE.search(v["comment"])
        if hint and (v["stem"], int(hint.group(1))) in by_number:
            v["parent"] = by_number[(v["stem"], int(hint.group(1)))]
        else:
            older = [n for s, n in by_number if s == v["stem"] and n < v["number"]]
            v["parent"] = by_number[(v["stem"], max(older))] if older else None
            v["inferred"] = bool(older)
    autosaves = os.path.join(folder, AUTOSAVE_DIR)
    for name in os.listdir(autosaves) if os.path.isdir(autosaves) else []:
        if name.endswith(HIP_EXT):
            path = _slash(os.path.join(autosaves, name))
            mtime = os.path.getmtime(path)
            versions.append({
                "path": path, "file": name, "mtime": mtime, "version": "auto", "autosave": True,
                "date": datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M"), "user": "",
                "comment": f"Autosave of {name.replace(AUTOSAVE_SUFFIX, '')}", "thumb": None,
                "parent": autosave_source(path), "inferred": False,
            })
    return sorted(versions, key=lambda v: v["mtime"], reverse=True)


GRAPH_LANES_MAX = 8


def version_graph(versions):
    """Git-like lanes for versions listed newest first. Per row: {"lane": column of the dot,
    "lines": [(from_lane, to_lane, "top"|"bottom")]}: "top" goes from the row's top edge to the dot height,
    "bottom" from the dot height to the row's bottom edge. A branch opens a new lane and joins its parent's lane
    on the parent's row."""
    paths = {v["path"] for v in versions}
    seen, lanes, rows = set(), [], []
    for v in versions:
        path = v["path"]
        waiting = [i for i, p in enumerate(lanes) if p == path]
        if waiting:
            lane = waiting[0]
        else:
            lane = lanes.index(None) if None in lanes else len(lanes)
            lanes += [None] * (lane + 1 - len(lanes))
        lines = [(i, lane if p == path else i, "top") for i, p in enumerate(lanes) if p is not None]
        for i in waiting:
            lanes[i] = None
        seen.add(path)
        parent = v.get("parent")
        lanes[lane] = parent if parent in paths and parent not in seen else None
        while lanes and lanes[-1] is None:
            lanes.pop()
        lines += [(i, i, "bottom") for i, p in enumerate(lanes) if p is not None]
        rows.append({"lane": min(lane, GRAPH_LANES_MAX - 1), "lines": [
            (min(a, GRAPH_LANES_MAX - 1), min(b, GRAPH_LANES_MAX - 1), part) for a, b, part in lines]})
    return rows


def _parent_ref(folder, parent):
    same_folder = os.path.normcase(os.path.dirname(os.path.abspath(parent))) == os.path.normcase(os.path.abspath(folder))
    return os.path.basename(parent) if same_folder else _slash(parent)


def set_parent(hip, parent):
    """Record which scene hip was made from (a file name when both are in the same folder)."""
    folder, name = os.path.split(hip)
    meta = _read_versions(folder)
    meta.setdefault(name, {})["parent"] = _parent_ref(folder, parent)
    with open(os.path.join(folder, VERSIONS_FILE), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=4, ensure_ascii=False)


_origin = None  # scene the session was loaded from or last saved as


def _on_hip_event(event_type):
    """After any save under a new name (Save Up, Save As, Houdini's +): remember the scene it came from."""
    global _origin
    if event_type != hou.hipFileEventType.AfterSave:
        return
    hip = _slash(hou.hipFile.path())  # session name: autosaves and mwrite -n copies do not change it
    if _origin and hip != _origin and os.path.isfile(hip):
        if not _read_versions(os.path.dirname(hip)).get(os.path.basename(hip), {}).get("parent"):
            set_parent(hip, _origin)
    _origin = hip


def record_version(hip, comment="", parent=None):
    """Store author, date, comment and parent scene of a saved scene, and grab a viewport thumbnail when there is a UI."""
    folder, name = os.path.split(hip)
    meta = _read_versions(folder)
    parent = _parent_ref(folder, parent) if parent else meta.get(name, {}).get("parent")  # set by _on_hip_event
    meta[name] = {"comment": comment, "user": user_trigram(), "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}
    if parent:
        meta[name]["parent"] = parent
    with open(os.path.join(folder, VERSIONS_FILE), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=4, ensure_ascii=False)
    capture_thumbnail(hip)


def capture_thumbnail(hip):
    """One-frame flipbook of the current viewport. Silently skipped without a Scene Viewer (hython)."""
    if not hou.isUIAvailable():
        return None
    try:
        viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
        if viewer is None:
            return None
        path = thumbnail_path(hip)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        settings = viewer.flipbookSettings().stash()
        settings.frameRange((hou.frame(), hou.frame()))
        settings.output(path)
        settings.outputToMPlay(False)
        settings.useResolution(True)
        settings.resolution((480, 270))
        viewer.flipbook(viewer.curViewport(), settings)
        return path
    except Exception:  # a thumbnail must never block a save
        return None


def save_version(comment=""):
    """Save Up: next free version of the current scene, with its comment."""
    parent = None if hou.hipFile.isNewFile() else _slash(hou.hipFile.path())
    new_path = free_version_path(version_up_path(hou.hipFile.path()))
    hou.hipFile.save(new_path)
    record_version(new_path, comment, parent)
    return new_path


def new_entity_scene(info, kind="project", keep_scene=False, starter=True, **names):
    """New scene of a shot / asset / the project, in its folder, with the shot range applied."""
    names = {k: sanitize_name(v) for k, v in names.items()}
    folder = entity_dir(info, kind, **names)
    os.makedirs(folder, exist_ok=True)
    hip = free_version_path(_slash(os.path.join(folder, scene_name(info, *names.values()))))
    if not keep_scene:
        hou.hipFile.clear(suppress_save_prompt=True)
    apply_project(info)
    if kind == "shot":
        apply_range(*shot_range(info, "/".join(names.values())))
    if starter and not keep_scene:
        build_starter_scene(info)
    hou.hipFile.save(hip)
    record_version(hip, "New scene")
    add_recent(info["root"])
    return hip


def open_scene(hip):
    hou.hipFile.load(hip, suppress_save_prompt=True, ignore_load_warnings=True)
    original = autosave_source(hip)
    if original:
        # Recovered autosave: point the session at the next free version next to the original,
        # so Ctrl+S never writes back into autosave/ nor over a real version.
        hou.hipFile.setName(free_version_path(version_up_path(original)))
    info = on_scene_load()  # 456.py also does it in Houdini; explicit so it works everywhere
    if original:
        global _origin
        _origin = original  # the version saved from a recovered autosave is based on the autosaved scene
    if info:
        add_recent(info["root"])
    return info


# ---------------------------------------------------------------- dailies and media

VIDEO_EXT = (".mp4", ".mov", ".avi", ".mkv", ".webm")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".exr", ".tif", ".tiff")
SEQUENCE_RE = re.compile(r"^(.*?[._])(\d{3,})(\.[A-Za-z]+)$")  # name.0001.exr / name_0001.png, not name_v003.png
MEDIA_MAX_DEPTH = 4


def dailies_dir(info, shot=None):
    """Where flipbooks go: project.json 'dailies', else OUT/blast if it exists, else _DAILIES. Per shot when that folder exists."""
    base = info.get("dailies") or ("OUT/blast" if os.path.isdir(os.path.join(info["root"], "OUT", "blast")) else "_DAILIES")
    folder = os.path.join(info["root"], base)
    if shot and os.path.isdir(os.path.join(folder, shot)):
        folder = os.path.join(folder, shot)
    return _slash(folder)


def media_roots(info):
    folders = info.get("media") or ["_DAILIES", "OUT"]
    return [_slash(os.path.join(info["root"], f)) for f in folders if os.path.isdir(os.path.join(info["root"], f))]


def _matches_entity(path, kind, names):
    if kind == "project":
        return True
    low = path.lower()
    if kind == "shot":
        seq, shot = names["seq"].lower(), names["shot"].lower()
        return f"/{seq}/{shot}/" in low or f"{seq}_{shot}" in low
    return names["asset"].lower() in low


def list_media(info, kind="project", **names):
    """Videos, images and image sequences (grouped) under the project's media folders, newest first."""
    entries, sequences = [], {}
    for root in media_roots(info):
        base_depth = root.count("/")
        for folder, dirs, files in os.walk(root):
            folder = _slash(folder)
            if folder.count("/") - base_depth >= MEDIA_MAX_DEPTH:
                dirs[:] = []
            for name in files:
                path = f"{folder}/{name}"
                lower = name.lower()
                if not lower.endswith(VIDEO_EXT + IMAGE_EXT) or not _matches_entity(path, kind, names):
                    continue
                match = SEQUENCE_RE.match(name)
                if lower.endswith(IMAGE_EXT) and match:
                    key = (folder, match.group(1), len(match.group(2)), match.group(3))
                    sequences.setdefault(key, []).append((int(match.group(2)), path))
                    continue
                entries.append(_media_entry(path, "Video" if lower.endswith(VIDEO_EXT) else "Image", [path]))
    for (folder, prefix, padding, ext), frames in sequences.items():
        frames.sort()
        if len(frames) == 1:
            entries.append(_media_entry(frames[0][1], "Image", [frames[0][1]]))
            continue
        entry = _media_entry(f"{folder}/{prefix}{'#' * padding}{ext}", "Sequence", [p for _, p in frames])
        entry.update({"info": f"{frames[0][0]}-{frames[-1][0]}  ({len(frames)} images)",
                      "mplay": f"{folder}/{prefix}$F{padding}{ext}"})
        entries.append(entry)
    return sorted(entries, key=lambda e: e["mtime"], reverse=True)


def _media_entry(path, kind, files):
    newest = max(files, key=os.path.getmtime)
    size = sum(os.path.getsize(f) for f in files)
    return {
        "path": path, "name": os.path.basename(path), "folder": os.path.dirname(path), "kind": kind,
        "first": files[0], "mtime": os.path.getmtime(newest),
        "date": datetime.datetime.fromtimestamp(os.path.getmtime(newest)).strftime("%Y-%m-%d %H:%M"),
        "info": f"{size / 1e6:.1f} MB",
    }


# ---------------------------------------------------------------- autosave

AUTOSAVE_DIR = "autosave"
AUTOSAVE_SUFFIX = "_autosave"
AUTOSAVE_MINUTES = 15
_autosave_timer = None


def autosave_path(hip=None):
    """scenes/shot_v0003.hip -> scenes/autosave/shot_v0003_autosave.hip (untitled scenes go to the prefs folder)."""
    if hip is None:
        hip = None if hou.hipFile.isNewFile() else hou.hipFile.path()
    if hip:
        folder, name = os.path.split(hip)
        folder = os.path.join(folder, AUTOSAVE_DIR)
    else:
        folder = os.path.join(hou.getenv("HOUDINI_USER_PREF_DIR") or os.path.expanduser("~"), AUTOSAVE_DIR)
        name = "untitled" + os.path.splitext(hou.hipFile.path())[1]
    stem, ext = os.path.splitext(name)
    return _slash(os.path.join(folder, stem + AUTOSAVE_SUFFIX + ext))


def autosave_source(path):
    """The scene an autosave file was made from, or None if path is not an autosave."""
    folder, name = os.path.split(path)
    stem, ext = os.path.splitext(name)
    if os.path.basename(folder) != AUTOSAVE_DIR or not stem.endswith(AUTOSAVE_SUFFIX):
        return None
    return _slash(os.path.join(os.path.dirname(folder), stem[:-len(AUTOSAVE_SUFFIX)] + ext))


def autosave():
    """Write a copy of the session to its _autosave file. The open scene keeps its name and its unsaved state.
    One autosave per scene version, overwritten each time. Returns the path, or None when there was nothing to save."""
    if hou.hipFile.isLoadingHipFile() or hou.hipFile.isShuttingDown() or not hou.hipFile.hasUnsavedChanges():
        return None
    target = autosave_path()
    backup = hou.hipFile.saveAsBackup()  # writes $HIP/backup/<name>_bakN without renaming the session
    os.makedirs(os.path.dirname(target), exist_ok=True)
    os.replace(backup, target)
    try:
        os.rmdir(os.path.dirname(backup))  # only removes backup/ if we were its only user
    except OSError:
        pass
    return target


def _autosave_tick():
    try:
        path = autosave()
        if path:
            hou.ui.setStatusMessage(f"Autosave : {os.path.basename(path)}")
    except Exception as error:  # never interrupt the artist for an autosave
        hou.ui.setStatusMessage(f"Autosave failed: {error}", severity=hou.severityType.Warning)


def set_autosave(enabled):
    """Start or stop the 15 minutes autosave timer and remember the choice."""
    global _autosave_timer
    set_pref("autosave", bool(enabled))
    if _autosave_timer is not None:
        _autosave_timer.stop()
        _autosave_timer = None
    if enabled and hou.isUIAvailable():
        from hutil.Qt import QtCore
        _autosave_timer = QtCore.QTimer()
        _autosave_timer.timeout.connect(_autosave_tick)
        _autosave_timer.start(AUTOSAVE_MINUTES * 60 * 1000)


NON_COMMERCIAL = ("Apprentice", "ApprenticeHD", "Education")
_licence_timer = None
_licence_warned = False


def check_licence():
    """Warn once per session when Houdini runs non-commercial: every save would become .hipnc / .usdnc,
    and SideFX does not let those files come back to Indie. Returns True when the session is fine."""
    global _licence_warned
    category = hou.licenseCategory().name()
    if category not in NON_COMMERCIAL:
        return True
    if not _licence_warned and hou.isUIAvailable():
        _licence_warned = True
        hou.ui.displayMessage(
            f"Houdini is running with a {category} licence, not Indie.\n\n"
            "Do not save: scenes would become .hipnc and USD exports .usdnc, and they cannot be "
            "turned back into Indie files.\n\nCheck the License Administrator, then restart Houdini.",
            severity=hou.severityType.Warning, title="Not in Indie")
    return False


def startup():
    """Houdini start (pythonrc.py): Manual update mode so heavy scenes do not cook on open, autosave,
    and a licence check every 30 s (an asset can switch a session to non-commercial mid-way)."""
    global _licence_timer
    if _on_hip_event not in hou.hipFile.eventCallbacks():
        hou.hipFile.addEventCallback(_on_hip_event)
    if hou.isUIAvailable():
        hou.setUpdateMode(hou.updateMode.Manual)
        set_autosave(get_pref("autosave", True))
        import mke_tracking
        mke_tracking.start_tracking()
        from hutil.Qt import QtCore
        _licence_timer = QtCore.QTimer()
        _licence_timer.timeout.connect(check_licence)
        _licence_timer.start(30 * 1000)
        check_licence()
