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
    """scene_v0001.hip -> scene_v0002.hip. Always 4 digits (old _v002 becomes _v0003)."""
    base, ext = os.path.splitext(path)
    match = VERSION_RE.search(base)
    if match:
        return VERSION_RE.sub(f"_v{int(match.group(1)) + 1:04d}", base) + ext
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


def on_scene_load():
    """Called by 456.py: re-point $JOB/$CACHE on the project the .hip lives in."""
    hip = hou.hipFile.path()
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
        return f"Le projet n'est pas sur le serveur ({server}) : Deadline ne pourra pas lire ses fichiers."
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


def latest_scene(info):
    scenes = []
    for folder, _, files in os.walk(os.path.join(info["root"], SCENES_DIR)):
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
        raise ValueError("Nom de projet vide.")
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
    record_version(hip, "Création du projet")
    add_recent(root)
    return info, hip


def _write_readme(info):
    lines = [
        f"# {info['name']}", "",
        f"- Type : {info['type']}",
        f"- Créé le {info['created']} par {info['author']}",
        f"- {info['fps']} fps, frames {info['frame_start']}-{info['frame_end']}, {info['resolution'][0]}x{info['resolution'][1]}",
        f"- Cache : `{info['cache']}`",
        f"- OCIO : `{info['ocio'] or 'défaut Houdini'}`", "",
        "Lance Houdini avec `PIPELINE/launch_houdini.bat` pour avoir $JOB, $CACHE et l'OCIO du projet dès le démarrage.",
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
        raise ValueError("Nom vide.")
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
    rel = _slash(os.path.relpath(os.path.dirname(hip), os.path.join(info["root"], SCENES_DIR)))
    return rel if rel in info["shots"] else None


# ---------------------------------------------------------------- scene versions (browser)

VERSIONS_FILE = "_versions.json"
THUMBS_DIR = ".thumbs"
HIP_EXT = (".hip", ".hiplc", ".hipnc")


def entity_dir(info, kind="project", **names):
    """Scene folder of the project root, a shot (seq=, shot=) or an asset (asset=)."""
    sub = {"project": "", "shot": "{seq}/{shot}", "asset": "ASSETS/{asset}"}[kind].format(**names)
    return _slash(os.path.join(info["root"], SCENES_DIR, sub)).rstrip("/")


def _read_versions(folder):
    try:
        with open(os.path.join(folder, VERSIONS_FILE), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def thumbnail_path(hip):
    folder, name = os.path.split(hip)
    return _slash(os.path.join(folder, THUMBS_DIR, os.path.splitext(name)[0] + ".jpg"))


def list_versions(folder):
    """Scenes directly in folder, newest first, with their comment, author, date and thumbnail."""
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
            "path": path, "file": name, "mtime": mtime,
            "version": f"v{int(match.group(1)):04d}" if match else "-",
            "date": info.get("date") or datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M"),
            "user": info.get("user", ""), "comment": info.get("comment", ""),
            "thumb": thumb if os.path.isfile(thumb) else None,
        })
    return sorted(versions, key=lambda v: v["mtime"], reverse=True)


def record_version(hip, comment=""):
    """Store author, date and comment of a saved scene, and grab a viewport thumbnail when there is a UI."""
    folder, name = os.path.split(hip)
    meta = _read_versions(folder)
    meta[name] = {"comment": comment, "user": user_trigram(),
                  "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}
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
    new_path = free_version_path(version_up_path(hou.hipFile.path()))
    hou.hipFile.save(new_path)
    record_version(new_path, comment)
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
    record_version(hip, "Nouvelle scène")
    add_recent(info["root"])
    return hip


def open_scene(hip):
    hou.hipFile.load(hip, suppress_save_prompt=True, ignore_load_warnings=True)
    info = on_scene_load()  # 456.py also does it in Houdini; explicit so it works everywhere
    if info:
        add_recent(info["root"])
    return info


def startup():
    """Houdini start (pythonrc.py): Manual update mode so heavy scenes do not cook on open."""
    if hou.isUIAvailable():
        hou.setUpdateMode(hou.updateMode.Manual)
