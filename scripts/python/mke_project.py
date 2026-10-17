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


def add_entity(info, kind, **names):
    """kind 'shot' (seq=, shot=) or 'asset' (asset=). Creates its folders and records it in project.json."""
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
        write_project(info)
    return created


def add_shot(info, seq, shot):
    return add_entity(info, "shot", seq=seq, shot=shot)


def add_asset(info, asset):
    return add_entity(info, "asset", asset=asset)


def startup():
    """Houdini start (pythonrc.py): Manual update mode so heavy scenes do not cook on open."""
    if hou.isUIAvailable():
        hou.setUpdateMode(hou.updateMode.Manual)
