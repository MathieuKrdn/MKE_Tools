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


def mention_id():
    """Discord user ID to @mention, or "" when mentions are off (prefs discord_mention + discord_user_id)."""
    user = str(mke_project.get_pref("discord_user_id", "")).strip()
    return user if user.isdigit() and mke_project.get_pref("discord_mention", True) else ""


DISCORD_FILE_LIMIT = 10 * 1024 * 1024  # webhook upload limit on a server without boosts


def send(content, embed=None, url=None, wait=False, attachment=None, mention=None):
    """POST to the Discord webhook, optionally with a file (skipped above Discord's upload limit).
    In Houdini's UI it runs in a thread so the session never waits on the network."""
    url = url or webhook_url()
    if not url:
        return False
    mention = mention_id() if mention is None else mention
    payload = {"username": "Houdini", "content": f"<@{mention}> {content}" if mention else content,
               "allowed_mentions": {"users": [mention] if mention else []}}
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
            print(f"[MKE Discord] could not send: {error}")
            return False

    if wait or not hou.isUIAvailable():  # farm / hython: the process may exit right after, so send now
        return post()
    threading.Thread(target=post, daemon=True).start()
    return True


def _field(name, value, inline=True):
    return {"name": name, "value": str(value) or "-", "inline": inline}


def context_fields():
    """Project (when the scene belongs to one) and Scene, shared by every notification."""
    hip = hou.hipFile.path()
    info = None if hou.hipFile.isNewFile() else mke_project.find_project(os.path.dirname(hip))
    fields = [_field("Project", f"{info['name']}  ·  {info['type']}")] if info else []
    return fields + [_field("Scene", hou.hipFile.basename())]


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
    folder.addParmTemplate(hou.ToggleParmTemplate("discord_notify", "Notify on Discord", default_value=True,
                                                  help="Message on your Discord server when the cache finishes."))
    folder.addParmTemplate(hou.StringParmTemplate("discord_message", "Message", 1, default_value=("",),
                                                  help="Text added to the notification (optional)."))
    folder.addParmTemplate(hou.ButtonParmTemplate(
        "discord_test", "Send a test", script_callback_language=hou.scriptLanguage.Python,
        script_callback="import mke_notify; mke_notify.send('Test from ' + kwargs['node'].path(), wait=True)"))
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
    hou.ui.displayMessage(f"{len(changed)} File Caches set up for Discord ({len(nodes) - len(changed)} already were).")
    return changed


def _size(path):
    total = 0
    for folder, _, files in os.walk(path):
        total += sum(os.path.getsize(os.path.join(folder, f)) for f in files)
    return total


def _human(size):
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def cache_started(node=None):
    node = _cache_node(node or hou.pwd())
    if node is not None:
        node.setCachedUserData(START_KEY, time.time())


FRAME_RE = re.compile(r"([._])(-?\d+)(\.[^./\\]+(?:\.sc|\.gz)?)$")  # name.0012.bgeo.sc -> name.####.bgeo.sc


def cache_done(node=None):
    node = _cache_node(node or hou.pwd())
    if node is None:
        return
    try:
        import mke_cachestate
        mke_cachestate.record(node)  # fingerprint for outdated-cache detection, Discord or not
    except Exception as error:
        print(f"[MKE] cache fingerprint not saved: {error}")
    if not node.evalParm("discord_notify"):
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
        _field("Files", f"`{files}`"),
        _field("Frames", f"{int(node.evalParm('f1'))}-{int(node.evalParm('f2'))}"),
        _field("Duration", duration),
        _field("Size", _human(_size(folder)) if os.path.isdir(folder) else "?"),
        _field("Machine", socket.gethostname()),
        _field("Folder", f"`{folder}`", inline=False),
    ]
    note = node.evalParm("discord_message").strip()
    send(f"✅ Cache **{cache}** finished ({duration})", _embed(f"Cache finished: {node.name()}", note or node.path(), fields))


def daily_done(video, start, end, fps, seconds, note=""):
    """Daily flipbook finished: same context as caches, plus the video itself when it fits Discord's limit."""
    duration = str(datetime.timedelta(seconds=int(seconds)))
    size = os.path.getsize(video) if os.path.isfile(video) else 0
    fields = context_fields() + [
        _field("File", f"`{os.path.basename(video)}`", inline=False),
        _field("Frames", f"{start}-{end}"),
        _field("Video length", f"{(end - start + 1) / fps:.1f} s at {fps:g} fps"),
        _field("Render time", duration),
        _field("Size", _human(size) + ("" if size <= DISCORD_FILE_LIMIT else "  (too large to attach)")),
        _field("Machine", socket.gethostname()),
        _field("Folder", f"`{os.path.dirname(video)}`", inline=False),
    ]
    name = os.path.splitext(os.path.basename(video))[0]
    return send(f"🎬 Daily **{name}** ready ({duration})",
                _embed("Daily flipbook finished", note or name, fields, color=0x3D6EA8), attachment=video)


# ---------------------------------------------------------------- setup

def configure():
    """Small dialog where the user pastes his webhook URL and sends a test message."""
    from hutil.Qt import QtWidgets
    import projectSetup as ui

    dialog = QtWidgets.QDialog(hou.qt.mainWindow())
    dialog.setWindowTitle("Discord notifications")
    dialog.setStyleSheet(ui.STYLE)
    dialog.setMinimumWidth(560)
    url = QtWidgets.QLineEdit(mke_project.get_pref("discord_webhook", ""))
    url.setEchoMode(QtWidgets.QLineEdit.PasswordEchoOnEdit)
    url.setPlaceholderText("https://discord.com/api/webhooks/...")
    help_text = ui._label("On your Discord server: Channel settings > Integrations > Webhooks > New webhook > "
                          "Copy URL. Paste it here. It stays on this PC (Houdini prefs), never in scenes.", "hint")
    mention = QtWidgets.QCheckBox("@mention me")
    mention.setChecked(bool(mke_project.get_pref("discord_mention", True)))
    user = QtWidgets.QLineEdit(str(mke_project.get_pref("discord_user_id", "")))
    user.setPlaceholderText("Your Discord user ID (digits)")
    user.setToolTip("Discord > Settings > Advanced > Developer Mode, then right-click your name > Copy User ID.")
    status = ui._label("", "hint")
    test = QtWidgets.QPushButton("Send a test")
    save = QtWidgets.QPushButton("Save")
    save.setObjectName("primary")

    def user_id():
        text = user.text().strip()
        return text if mention.isChecked() and text.isdigit() else ""

    def do_test():
        ok = send("👋 Test from Houdini: cache notifications will arrive here.", url=url.text().strip(), wait=True,
                  mention=user_id())
        status.setText("Message sent, check your Discord channel." if ok else "Failed: check the webhook URL.")

    def do_save():
        if mention.isChecked() and not user.text().strip().isdigit():
            status.setText("The user ID must be digits only (or untick @mention me).")
            return
        mke_project.set_pref("discord_webhook", url.text().strip())
        mke_project.set_pref("discord_mention", mention.isChecked())
        mke_project.set_pref("discord_user_id", user.text().strip())
        dialog.accept()
        hou.ui.setStatusMessage("Discord webhook saved")

    test.clicked.connect(do_test)
    save.clicked.connect(do_save)
    layout = QtWidgets.QVBoxLayout(dialog)
    layout.addWidget(help_text)
    layout.addWidget(url)
    layout.addLayout(ui._row(mention, user))
    layout.addWidget(status)
    layout.addLayout(ui._row(test, None, save))
    dialog.show()
    global _dialog
    _dialog = dialog
    return dialog


_dialog = None
