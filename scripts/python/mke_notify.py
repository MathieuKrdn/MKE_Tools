"""Discord notifications for MKE nodes (File Cache Discord).

The webhook URL is personal: it is read from $MKE_DISCORD_WEBHOOK or from mke_projects_prefs.json,
where configure() stores what the user pastes. It never lives in a scene or in this package.
"""
import datetime
import json
import os
import socket
import threading
import time
import urllib.request

import hou

import mke_project

NODE_TYPE_PREFIX = "MKE::filecache_discord"
START_KEY = "mke_cache_start"


def webhook_url():
    return os.environ.get("MKE_DISCORD_WEBHOOK") or mke_project.get_pref("discord_webhook", "")


def send(content, embed=None, url=None, wait=False):
    """POST to the Discord webhook. In Houdini's UI it runs in a thread so the session never waits on the network."""
    url = url or webhook_url()
    if not url:
        return False
    payload = {"username": "Houdini", "content": content}
    if embed:
        payload["embeds"] = [embed]
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json", "User-Agent": "MKE_Tools"})

    def post():
        try:
            urllib.request.urlopen(request, timeout=10).close()
            return True
        except Exception as error:
            print(f"[MKE Discord] envoi impossible : {error}")
            return False

    if wait or not hou.isUIAvailable():  # farm / hython: the process may exit right after, so send now
        return post()
    threading.Thread(target=post, daemon=True).start()
    return True


# ---------------------------------------------------------------- File Cache hooks

def _cache_node(node):
    """Pre/post-render scripts run on the File Cache's internal ROP: walk up to our node."""
    while node is not None and not node.type().name().startswith(NODE_TYPE_PREFIX):
        node = node.parent()
    return node


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


def cache_done(node=None):
    node = _cache_node(node or hou.pwd())
    if node is None or not node.evalParm("discord_notify"):
        return
    started = node.cachedUserData(START_KEY)
    duration = str(datetime.timedelta(seconds=int(time.time() - started))) if started else "?"
    output_parm = node.parm("sopoutput") or node.parm("file")  # sopoutput = the path actually written (any file method)
    output = output_parm.evalAsString() if output_parm else ""
    folder = os.path.dirname(output)
    hip = hou.hipFile.basename()
    note = node.evalParm("discord_message").strip()
    fields = [
        {"name": "Scène", "value": hip, "inline": True},
        {"name": "Durée", "value": duration, "inline": True},
        {"name": "Frames", "value": f"{int(node.evalParm('f1'))}-{int(node.evalParm('f2'))}", "inline": True},
        {"name": "Taille", "value": _human(_size(folder)) if os.path.isdir(folder) else "?", "inline": True},
        {"name": "Machine", "value": socket.gethostname(), "inline": True},
        {"name": "Dossier", "value": f"`{folder}`", "inline": False},
    ]
    embed = {"title": f"Cache terminé : {node.name()}", "description": note or node.path(),
             "color": 0x3D9A50, "fields": fields, "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    send(f"✅ **{node.name()}** est terminé ({duration})", embed)


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
