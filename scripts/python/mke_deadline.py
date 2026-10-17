"""Night queue on Deadline: send File Caches / ROPs as Deadline jobs (now or tonight), chained by node connections.

Jobs use Deadline's CommandLine plugin running this Houdini's hython on mke_deadline_cook.py, so they do not
depend on which Houdini versions the Deadline Houdini plugin knows. Submitted jobs are remembered per project
in PIPELINE/queue.json; their live state comes from deadlinecommand.
"""
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

import hou

import mke_project

QUEUE_FILE = "PIPELINE/queue.json"
LOG_DIR = "PIPELINE/deadline_logs"
COOK_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mke_deadline_cook.py").replace("\\", "/")
DONE = ("Completed", "Failed")
NIGHT_DEFAULT = "20:00"


# ---------------------------------------------------------------- deadlinecommand

def deadline_command():
    found = shutil.which("deadlinecommand")
    if found:
        return found
    folder = os.environ.get("DEADLINE_PATH", r"C:\Program Files\Thinkbox\Deadline10\bin")
    path = os.path.join(folder, "deadlinecommand.exe" if sys.platform == "win32" else "deadlinecommand")
    return path if os.path.isfile(path) else None


def run(*args, timeout=60):
    exe = deadline_command()
    if not exe:
        raise RuntimeError("deadlinecommand introuvable : Deadline n'est pas installé sur ce poste.")
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    result = subprocess.run([exe, *map(str, args)], capture_output=True, text=True, timeout=timeout, creationflags=flags)
    return result.stdout


def _parse(text):
    data = {}
    for line in text.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            data.setdefault(key.strip(), value.strip())
    return data


def pools():
    try:
        return [p.strip() for p in run("-Pools").splitlines() if p.strip()]
    except Exception:
        return []


# ---------------------------------------------------------------- what can be sent

def is_filecache(node):
    return node.type().nameComponents()[2] == "filecache"


def can_submit(node):
    return node is not None and (is_filecache(node) or node.type().category() == hou.ropNodeTypeCategory())


def frame_range(node):
    if node.parm("trange") is not None and node.evalParm("trange") == 0:
        return int(hou.frame()), int(hou.frame())
    if node.parm("f1") is not None:
        return int(node.evalParm("f1")), int(node.evalParm("f2"))
    start, end = hou.playbar.playbackRange()
    return int(start), int(end)


def output_dir(node):
    """Folder the job writes to (used to measure progress by counting written frames)."""
    for name in ("cachedir", "sopoutput", "lopoutput", "vm_picture", "picture"):
        parm = node.parm(name)
        if parm is not None:
            value = parm.evalAsString()
            return (value if name == "cachedir" else os.path.dirname(value)).replace("\\", "/")
    return ""


def display_name(node):
    name = node.evalParm("basename") if is_filecache(node) and node.parm("basename") else node.name()
    if node.parm("enableversion") is not None and node.evalParm("enableversion"):
        name += f"  v{node.evalParm('version')}"
    return name


# ---------------------------------------------------------------- queue file (per project)

def project_for_scene():
    return None if hou.hipFile.isNewFile() else mke_project.find_project(os.path.dirname(hou.hipFile.path()))


def read_queue(info):
    try:
        with open(os.path.join(info["root"], QUEUE_FILE), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def write_queue(info, entries):
    path = os.path.join(info["root"], QUEUE_FILE)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)
    os.replace(path + ".tmp", path)


def forget(info, job_id):
    write_queue(info, [e for e in read_queue(info) if e["id"] != job_id])


# ---------------------------------------------------------------- night schedule

def night_start(now=None):
    """Next start time for 'tonight' jobs, or None when we are already inside the night (start right away)."""
    now = now or datetime.datetime.now()
    hh, mm = map(int, mke_project.get_pref("night_start", NIGHT_DEFAULT).split(":"))
    start = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if now >= start or now.hour < 7:
        return None
    return start


# ---------------------------------------------------------------- submission

def upstream_jobs(info, node, hip):
    """Jobs still pending/running in this project for nodes upstream of `node` in the same scene: they become dependencies."""
    ancestors = {n.path() for n in node.inputAncestors()}
    live = {j["id"]: j for j in job_states(info)}
    return [e["id"] for e in read_queue(info)
            if e["node"] in ancestors and e["hip"] == hip and live.get(e["id"], {}).get("Status") not in DONE + (None,)]


def submit(node, tonight=False, priority=50, pool=None, dependencies=None, info=None):
    """Send `node` to Deadline. The scene must be saved: the job renders the .hip as it is on disk."""
    hip = hou.hipFile.path()
    info = info or project_for_scene()
    start, end = frame_range(node)
    when = night_start() if tonight else None
    deps = dependencies if dependencies is not None else (upstream_jobs(info, node, hip) if info else [])
    pool = pool or ("houdini" if "houdini" in pools() else "none")
    project = info["name"] if info else "SANS_PROJET"
    name = display_name(node)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_root = os.path.join(info["root"], LOG_DIR) if info else os.path.join(tempfile.gettempdir(), "mke_deadline_logs")
    log = os.path.join(log_root, f"{stamp}_{node.name()}.log").replace("\\", "/")
    hython = os.path.join(hou.getenv("HFS"), "bin", "hython.exe" if sys.platform == "win32" else "hython").replace("\\", "/")

    job = {
        "Plugin": "CommandLine",
        "Name": f"[{project}] {name}",
        "BatchName": f"{project}  {datetime.date.today():%d/%m}",
        "Comment": f"{os.path.basename(hip)}  {node.path()}",
        "Pool": pool, "Priority": priority,
        "Frames": f"{start}-{end}", "ChunkSize": end - start + 1,  # one task: simulations must cook in order
        "ExtraInfo0": node.path(), "ExtraInfo1": hip, "ExtraInfo2": info["root"] if info else "",
        "OutputDirectory0": output_dir(node),
    }
    if deps:
        job["JobDependencies"] = ",".join(deps)
    if when:
        job["ScheduledType"] = "Once"
        job["ScheduledStartDateTime"] = when.strftime("%d/%m/%Y %H:%M")
    plugin = {
        "Executable": hython,
        "Arguments": f'"{COOK_SCRIPT}" "{hip}" "{node.path()}" <STARTFRAME> <ENDFRAME> "{log}"',
        "StartupDirectory": os.path.dirname(hip),
        "Shell": "default", "ShellExecute": "False",
    }
    folder = tempfile.mkdtemp(prefix="mke_deadline_")
    files = []
    for kind, data in (("job", job), ("plugin", plugin)):
        path = os.path.join(folder, f"{kind}_info.job")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(f"{k}={v}" for k, v in data.items()) + "\n")
        files.append(path)
    output = run(*files)
    shutil.rmtree(folder, ignore_errors=True)
    job_id = _parse(output).get("JobID")
    if not job_id:
        raise RuntimeError(f"Deadline a refusé le job :\n{output.strip()[-600:]}")
    entry = {"id": job_id, "name": name, "node": node.path(), "hip": hip, "frames": [start, end], "log": log,
             "output": output_dir(node), "submitted": datetime.datetime.now().isoformat(timespec="seconds"),
             "scheduled": when.isoformat(timespec="minutes") if when else None, "deps": deps}
    if info:
        write_queue(info, read_queue(info) + [entry])
    return entry


# ---------------------------------------------------------------- live state

def job_states(info):
    """deadlinecommand -GetJob for every job of the project's queue, merged with what we stored."""
    states = []
    for entry in read_queue(info):
        try:
            data = _parse(run("-GetJob", entry["id"], timeout=20))
        except Exception:
            data = {}
        states.append({**entry, **data})
    return states


def written_frames(entry):
    folder = entry.get("output")
    if not folder or not os.path.isdir(folder):
        return 0
    return sum(1 for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f)))


def describe(job, now=None):
    """(group, label, color, percent, time text) shown in the queue tab."""
    now = now or datetime.datetime.now()
    status = job.get("Status")
    start, end = job["frames"]
    total = end - start + 1
    percent = 100 if status == "Completed" else min(99, int(100 * written_frames(job) / max(total, 1)))
    started = _date(job.get("StartedDateTimeString"))
    finished = _date(job.get("CompletedDateTimeString"))
    if status is None:
        return "Terminés", "Introuvable dans Deadline", "#8a8a8a", 0, "job supprimé de Deadline ?"
    if status == "Failed" or (status == "Active" and int(job.get("FailedChunks", 0) or 0)):
        return "Terminés", "Erreur", "#d0603f", percent, _last_error(job)
    if status == "Completed":
        took = _duration(finished - started) if started and finished else ""
        return "Terminés", "Terminé", "#4caf61", 100, took
    if status == "Suspended":
        return "En attente", "Suspendu", "#8a8a8a", percent, ""
    if int(job.get("RenderingChunks", 0) or 0):
        elapsed = now - started if started else None
        eta = ""
        if elapsed and 0 < percent < 100:
            eta = f"  ·  reste ~{_duration(elapsed * (100 - percent) / percent)}"
        return "En cours", "Calcul", "#4f86c6", percent, (_duration(elapsed) if elapsed else "") + eta
    if job.get("scheduled") and datetime.datetime.fromisoformat(job["scheduled"]) > now:
        return "Ce soir", f"Programmé {job['scheduled'][11:16]}", "#b08cd8", 0, _waiting(job)
    if status == "Pending":
        return "En attente", "Attend un autre job", "#b08cd8", 0, _waiting(job)
    return "En attente", "En file", "#8a8a8a", 0, _waiting(job)


def _waiting(job):
    deps = job.get("deps") or []
    return f"après {len(deps)} job(s)" if deps else ""


def _date(text):
    if not text or text.startswith("01/01/0001"):
        return None
    try:
        return datetime.datetime.strptime(text, "%m/%d/%Y %H:%M:%S")
    except ValueError:
        return None


def _duration(delta):
    minutes = int(delta.total_seconds()) // 60
    return f"{minutes // 60} h {minutes % 60:02d}" if minutes >= 60 else f"{minutes} min"


def _last_error(job):
    try:
        with open(job["log"], encoding="utf-8", errors="replace") as f:
            lines = [l.strip() for l in f if l.strip()]
        errors = [l for l in lines if "ERREUR" in l or "Error" in l or "error" in l]
        return (errors or lines or ["voir le log"])[-1][:160]
    except OSError:
        return "voir le log dans Deadline Monitor"


def start_now(job):
    """Drop the 'tonight' schedule and let the job start as soon as the worker is free (dependencies still apply)."""
    run("-SetJobSetting", job["id"], "ScheduledType", "None")
    if not job.get("deps"):
        run("-ReleasePendingJob", job["id"])
    job["scheduled"] = None
    return job


def action(verb, job_id):
    """suspend / resume / requeue a job."""
    return run({"suspend": "-SuspendJob", "resume": "-ResumeJob", "requeue": "-RequeueJob"}[verb], job_id)


# ---------------------------------------------------------------- node right-click menu

def submit_now(node):
    submit_from_menu(node, tonight=False)


def submit_tonight(node):
    submit_from_menu(node, tonight=True)


def submit_from_menu(node, tonight):
    if not can_submit(node):
        return
    if hou.hipFile.isNewFile():
        hou.ui.displayMessage("Enregistre d'abord la scène : Deadline calcule le fichier .hip tel qu'il est sur le disque.",
                              severity=hou.severityType.Warning)
        return
    if hou.hipFile.hasUnsavedChanges():
        if hou.ui.displayMessage("La scène a des changements non enregistrés. Deadline calcule le fichier sur le disque.",
                                 buttons=("Enregistrer et envoyer", "Annuler"), default_choice=0, close_choice=1) != 0:
            return
        hou.hipFile.save()
    try:
        entry = submit(node, tonight=tonight)
    except Exception as error:
        hou.ui.displayMessage(f"Envoi à Deadline impossible : {error}", severity=hou.severityType.Error)
        return
    when = f"ce soir à {entry['scheduled'][11:16]}" if entry["scheduled"] else "dès que le worker est libre"
    deps = f"\nIl attendra la fin de {len(entry['deps'])} job(s) en amont." if entry["deps"] else ""
    choice = hou.ui.displayMessage(
        f"« {entry['name']} » est envoyé à Deadline, calcul {when}.{deps}\n\n"
        "Le job lira la scène telle qu'elle est enregistrée. Pour continuer à travailler sans la modifier, "
        "passe sur une nouvelle version.", buttons=("Save Up maintenant", "Rester sur cette version"),
        default_choice=0, close_choice=1)
    if choice == 0:
        import saveUp
        saveUp.saveUp()
