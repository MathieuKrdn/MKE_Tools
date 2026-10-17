"""Daily flipbook: viewport flipbook -> mp4 named like 261015_WHOOP_ACT2_car_cubePropagation_v012_MK.mp4.

dailyFlipbook() opens the dialog. Naming and encoding work without UI (hython-testable).
"""
import datetime
import os
import shutil
import subprocess
import sys
import tempfile

import hou
from hutil.Qt import QtCore, QtWidgets

import mke_project
import projectSetup as ui


# ---------------------------------------------------------------- naming

def scene_version():
    """'025' from ..._v025.hipnc (3 digits minimum), '001' for an unsaved scene."""
    match = mke_project.VERSION_RE.search(os.path.splitext(os.path.basename(hou.hipFile.path()))[0])
    return f"{int(match.group(1)):03d}" if match else "001"


def daily_name(project, context, description, version, initials, date=None, ext=".mp4"):
    date = date or datetime.date.today()
    parts = [date.strftime("%y%m%d"), mke_project.sanitize_name(project).upper(), mke_project.sanitize_name(context).upper(),
             mke_project.sanitize_name(description), f"v{version}", mke_project.sanitize_name(initials).upper()]
    return "_".join(p for p in parts if p and p != "v") + ext


def default_context(info):
    """SEQ010_SH0010 inside a shot scene, else what was used last on this project (ex: ACT2)."""
    shot = None if hou.hipFile.isNewFile() else mke_project.shot_for_path(info, hou.hipFile.path())
    return shot.replace("/", "_") if shot else info.get("daily_context", "")


# ---------------------------------------------------------------- encoding

def encoder():
    """System ffmpeg with x264 when installed, else the hffmpeg shipped with Houdini (OpenH264)."""
    system = shutil.which("ffmpeg")
    if system:
        return [system], ["-c:v", "libx264", "-crf", "18", "-preset", "medium"]
    bundled = os.path.join(hou.getenv("HFS"), "bin", "hffmpeg.exe" if sys.platform == "win32" else "hffmpeg")
    return [bundled], ["-c:v", "libopenh264", "-b:v", "20M"]


def encode(pattern, start_frame, fps, out_path):
    """pattern uses ffmpeg numbering (frame.%04d.jpg). Returns out_path."""
    exe, codec = encoder()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    cmd = exe + ["-y", "-hide_banner", "-loglevel", "error", "-framerate", f"{fps:g}", "-start_number", str(start_frame),
                 "-i", pattern, *codec, "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2:out_range=tv,format=yuv420p",
                 "-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                 "-r", f"{fps:g}", out_path]
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    result = subprocess.run(cmd, capture_output=True, text=True, creationflags=flags)
    if result.returncode != 0 or not os.path.isfile(out_path):
        raise RuntimeError(f"Encodage échoué : {result.stderr.strip()[-400:]}")
    return out_path


def flipbook(out_path, start, end, resolution, fps):
    """Viewport flipbook to a temp jpg sequence, then encode. Needs Houdini's UI."""
    viewer = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
    if viewer is None:
        raise RuntimeError("Aucun viewport (Scene View) ouvert.")
    tmp = tempfile.mkdtemp(prefix="mke_daily_")
    try:
        settings = viewer.flipbookSettings().stash()
        settings.frameRange((start, end))
        settings.output(os.path.join(tmp, "frame.$F4.jpg").replace("\\", "/"))
        settings.outputToMPlay(False)
        settings.useResolution(True)
        settings.resolution(tuple(resolution))
        viewer.flipbook(viewer.curViewport(), settings)
        return encode(os.path.join(tmp, "frame.%04d.jpg"), start, fps, out_path)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- dialog

def dailyFlipbook():
    info = mke_project.on_scene_load() if not hou.hipFile.isNewFile() else None
    info = info or mke_project.find_project(hou.getenv("JOB") or os.getcwd())
    if not info:
        hou.ui.displayMessage("Ouvre d'abord une scène d'un projet (dashboard Projects).", severity=hou.severityType.Warning)
        return
    dialog = DailyDialog(info, hou.qt.mainWindow())
    dialog.show()
    global _dialog
    _dialog = dialog
    return dialog


_dialog = None


class DailyDialog(QtWidgets.QDialog):
    def __init__(self, info, parent=None):
        super().__init__(parent)
        self.info = info
        self.setWindowTitle("Daily flipbook")
        self.setStyleSheet(ui.STYLE)
        self.setMinimumWidth(560)
        start, end = hou.playbar.playbackRange()
        self.context = QtWidgets.QLineEdit(default_context(info))
        self.context.setPlaceholderText("ex : ACT2, SEQ010_SH0010")
        self.description = QtWidgets.QLineEdit(info.get("daily_description", ""))
        self.description.setPlaceholderText("ex : car_cubePropagation")
        self.version = QtWidgets.QLineEdit(scene_version())
        self.version.setFixedWidth(70)
        self.initials = QtWidgets.QLineEdit(mke_project.get_pref("initials", mke_project.user_trigram()[:2].upper()))
        self.initials.setFixedWidth(70)
        self.start = ui._compact_spin(-100000, 100000, int(start))
        self.end = ui._compact_spin(-100000, 100000, int(end))
        self.scale = QtWidgets.QComboBox()
        w, h = info["resolution"]
        for pct in (100, 75, 50, 25):
            self.scale.addItem(f"{pct} %  ({w * pct // 100}x{h * pct // 100})", pct)
        self.scale.setCurrentIndex(2 if w >= 3000 else 0)
        self.open_after = QtWidgets.QCheckBox("Lire la vidéo à la fin")
        self.open_after.setChecked(True)
        self.preview = ui._label("", "hint")
        self.preview.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.error = ui._label("", "warning")
        run = QtWidgets.QPushButton("Lancer le flipbook")
        run.setObjectName("primary")
        run.setDefault(True)
        run.clicked.connect(self._run)
        self.run_button = run
        cancel = QtWidgets.QPushButton("Annuler")
        cancel.clicked.connect(self.reject)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(ui._card("Nom", [
            ("Contexte", self.context), ("Description", self.description),
            ("Version", ui._row(self.version, "Initiales", self.initials, None)),
        ]))
        layout.addWidget(ui._card("Image", [
            ("Frames", ui._row(self.start, "→", self.end, None)),
            ("Taille", ui._row(self.scale, None)),
        ]))
        layout.addWidget(self.preview)
        layout.addWidget(self.error)
        layout.addLayout(ui._row(self.open_after, None, cancel, run))
        for widget in (self.context, self.description, self.version, self.initials):
            widget.textChanged.connect(self._refresh)
        for widget in (self.start, self.end):
            widget.valueChanged.connect(self._refresh)
        self._refresh()

    def out_path(self):
        name = daily_name(self.info["name"], self.context.text(), self.description.text(),
                          self.version.text().strip(), self.initials.text())
        shot = self.context.text().replace("_", "/") if self.context.text().replace("_", "/") in self.info["shots"] else None
        return f"{mke_project.dailies_dir(self.info, shot)}/{name}"

    def _refresh(self, *_):
        path = self.out_path()
        folder = os.path.dirname(path)
        short = folder if len(folder) < 60 else ".../" + "/".join(folder.split("/")[-3:])
        self.preview.setText(f"{os.path.basename(path)}\ndans {short}")
        self.preview.setToolTip(path)
        errors = []
        if not self.description.text().strip():
            errors.append("Ajoute une description.")
        if self.end.value() < self.start.value():
            errors.append("La dernière frame doit être après la première.")
        if os.path.exists(path):
            errors.append("Ce fichier existe déjà : change la description ou la version.")
        self.error.setText("\n".join(errors))
        self.error.setVisible(bool(errors))
        self.run_button.setEnabled(not errors)

    def _run(self):
        path = self.out_path()
        self.info["daily_context"] = self.context.text().strip()
        self.info["daily_description"] = self.description.text().strip()
        mke_project.write_project(self.info)
        mke_project.set_pref("initials", self.initials.text().strip().upper())
        pct = self.scale.currentData()
        res = [max(2, v * pct // 100) for v in self.info["resolution"]]
        self.hide()
        try:
            with hou.InterruptableOperation("Daily flipbook", open_interrupt_dialog=True):
                flipbook(path, self.start.value(), self.end.value(), res, self.info["fps"])
        except Exception as error:
            self.show()
            hou.ui.displayMessage(f"Le flipbook a échoué : {error}", severity=hou.severityType.Error)
            return
        self.accept()
        hou.ui.setStatusMessage(f"Daily : {os.path.basename(path)}")
        if self.open_after.isChecked():
            os.startfile(path)

