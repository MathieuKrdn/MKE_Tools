"""Discord notifications: Houdini's own File Cache (via scripts/sop/filecache-2.0_OnCreated.py) and Daily flipbooks.

The webhook URL is personal: it is read from $MKE_DISCORD_WEBHOOK or from mke_projects_prefs.json,
where configure() stores what the user pastes. It never lives in a scene or in this package.
"""
import datetime
import json
import os
import re
import socket
import threading
import time
import urllib.request
import uuid

import hou

import mke_project

START_KEY = "mke_cache_start"
PRE_SCRIPT = "import mke_notify; mke_notify.cache_started(hou.pwd())"
POST_SCRIPT = "import mke_notify; mke_notify.cache_done(hou.pwd())"


def webhook_url():
    return os.environ.get("MKE_DISCORD_WEBHOOK") or mke_project.get_pref("discord_webhook", "")


DISCORD_FILE_LIMIT = 10 * 1024 * 1024  # webhook upload limit on a server without boosts


def send(content, embed=None, url=None, wait=False, attachment=None):
    """POST to the Discord webhook, optionally with a file (skipped above Discord's upload limit).
    In Houdini's UI it runs in a thread so the session never waits on the network."""
    url = url or webhook_url()
    if not url:
        return False
    payload = {"username": "Houdini", "content": content}
    if embed:
        payload["embeds"] = [embed]
    if attachment and os.path.isfile(attachment) and os.path.getsize(attachment) <= DISCORD_FILE_LIMIT:
        boundary = uuid.uuid4().hex
        name = os.path.basename(attachment)
        with open(attachment, "rb") as f:
            data = f.read()
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"payload_json\"\r\n"
                f"Content-Type: application/json\r\n\r\n{json.dumps(payload)}\r\n"
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"files[0]\"; filename=\"{name}\"\r\n"
                f"Content-Type: application/octet-stream\r\n\r\n").encode("utf-8") + data + f"\r\n--{boundary}--\r\n".encode()
        content_type = f"multipart/form-data; boundary={boundary}"
    else:
        body, content_type = json.dumps(payload).encode("utf-8"), "application/json"
    request = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": content_type, "User-Agent": "MKE_Tools"})

    def post():
        try:
            urllib.request.urlopen(request, timeout=30).close()
            return True
        except Exception as error:
            print(f"[MKE Discord] envoi impossible : {error}")
            return False

    if wait or not hou.isUIAvailable():  # farm / hython: the process may exit right after, so send now
        return post()
    threading.Thread(target=post, daemon=True).start()
    return True


def _field(name, value, inline=True):
    return {"name": name, "value": str(value) or "-", "inline": inline}


def context_fields():
    """Projet (when the scene belongs to one) and Scène, shared by every notification."""
    hip = hou.hipFile.path()
    info = None if hou.hipFile.isNewFile() else mke_project.find_project(os.path.dirname(hip))
    fields = [_field("Projet", f"{info['name']}  ·  {info['type']}")] if info else []
    return fields + [_field("Scène", hou.hipFile.basename())]


def _embed(title, description, fields, color=0x3D9A50):
    return {"title": title, "description": description, "color": color, "fields": fields,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()}


# ---------------------------------------------------------------- File Cache hooks

def _cache_node(node):
    """Pre/post-render scripts run on the File Cache's internal ROP: walk up to the node carrying the Discord toggle."""
    while node is not None and node.parm("discord_notify") is None:
        node = node.parent()
    return node


def setup_filecache(node):
    """Turn a normal File Cache into a notifying one: a 'Discord' tab of spare parms + pre/post-render scripts.
    Scripts the user already wrote are kept: we only fill empty slots. Returns True if the node was changed."""
    if node.parm("discord_notify") is not None:
        return False
    group = node.parmTemplateGroup()
    folder = hou.FolderParmTemplate("discord", "Discord", folder_type=hou.folderType.Tabs)
    folder.addParmTemplate(hou.ToggleParmTemplate("discord_notify", "Notifier sur Discord", default_value=True,
                                                  help="Message sur ton serveur Discord à la fin du cache."))
    folder.addParmTemplate(hou.StringParmTemplate("discord_message", "Message", 1, default_value=("",),
                                                  help="Texte ajouté à la notification (optionnel)."))
    folder.addParmTemplate(hou.ButtonParmTemplate(
        "discord_test", "Envoyer un test", script_callback_language=hou.scriptLanguage.Python,
        script_callback="import mke_notify; mke_notify.send('Test depuis ' + kwargs['node'].path(), wait=True)"))
    group.append(folder)
    node.setParmTemplateGroup(group)
    for toggle, script, lang, code in (("tprerender", "prerender", "lprerender", PRE_SCRIPT),
                                       ("tpostrender", "postrender", "lpostrender", POST_SCRIPT)):
        if node.parm(script) is None or node.parm(script).eval().strip():
            continue  # not a File Cache, or the user already has a script there
        node.parm(script).set(code)
        node.parm(lang).set("python")
        node.parm(toggle).set(True)
    return True


def is_filecache(node):
    return node.type().nameComponents()[2] == "filecache"


def setup_scene_filecaches():
    """Menu action: add Discord notifications to every File Cache already in the scene."""
    nodes = [n for n in hou.node("/").allSubChildren() if is_filecache(n)]
    changed = [n for n in nodes if setup_filecache(n)]
    hou.ui.displayMessage(f"{len(changed)} File Cache configurés pour Discord ({len(nodes) - len(changed)} l'étaient déjà).")
    return changed


def _size(path):
    total = 0
    for folder, _, files in os.walk(path):
        total += sum(os.path.getsize(os.path.join(folder, f)) for f in files)
    return total


def _human(size):
    for unit in ("o", "Ko", "Mo", "Go"):
        if size < 1024:
            return f"{size:.0f} {unit}"
        size /= 1024
    return f"{size:.1f} To"


def cache_started(node=None):
    node = _cache_node(node or hou.pwd())
    if node is not None:
        node.setCachedUserData(START_KEY, time.time())


FRAME_RE = re.compile(r"([._])(-?\d+)(\.[^./\\]+(?:\.sc|\.gz)?)$")  # name.0012.bgeo.sc -> name.####.bgeo.sc


def cache_done(node=None):
    node = _cache_node(node or hou.pwd())
    if node is None or not node.evalParm("discord_notify"):
        return
    started = node.cachedUserData(START_KEY)
    duration = str(datetime.timedelta(seconds=int(time.time() - started))) if started else "?"
    output_parm = node.parm("sopoutput") or node.parm("file")  # sopoutput = the path actually written (any file method)
    output = output_parm.evalAsString() if output_parm else ""
    folder = os.path.dirname(output)
    cache = node.evalParm("basename") if node.parm("basename") else node.name()
    if node.parm("enableversion") and node.evalParm("enableversion"):
        cache += f"  v{node.evalParm('version')}"
    files = FRAME_RE.sub(lambda m: f"{m.group(1)}{'#' * len(m.group(2))}{m.group(3)}", os.path.basename(output))
    fields = context_fields() + [
        _field("Cache", cache),
        _field("Fichiers", f"`{files}`"),
        _field("Frames", f"{int(node.evalParm('f1'))}-{int(node.evalParm('f2'))}"),
        _field("Durée", duration),
        _field("Taille", _human(_size(folder)) if os.path.isdir(folder) else "?"),
        _field("Machine", socket.gethostname()),
        _field("Dossier", f"`{folder}`", inline=False),
    ]
    note = node.evalParm("discord_message").strip()
    send(f"✅ Cache **{cache}** terminé ({duration})", _embed(f"Cache terminé : {node.name()}", note or node.path(), fields))


def daily_done(video, start, end, fps, seconds, note=""):
    """Daily flipbook finished: same context as caches, plus the video itself when it fits Discord's limit."""
    duration = str(datetime.timedelta(seconds=int(seconds)))
    size = os.path.getsize(video) if os.path.isfile(video) else 0
    fields = context_fields() + [
        _field("Fichier", f"`{os.path.basename(video)}`", inline=False),
        _field("Frames", f"{start}-{end}"),
        _field("Durée vidéo", f"{(end - start + 1) / fps:.1f} s à {fps:g} fps"),
        _field("Temps de rendu", duration),
        _field("Taille", _human(size) + ("" if size <= DISCORD_FILE_LIMIT else "  (trop lourde pour être jointe)")),
        _field("Machine", socket.gethostname()),
        _field("Dossier", f"`{os.path.dirname(video)}`", inline=False),
    ]
    name = os.path.splitext(os.path.basename(video))[0]
    return send(f"🎬 Daily **{name}** prêt ({duration})",
                _embed("Daily flipbook terminé", note or name, fields, color=0x3D6EA8), attachment=video)


# ---------------------------------------------------------------- setup

def configure():
    """Small dialog where the user pastes his webhook URL and sends a test message."""
    from hutil.Qt import QtWidgets
    import projectSetup as ui

    dialog = QtWidgets.QDialog(hou.qt.mainWindow())
    dialog.setWindowTitle("Notifications Discord")
    dialog.setStyleSheet(ui.STYLE)
    dialog.setMinimumWidth(560)
    url = QtWidgets.QLineEdit(mke_project.get_pref("discord_webhook", ""))
    url.setEchoMode(QtWidgets.QLineEdit.PasswordEchoOnEdit)
    url.setPlaceholderText("https://discord.com/api/webhooks/...")
    help_text = ui._label("Sur ton serveur Discord : Paramètres du salon > Intégrations > Webhooks > Nouveau webhook > "
                          "Copier l'URL. Colle-la ici. Elle reste sur ce PC (préférences Houdini), jamais dans les scènes.", "hint")
    status = ui._label("", "hint")
    test = QtWidgets.QPushButton("Envoyer un test")
    save = QtWidgets.QPushButton("Enregistrer")
    save.setObjectName("primary")

    def do_test():
        ok = send("👋 Test depuis Houdini : les notifications de cache arriveront ici.", url=url.text().strip(), wait=True)
        status.setText("Message envoyé, regarde ton salon Discord." if ok else "Échec : vérifie l'URL du webhook.")

    def do_save():
        mke_project.set_pref("discord_webhook", url.text().strip())
        dialog.accept()
        hou.ui.setStatusMessage("Webhook Discord enregistré")

    test.clicked.connect(do_test)
    save.clicked.connect(do_save)
    layout = QtWidgets.QVBoxLayout(dialog)
    layout.addWidget(help_text)
    layout.addWidget(url)
    layout.addWidget(status)
    layout.addLayout(ui._row(test, None, save))
    dialog.show()
    global _dialog
    _dialog = dialog
    return dialog


_dialog = None
