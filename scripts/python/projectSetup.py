"""Projects: a dashboard to reach projects, shots/assets and scene versions. Logic lives in mke_project.

projects()          -> the dashboard (also opened at Houdini startup)
CreateProjectDialog -> "+ Nouveau projet"
EntitiesDialog      -> "+ Plan / asset"
"""
import os
import subprocess

import hou
from hutil.Qt import QtCore, QtGui, QtWidgets

import mke_project

OTHER = "Autre"
TYPE_STYLE = "padding: 6px 12px;"
TYPE_CHECKED_STYLE = TYPE_STYLE + "background: #3d6ea8; color: white; border: 1px solid #5b8cc8;"
STYLE = """
QLabel#title { font-size: 16pt; font-weight: bold; }
QLabel#hint { color: #8a8a8a; }
QLabel#warning { color: #e0a030; }
QPushButton#primary { padding: 6px 18px; font-weight: bold; }
QListWidget#projects::item { padding: 6px 4px; }
"""


def _label(text, name=None):
    label = QtWidgets.QLabel(text)
    label.setWordWrap(True)
    if name:
        label.setObjectName(name)
    return label


def _section(title):
    label = QtWidgets.QLabel(title.upper())
    label.setStyleSheet("color: #8a8a8a; font-size: 8pt; font-weight: bold; margin-top: 6px;")
    return label


def _spin(minimum, maximum, value, double=False):
    spin = QtWidgets.QDoubleSpinBox() if double else QtWidgets.QSpinBox()
    spin.setRange(minimum, maximum)
    spin.setValue(value)
    if double:
        spin.setDecimals(3)
    return spin


def _path_field(line_edit, title, parent):
    row = QtWidgets.QHBoxLayout()
    button = QtWidgets.QToolButton()
    button.setText("...")

    def browse():
        path = QtWidgets.QFileDialog.getExistingDirectory(parent, title, line_edit.text())
        if path:
            line_edit.setText(path)
    button.clicked.connect(browse)
    row.addWidget(line_edit)
    row.addWidget(button)
    return row


def _column(title, widget, *buttons):
    column = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(column)
    layout.setContentsMargins(0, 0, 0, 0)
    if title:
        layout.addWidget(_section(title))
    layout.addWidget(widget, 1)
    if buttons:
        row = QtWidgets.QHBoxLayout()
        for button in buttons:
            if button is None:
                row.addStretch()
            else:
                row.addWidget(button)
        layout.addLayout(row)
    return column


try:  # Qt Multimedia ships with Houdini 22 (PySide6); without it the preview falls back to the external player
    from PySide6 import QtMultimedia, QtMultimediaWidgets
    from PySide6.QtCore import QLoggingCategory
except ImportError:
    QtMultimedia = None


class VideoPlayer(QtWidgets.QWidget):
    """Inline preview: loops muted as soon as a video is loaded, click or space to pause."""

    def __init__(self, parent=None):
        super().__init__(parent)
        QLoggingCategory.setFilterRules("qt.multimedia*=false")  # keep FFmpeg stream dumps out of the console
        self.video = QtMultimediaWidgets.QVideoWidget()
        self.video.setStyleSheet("background: black;")
        self.player = QtMultimedia.QMediaPlayer(self)
        self.audio = QtMultimedia.QAudioOutput(self)
        self.audio.setMuted(True)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.player.setLoops(QtMultimedia.QMediaPlayer.Infinite)

        self.play_button = QtWidgets.QToolButton()
        self.play_button.clicked.connect(self.toggle)
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider.sliderMoved.connect(self.player.setPosition)
        self.time = QtWidgets.QLabel("0:00 / 0:00")
        self.time.setStyleSheet("color: #8a8a8a;")
        self.mute_button = QtWidgets.QToolButton()
        self.mute_button.setText("Son")
        self.mute_button.setCheckable(True)
        self.mute_button.toggled.connect(lambda on: self.audio.setMuted(not on))

        controls = QtWidgets.QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.addWidget(self.play_button)
        controls.addWidget(self.slider, 1)
        controls.addWidget(self.time)
        controls.addWidget(self.mute_button)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.video, 1)
        layout.addLayout(controls)

        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(lambda d: self.slider.setRange(0, d))
        self.player.playbackStateChanged.connect(self._on_state)
        self._on_state()

    def load(self, path):
        self.player.setSource(QtCore.QUrl.fromLocalFile(path))
        self.player.play()

    def stop(self):
        self.player.stop()
        self.player.setSource(QtCore.QUrl())

    def toggle(self):
        if self.player.playbackState() == QtMultimedia.QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def mousePressEvent(self, event):
        self.toggle()

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Space:
            self.toggle()
        else:
            super().keyPressEvent(event)

    def _on_state(self, *_):
        playing = self.player.playbackState() == QtMultimedia.QMediaPlayer.PlayingState
        self.play_button.setText("Pause" if playing else "Lecture")

    def _on_position(self, position):
        if not self.slider.isSliderDown():
            self.slider.setValue(position)
        fmt = lambda ms: f"{ms // 60000}:{ms // 1000 % 60:02d}"
        self.time.setText(f"{fmt(position)} / {fmt(self.player.duration())}")


def _confirm_discard():
    return not hou.hipFile.hasUnsavedChanges() or hou.ui.displayMessage(
        "La scène ouverte a des changements non sauvegardés.",
        buttons=("Continuer", "Annuler"), default_choice=1, close_choice=1) == 0


def current_project():
    job = hou.getenv("JOB")
    return mke_project.find_project(job) if job and os.path.isdir(job) else None


# ==================================================================== dashboard

class ProjectsDashboard(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Projects")
        self.setStyleSheet(STYLE)
        self.resize(1100, 640)

        title = _label("Projects", "title")
        self.active = _label("", "hint")
        new_project = QtWidgets.QPushButton("+ Nouveau projet")
        new_project.clicked.connect(self._new_project)
        header = QtWidgets.QHBoxLayout()
        header.addWidget(title)
        header.addSpacing(12)
        header.addWidget(self.active, 1)
        header.addWidget(new_project)

        # 1. projects
        self.project_list = QtWidgets.QListWidget()
        self.project_list.setObjectName("projects")
        self.project_list.setTextElideMode(QtCore.Qt.ElideMiddle)
        self.project_list.currentItemChanged.connect(lambda *_: self._refresh_entities())
        self.empty_projects = _label("Aucun projet récent.\nCrée-en un avec « + Nouveau projet » ou ouvre un dossier avec « Parcourir ».", "hint")
        browse = QtWidgets.QPushButton("Parcourir...")
        browse.clicked.connect(self._browse)
        self.settings_button = QtWidgets.QPushButton("Réglages")
        self.settings_button.setToolTip("Lire et modifier fps, frames, résolution, dossiers...")
        self.settings_button.clicked.connect(self._edit_settings)
        self.project_list.itemDoubleClicked.connect(lambda *_: self._edit_settings())
        self.project_summary = _label("", "hint")
        projects_box = QtWidgets.QWidget()
        box = QtWidgets.QVBoxLayout(projects_box)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self.project_list, 1)
        box.addWidget(self.empty_projects)
        box.addWidget(self.project_summary)

        # 2. shots and assets
        self.entity_tree = QtWidgets.QTreeWidget()
        self.entity_tree.setHeaderHidden(True)
        self.entity_tree.currentItemChanged.connect(lambda *_: self._refresh_versions())
        self.entity_button = QtWidgets.QPushButton("+ Plan / asset")
        self.entity_button.clicked.connect(self._edit_entities)

        # 3. versions
        self.version_list = QtWidgets.QTreeWidget()
        self.version_list.setHeaderLabels(["Version", "Date", "Auteur", "Commentaire"])
        self.version_list.setRootIsDecorated(False)
        self.version_list.setAlternatingRowColors(True)
        self.version_list.currentItemChanged.connect(lambda *_: self._refresh_thumbnail())
        self.version_list.itemDoubleClicked.connect(lambda *_: self._open_version())
        self.thumbnail = QtWidgets.QLabel()
        self.thumbnail.setAlignment(QtCore.Qt.AlignCenter)
        self.thumbnail.setFixedHeight(200)
        self.thumbnail.setStyleSheet("color: #8a8a8a; border: 1px solid rgba(255, 255, 255, 30); border-radius: 4px;")
        versions_box = QtWidgets.QWidget()
        box = QtWidgets.QVBoxLayout(versions_box)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self.version_list, 1)
        box.addWidget(self.thumbnail)
        self.new_scene_button = QtWidgets.QPushButton("Nouvelle scène ici")
        self.new_scene_button.setToolTip("Crée la v0001 de ce plan / asset dans son dossier, avec sa plage de frames")
        self.new_scene_button.clicked.connect(self._new_scene)
        self.open_button = QtWidgets.QPushButton("Ouvrir")
        self.open_button.setObjectName("primary")
        self.open_button.setDefault(True)
        self.open_button.clicked.connect(self._open_version)
        versions_page = _column("", versions_box, self.new_scene_button, None, self.open_button)

        # 4. media: blasts, renders, image sequences of the selected shot / asset
        self.media_list = QtWidgets.QTreeWidget()
        self.media_list.setHeaderLabels(["Nom", "Date", "Type", "Infos"])
        self.media_list.setRootIsDecorated(False)
        self.media_list.setAlternatingRowColors(True)
        self.media_list.setTextElideMode(QtCore.Qt.ElideMiddle)
        self.media_list.currentItemChanged.connect(lambda *_: self._refresh_media_preview())
        self.media_list.itemDoubleClicked.connect(lambda *_: self._play_media())
        self.media_preview = QtWidgets.QLabel()
        self.media_preview.setAlignment(QtCore.Qt.AlignCenter)
        self.media_preview.setStyleSheet(self.thumbnail.styleSheet())
        self.video_player = VideoPlayer() if QtMultimedia else None
        self.preview_stack = QtWidgets.QStackedWidget()
        self.preview_stack.setFixedHeight(280)
        self.preview_stack.addWidget(self.media_preview)
        if self.video_player:
            self.preview_stack.addWidget(self.video_player)
        media_box = QtWidgets.QWidget()
        box = QtWidgets.QVBoxLayout(media_box)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self.media_list, 1)
        box.addWidget(self.preview_stack)
        folder_button = QtWidgets.QPushButton("Ouvrir le dossier")
        folder_button.clicked.connect(self._open_media_folder)
        daily_button = QtWidgets.QPushButton("+ Daily flipbook")
        daily_button.setToolTip("Flipbook du viewport en mp4, nommé selon la convention du projet")
        daily_button.clicked.connect(self._daily)
        self.play_button = QtWidgets.QPushButton("Ouvrir dans le lecteur")
        self.play_button.setToolTip("Vidéos : ton lecteur vidéo. Séquences : MPlay.")
        self.play_button.setObjectName("primary")
        self.play_button.clicked.connect(self._play_media)
        media_page = _column("", media_box, folder_button, daily_button, None, self.play_button)

        self.content_tabs = QtWidgets.QTabWidget()
        self.content_tabs.addTab(versions_page, "Versions")
        self.content_tabs.addTab(media_page, "Médias")
        self.content_tabs.currentChanged.connect(lambda *_: self._refresh_media())

        splitter = QtWidgets.QSplitter()
        splitter.addWidget(_column("Projets", projects_box, browse, self.settings_button))
        splitter.addWidget(_column("Plans et assets", self.entity_tree, self.entity_button))
        splitter.addWidget(self.content_tabs)
        splitter.setSizes([260, 240, 600])

        self.startup_check = QtWidgets.QCheckBox("Ouvrir au démarrage de Houdini")
        self.startup_check.setChecked(mke_project.get_pref("open_at_startup", True))
        self.startup_check.toggled.connect(lambda on: mke_project.set_pref("open_at_startup", on))

        self.autosave_check = QtWidgets.QCheckBox(f"Sauvegarde auto toutes les {mke_project.AUTOSAVE_MINUTES} min")
        self.autosave_check.setToolTip("Copie dans autosave/<scène>_autosave.hip, sans toucher à ta scène ni à ses versions")
        self.autosave_check.setChecked(mke_project.get_pref("autosave", True))
        self.autosave_check.toggled.connect(mke_project.set_autosave)
        options = QtWidgets.QHBoxLayout()
        options.addWidget(self.startup_check)
        options.addSpacing(16)
        options.addWidget(self.autosave_check)
        options.addStretch()

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(splitter, 1)
        layout.addLayout(options)
        self.refresh()

    # ---------------------------------------------------------------- data
    def refresh(self, select=None):
        active = current_project()
        self.active.setText(f"Projet actif : {active['name']}  ·  {active['type']}" if active else "Aucun projet actif")
        roots = mke_project.recent_projects()
        if active and active["root"] not in roots:
            roots.insert(0, active["root"])
        select = select or (active["root"] if active else None)
        self.project_list.blockSignals(True)
        self.project_list.clear()
        for root in roots:
            info = mke_project.read_project(root)
            shots, assets = len(info["shots"]), len(info["assets"])
            item = QtWidgets.QListWidgetItem(f"{info['name']}\n{info['type']}  ·  {shots} plans  ·  {assets} assets")
            item.setData(QtCore.Qt.UserRole, root)
            item.setToolTip(root)
            font = item.font()
            font.setBold(active is not None and root == active["root"])
            item.setFont(font)
            self.project_list.addItem(item)
            if root == select:
                self.project_list.setCurrentItem(item)
        if self.project_list.currentItem() is None and self.project_list.count():
            self.project_list.setCurrentRow(0)
        self.project_list.blockSignals(False)
        self.empty_projects.setVisible(not roots)
        self._refresh_entities()

    def selected_project(self):
        item = self.project_list.currentItem()
        return mke_project.read_project(item.data(QtCore.Qt.UserRole)) if item else None

    def _refresh_entities(self):
        self.entity_tree.clear()
        info = self.selected_project()
        self.entity_button.setEnabled(bool(info))
        self.settings_button.setEnabled(bool(info))
        self.project_summary.setText(
            f"{info['fps']:g} fps  ·  frames {info['frame_start']}-{info['frame_end']}  ·  "
            f"{info['resolution'][0]}x{info['resolution'][1]}\nscènes : {mke_project.scenes_dir(info) or '(racine)'}"
            f"  ·  cache : {info['cache']}" if info else "")
        if info:
            project = QtWidgets.QTreeWidgetItem(self.entity_tree, ["Scènes du projet"])
            project.setData(0, QtCore.Qt.UserRole, ("project", {}))
            shots = QtWidgets.QTreeWidgetItem(self.entity_tree, ["Plans"])
            sequences = {}
            for entry in info["shots"]:
                seq, shot = entry.split("/")
                if seq not in sequences:
                    sequences[seq] = QtWidgets.QTreeWidgetItem(shots, [seq])
                start, end = mke_project.shot_range(info, entry)
                item = QtWidgets.QTreeWidgetItem(sequences[seq], [f"{shot}    {start}-{end}"])
                item.setData(0, QtCore.Qt.UserRole, ("shot", {"seq": seq, "shot": shot}))
            assets = QtWidgets.QTreeWidgetItem(self.entity_tree, ["Assets"])
            for asset in info["assets"]:
                item = QtWidgets.QTreeWidgetItem(assets, [asset])
                item.setData(0, QtCore.Qt.UserRole, ("asset", {"asset": asset}))
            self.entity_tree.expandAll()
            if not self._select_current_scene(info):
                self.entity_tree.setCurrentItem(project)
        self._refresh_versions()

    def _select_current_scene(self, info):
        """Pre-select the shot / asset of the open scene when it belongs to this project."""
        folder = os.path.dirname(hou.hipFile.path()).replace("\\", "/")
        iterator = QtWidgets.QTreeWidgetItemIterator(self.entity_tree)
        while iterator.value():
            item = iterator.value()
            entity = item.data(0, QtCore.Qt.UserRole)
            if entity and mke_project.entity_dir(info, entity[0], **entity[1]) == folder:
                self.entity_tree.setCurrentItem(item)
                return True
            iterator += 1
        return False

    def selected_entity(self):
        item = self.entity_tree.currentItem()
        return item.data(0, QtCore.Qt.UserRole) if item else None

    def _refresh_versions(self):
        self.version_list.clear()
        info, entity = self.selected_project(), self.selected_entity()
        if info and entity:
            for version in mke_project.list_versions(mke_project.entity_dir(info, entity[0], **entity[1])):
                item = QtWidgets.QTreeWidgetItem([version["version"], version["date"], version["user"], version["comment"]])
                item.setData(0, QtCore.Qt.UserRole, version)
                item.setToolTip(0, version["file"])
                item.setToolTip(3, version["comment"])
                self.version_list.addTopLevelItem(item)
            for column in range(3):
                self.version_list.resizeColumnToContents(column)
            if self.version_list.topLevelItemCount():
                self.version_list.setCurrentItem(self.version_list.topLevelItem(0))
        self.new_scene_button.setEnabled(bool(info and entity))
        self.open_button.setEnabled(bool(self.version_list.topLevelItemCount()))
        self._refresh_thumbnail()
        self._refresh_media()

    def _refresh_media(self):
        """Scan media only while the Médias tab is shown: OUT folders can be large."""
        if self.content_tabs.currentIndex() != 1:
            return
        self.media_list.clear()
        info, entity = self.selected_project(), self.selected_entity()
        if info and entity:
            for media in mke_project.list_media(info, entity[0], **entity[1]):
                item = QtWidgets.QTreeWidgetItem([media["name"], media["date"], media["kind"], media["info"]])
                item.setData(0, QtCore.Qt.UserRole, media)
                item.setToolTip(0, media["path"])
                self.media_list.addTopLevelItem(item)
            for column in (1, 2, 3):
                self.media_list.resizeColumnToContents(column)
            self.media_list.setColumnWidth(0, max(260, self.media_list.width() - sum(
                self.media_list.columnWidth(c) for c in (1, 2, 3)) - 30))
            if self.media_list.topLevelItemCount():
                self.media_list.setCurrentItem(self.media_list.topLevelItem(0))
        self.play_button.setEnabled(bool(self.media_list.topLevelItemCount()))
        self._refresh_media_preview()

    def selected_media(self):
        item = self.media_list.currentItem()
        return item.data(0, QtCore.Qt.UserRole) if item else None

    def _refresh_media_preview(self):
        media = self.selected_media()
        if self.video_player:
            if media and media["kind"] == "Vidéo":
                self.preview_stack.setCurrentWidget(self.video_player)
                self.video_player.load(media["path"])
                return
            self.video_player.stop()
            self.preview_stack.setCurrentWidget(self.media_preview)
        first = media["first"] if media else ""
        pixmap = QtGui.QPixmap(first) if first.lower().endswith((".png", ".jpg", ".jpeg")) else QtGui.QPixmap()
        if pixmap.isNull():
            self.media_preview.setPixmap(QtGui.QPixmap())
            self.media_preview.setText("Double-clic pour lire" if media else
                                       "Aucun média : « + Daily flipbook » en crée un depuis le viewport")
        else:
            self.media_preview.setPixmap(pixmap.scaled(500, 280, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))

    def done(self, result):
        if self.video_player:
            self.video_player.stop()  # release the file and the decoder when the dashboard closes
        super().done(result)

    def closeEvent(self, event):
        if self.video_player:
            self.video_player.stop()
        super().closeEvent(event)

    def _play_media(self):
        media = self.selected_media()
        if not media:
            return
        if media["kind"] == "Séquence":
            mplay = os.path.join(hou.getenv("HFS"), "bin", "mplay")
            subprocess.Popen([mplay, media["mplay"]])
        else:
            os.startfile(media["path"])

    def _open_media_folder(self):
        media, info = self.selected_media(), self.selected_project()
        folder = media["folder"] if media else (mke_project.media_roots(info) or [info["root"]])[0] if info else None
        if folder:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(folder))

    def _daily(self):
        import mke_daily
        if mke_daily.dailyFlipbook():
            self.accept()

    def _refresh_thumbnail(self):
        item = self.version_list.currentItem()
        thumb = item.data(0, QtCore.Qt.UserRole)["thumb"] if item else None
        pixmap = QtGui.QPixmap(thumb) if thumb else QtGui.QPixmap()
        if pixmap.isNull():
            self.thumbnail.setPixmap(QtGui.QPixmap())
            self.thumbnail.setText("Pas d'aperçu (il sera pris au prochain Save Up)" if item else
                                   "Pas encore de scène ici : « Nouvelle scène ici » crée la v0001" if self.selected_entity() else "")
        else:
            self.thumbnail.setPixmap(pixmap.scaled(356, 200, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))

    # ---------------------------------------------------------------- actions
    def _browse(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Dossier d'un projet MKE")
        if not path:
            return
        info = mke_project.find_project(path)
        if not info:
            scenes = mke_project.detect_scenes_dir(path) or "(racine)"
            if hou.ui.displayMessage(
                    f"Ce dossier n'est pas encore dans le pipeline.\n\nL'ajouter ? Rien n'est déplacé : seul "
                    f"PIPELINE/project.json est créé.\nScènes détectées dans : {scenes}",
                    buttons=("Ajouter", "Annuler"), close_choice=1) == 1:
                return
            presets = mke_project.load_presets()
            info = mke_project.adopt_project(path, "FX", mke_project.preset_settings(presets, "FX"))
        mke_project.add_recent(info["root"])
        self.refresh(select=info["root"])

    def _new_project(self):
        dialog = CreateProjectDialog(self)
        if dialog.exec_():
            self.accept()  # the new project's first scene is open
        elif dialog.existing_root:
            mke_project.add_recent(dialog.existing_root)
            self.refresh(select=dialog.existing_root)

    def _edit_settings(self):
        info = self.selected_project()
        if info and ProjectSettingsDialog(info, self).exec_():
            self.refresh(select=info["root"])

    def _edit_entities(self):
        info = self.selected_project()
        if info:
            EntitiesDialog(info, self).exec_()
            self.refresh(select=info["root"])

    def _open_version(self):
        item = self.version_list.currentItem()
        if not item or not _confirm_discard():
            return
        version = item.data(0, QtCore.Qt.UserRole)
        mke_project.open_scene(version["path"])
        self.accept()
        hou.ui.setStatusMessage(f"{version['file']} ouvert")

    def _new_scene(self):
        info, entity = self.selected_project(), self.selected_entity()
        if not info or not entity or not _confirm_discard():
            return
        hip = mke_project.new_entity_scene(info, entity[0], **entity[1])
        self.accept()
        hou.ui.setStatusMessage(f"Nouvelle scène : {os.path.basename(hip)}")


# ==================================================================== project settings

FPS_PRESETS = ["23.976", "24", "25", "29.97", "30", "48", "50", "59.94", "60"]
RESOLUTION_PRESETS = [("HD 720", 1280, 720), ("Full HD", 1920, 1080), ("2K DCI", 2048, 1080),
                      ("UHD 4K", 3840, 2160), ("Carré", 1080, 1080), ("Vertical", 1080, 1920)]
CARD_STYLE = "QFrame#card { background: rgba(255, 255, 255, 10); border: 1px solid rgba(255, 255, 255, 22); border-radius: 6px; }"


def _card(title, rows):
    """A rounded box with a small caps title and label/field rows aligned on one grid."""
    card = QtWidgets.QFrame()
    card.setObjectName("card")
    card.setStyleSheet(CARD_STYLE)
    grid = QtWidgets.QGridLayout(card)
    grid.setContentsMargins(14, 10, 14, 12)
    grid.setHorizontalSpacing(14)
    grid.setVerticalSpacing(8)
    grid.addWidget(_section(title), 0, 0, 1, 2)
    for row, (label, field) in enumerate(rows, 1):
        text = QtWidgets.QLabel(label)
        text.setStyleSheet("color: #b0b0b0;")
        grid.addWidget(text, row, 0, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        if isinstance(field, QtWidgets.QLayout):
            grid.addLayout(field, row, 1)
        else:
            grid.addWidget(field, row, 1)
    grid.setColumnMinimumWidth(0, 110)
    grid.setColumnStretch(1, 1)
    return card


def _row(*widgets):
    row = QtWidgets.QHBoxLayout()
    row.setSpacing(6)
    for widget in widgets:
        if widget is None:
            row.addStretch()
        elif isinstance(widget, str):
            label = QtWidgets.QLabel(widget)
            label.setStyleSheet("color: #8a8a8a;")
            row.addWidget(label)
        else:
            row.addWidget(widget)
    return row


def _compact_spin(minimum, maximum, value, width=86):
    spin = _spin(minimum, maximum, value)
    spin.setFixedWidth(width)
    spin.setAlignment(QtCore.Qt.AlignRight)
    return spin


class ProjectSettingsDialog(QtWidgets.QDialog):
    """Read and edit a project's project.json, grouped in cards: identity, time, image, folders."""

    def __init__(self, info, parent=None):
        super().__init__(parent)
        self.info = info
        self.setWindowTitle(f"Réglages  ·  {info['name']}")
        self.setStyleSheet(STYLE)
        self.setMinimumWidth(560)
        presets = mke_project.load_presets()

        # header: editable name + where the project lives
        self.name_input = QtWidgets.QLineEdit(info["name"])
        self.name_input.setStyleSheet("font-size: 14pt; font-weight: bold; padding: 4px;")
        root = info["root"] if len(info["root"]) < 50 else ".../" + "/".join(info["root"].split("/")[-2:])
        where = _label(f"{root}  ·  créé le {info.get('created', '?')} par {info.get('author', '?')}", "hint")
        where.setToolTip(info["root"])
        open_folder = QtWidgets.QToolButton()
        open_folder.setText("Ouvrir le dossier")
        open_folder.clicked.connect(lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(info["root"])))

        # identity
        self.type_group = QtWidgets.QButtonGroup(self)
        types = list(presets["types"])
        if info["type"] not in types:
            types.append(info["type"])
        type_row = QtWidgets.QHBoxLayout()
        type_row.setSpacing(4)
        for type_ in types:
            button = QtWidgets.QPushButton({"RND": "R&&D"}.get(type_, type_ if len(type_) <= 3 else type_.capitalize()))
            button.setProperty("type_value", type_)
            button.setCheckable(True)
            button.setFocusPolicy(QtCore.Qt.NoFocus)
            button.toggled.connect(lambda checked, b=button: b.setStyleSheet(TYPE_CHECKED_STYLE if checked else TYPE_STYLE))
            button.setStyleSheet(TYPE_STYLE)
            self.type_group.addButton(button)
            type_row.addWidget(button)
            button.setChecked(type_ == info["type"])
        type_row.addStretch()

        # time
        self.fps = QtWidgets.QComboBox()
        self.fps.setEditable(True)
        self.fps.addItems(FPS_PRESETS)
        self.fps.setValidator(QtGui.QDoubleValidator(1, 1000, 3))
        self.fps.setCurrentText(f"{info['fps']:g}")
        self.fps.setFixedWidth(100)
        self.start = _compact_spin(-100000, 100000, info["frame_start"])
        self.end = _compact_spin(-100000, 100000, info["frame_end"])
        self.duration = _label("", "hint")
        self.duration.setWordWrap(False)

        # image
        self.res_preset = QtWidgets.QComboBox()
        for label, w, h in RESOLUTION_PRESETS:
            self.res_preset.addItem(f"{label}  ({w}x{h})", (w, h))
        self.res_preset.addItem("Personnalisée", None)
        self.res_x = _compact_spin(16, 16384, info["resolution"][0])
        self.res_y = _compact_spin(16, 16384, info["resolution"][1])
        self.aspect = _label("", "hint")
        self.aspect.setWordWrap(False)

        # folders
        self.scenes_input = QtWidgets.QLineEdit(mke_project.scenes_dir(info))
        self.scenes_input.setPlaceholderText("racine du projet")
        self.scenes_input.setToolTip("Relatif au projet. Rien n'est déplacé : seul l'endroit où chercher les scènes change.")
        self.cache_input = QtWidgets.QLineEdit(info["cache"])
        self.cache_input.setToolTip("Relatif au projet ou chemin absolu. Devient $CACHE.")
        self.ocio_input = QtWidgets.QLineEdit(info.get("ocio", ""))
        self.ocio_input.setPlaceholderText("vide = config OCIO de Houdini")

        content = QtWidgets.QVBoxLayout()
        content.setSpacing(10)
        content.addWidget(_card("Type", [("", type_row)]))
        content.addWidget(_card("Temps", [
            ("Images / s", _row(self.fps, None)),
            ("Frames", _row(self.start, "→", self.end, None, self.duration)),
        ]))
        content.addWidget(_card("Image", [
            ("Format", _row(self.res_preset, None)),
            ("Résolution", _row(self.res_x, "×", self.res_y, None, self.aspect)),
        ]))
        content.addWidget(_card("Dossiers", [
            ("Scènes", self._folder_field(self.scenes_input, relative=True)),
            ("Cache", self._folder_field(self.cache_input, relative=True)),
            ("OCIO", self._file_field(self.ocio_input)),
        ]))

        self.apply_check = QtWidgets.QCheckBox("Appliquer à la scène ouverte")
        active = current_project()
        self.apply_check.setVisible(bool(active and active["root"] == info["root"]))
        self.apply_check.setChecked(True)
        self.error = _label("", "warning")
        cancel = QtWidgets.QPushButton("Annuler")
        cancel.clicked.connect(self.reject)
        self.save_button = QtWidgets.QPushButton("Enregistrer")
        self.save_button.setObjectName("primary")
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self._save)

        header = QtWidgets.QHBoxLayout()
        header.addWidget(self.name_input, 1)
        header.addWidget(open_folder)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(8)
        layout.addLayout(header)
        layout.addWidget(where)
        layout.addSpacing(4)
        layout.addLayout(content)
        layout.addWidget(self.error)
        layout.addLayout(_row(self.apply_check, None, cancel, self.save_button))

        self.res_preset.currentIndexChanged.connect(self._on_res_preset)
        for widget in (self.start, self.end, self.res_x, self.res_y):
            widget.valueChanged.connect(self._refresh)
        for widget in (self.name_input, self.scenes_input, self.cache_input, self.ocio_input):
            widget.textChanged.connect(self._refresh)
        self.fps.currentTextChanged.connect(self._refresh)
        self.type_group.buttonToggled.connect(lambda *_: self._refresh())
        self._initial = self._values()
        self._refresh()

    # ---------------------------------------------------------------- fields
    def _folder_field(self, line_edit, relative):
        def browse():
            start = os.path.join(self.info["root"], line_edit.text())
            path = QtWidgets.QFileDialog.getExistingDirectory(self, "Choisir un dossier", start)
            if path:
                rel = os.path.relpath(path, self.info["root"]).replace("\\", "/")
                line_edit.setText("" if rel == "." else rel if relative and not rel.startswith("..") else path.replace("\\", "/"))
        return self._with_buttons(line_edit, browse)

    def _file_field(self, line_edit):
        def browse():
            path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Config OCIO", line_edit.text(), "OCIO (*.ocio)")
            if path:
                line_edit.setText(path.replace("\\", "/"))
        return self._with_buttons(line_edit, browse)

    def _with_buttons(self, line_edit, browse):
        button = QtWidgets.QToolButton()
        button.setText("...")
        button.setToolTip("Parcourir")
        button.clicked.connect(browse)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(4)
        row.addWidget(line_edit, 1)
        row.addWidget(button)
        return row

    # ---------------------------------------------------------------- state
    def _fps_value(self):
        try:
            return float(self.fps.currentText().replace(",", "."))
        except ValueError:
            return 0.0

    def _values(self):
        checked = self.type_group.checkedButton()
        return (self.name_input.text().strip(), checked.property("type_value") if checked else "", self._fps_value(),
                self.start.value(), self.end.value(), self.res_x.value(), self.res_y.value(),
                self.scenes_input.text().strip(), self.cache_input.text().strip(), self.ocio_input.text().strip())

    def _on_res_preset(self, index):
        size = self.res_preset.itemData(index)
        if size:
            self.res_x.setValue(size[0])
            self.res_y.setValue(size[1])

    def _refresh(self, *_):
        fps, frames = self._fps_value(), self.end.value() - self.start.value() + 1
        self.duration.setText(f"{frames} frames  ·  {frames / fps:.1f} s" if frames > 0 and fps > 0 else "")
        w, h = self.res_x.value(), self.res_y.value()
        self.aspect.setText(f"ratio {w / h:.2f}")
        match = [i for i in range(self.res_preset.count()) if self.res_preset.itemData(i) == (w, h)]
        self.res_preset.blockSignals(True)
        self.res_preset.setCurrentIndex(match[0] if match else self.res_preset.count() - 1)
        self.res_preset.blockSignals(False)

        errors = []
        if not mke_project.sanitize_name(self.name_input.text()):
            errors.append("Le nom ne peut pas être vide.")
        if fps <= 0:
            errors.append("Images / s invalide.")
        if frames <= 0:
            errors.append("La dernière frame doit être après la première.")
        scenes = self.scenes_input.text().strip().replace("\\", "/").strip("/")
        if not os.path.isdir(os.path.join(self.info["root"], scenes)):
            errors.append(f"Le dossier de scènes « {scenes} » n'existe pas dans le projet.")
        self.error.setText("\n".join(errors))
        self.error.setVisible(bool(errors))
        self.save_button.setEnabled(not errors and self._values() != self._initial)

    def _save(self):
        if not self.save_button.isEnabled():
            return
        self.info.update({
            "name": mke_project.sanitize_name(self.name_input.text()),
            "type": self.type_group.checkedButton().property("type_value"),
            "fps": self._fps_value(), "frame_start": self.start.value(), "frame_end": self.end.value(),
            "resolution": [self.res_x.value(), self.res_y.value()],
            "scenes": self.scenes_input.text().strip().replace("\\", "/").strip("/"),
            "cache": self.cache_input.text().strip().replace("\\", "/") or self.info["cache"],
            "ocio": self.ocio_input.text().strip(),
        })
        mke_project.write_project(self.info)
        if self.apply_check.isVisible() and self.apply_check.isChecked():
            mke_project.apply_to_scene(self.info)
        self.accept()
        hou.ui.setStatusMessage(f"Réglages de {self.info['name']} enregistrés")


# ==================================================================== new project

class CreateProjectDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nouveau projet")
        self.setStyleSheet(STYLE)
        self.resize(580, 820)
        self.presets = mke_project.load_presets()
        self.custom_folders = []
        self.existing_root = None
        layout = QtWidgets.QVBoxLayout(self)

        layout.addWidget(_section("Nom du projet"))
        self.name_input = QtWidgets.QLineEdit()
        self.name_input.setPlaceholderText("ex : Ocean_Teaser")
        self.name_input.setStyleSheet("font-size: 12pt; padding: 4px;")
        layout.addWidget(self.name_input)

        layout.addWidget(_section("Type"))
        self.type_group = QtWidgets.QButtonGroup(self)
        type_row = QtWidgets.QHBoxLayout()
        for type_ in list(self.presets["types"]) + [OTHER]:
            label = {"RND": "R&&D"}.get(type_, type_ if len(type_) <= 3 else type_.capitalize())
            button = QtWidgets.QPushButton(label)
            button.setStyleSheet(TYPE_STYLE)
            button.setProperty("type_value", type_)
            button.setCheckable(True)
            button.setFocusPolicy(QtCore.Qt.NoFocus)
            self.type_group.addButton(button)
            button.toggled.connect(lambda checked, b=button: self._on_type_toggled(b, checked))
            type_row.addWidget(button)
        layout.addLayout(type_row)
        self.other_input = QtWidgets.QLineEdit()
        self.other_input.setPlaceholderText("Nom du type, ex : CFX")
        self.other_input.setVisible(False)
        layout.addWidget(self.other_input)

        layout.addWidget(_section("Emplacement"))
        recent = mke_project.recent_projects()
        default_parent = os.path.dirname(recent[0]) if recent else os.path.expanduser("~")
        self.parent_input = QtWidgets.QLineEdit(default_parent)
        layout.addLayout(_path_field(self.parent_input, "Dossier où créer le projet", self))
        self.preview = _label("", "hint")
        self.warning = _label("", "warning")
        layout.addWidget(self.preview)
        layout.addWidget(self.warning)

        layout.addWidget(_section("Réglages"))
        layout.addWidget(self._settings_panel(), 1)
        self.starter_check = QtWidgets.QCheckBox("Préparer une scène de départ avec les outils MKE")
        self.starter_check.setChecked(True)
        layout.addWidget(self.starter_check)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch()
        cancel = QtWidgets.QPushButton("Annuler")
        cancel.clicked.connect(self.reject)
        self.create_button = QtWidgets.QPushButton("Créer le projet")
        self.create_button.setObjectName("primary")
        self.create_button.setDefault(True)
        self.create_button.clicked.connect(self._create)
        buttons.addWidget(cancel)
        buttons.addWidget(self.create_button)
        layout.addLayout(buttons)

        for widget in (self.name_input, self.parent_input, self.other_input):
            widget.textChanged.connect(self._refresh_preview)
        self.other_input.textChanged.connect(self._refresh_folders)
        self.type_group.buttons()[0].setChecked(True)  # fires _on_type_toggled

    def _settings_panel(self):
        panel = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(panel)
        form.setContentsMargins(0, 0, 0, 0)
        d = self.presets["defaults"]
        self.fps = _spin(1, 240, d["fps"], double=True)
        self.start = _spin(-100000, 100000, d["frame_start"])
        self.end = _spin(-100000, 100000, d["frame_end"])
        self.res_x = _spin(16, 16384, d["resolution"][0])
        self.res_y = _spin(16, 16384, d["resolution"][1])
        frames = QtWidgets.QHBoxLayout()
        frames.addWidget(self.start)
        frames.addWidget(QtWidgets.QLabel("à"))
        frames.addWidget(self.end)
        res = QtWidgets.QHBoxLayout()
        res.addWidget(self.res_x)
        res.addWidget(QtWidgets.QLabel("x"))
        res.addWidget(self.res_y)
        self.cache_input = QtWidgets.QLineEdit(self.presets["cache"])
        self.cache_input.setToolTip("Relatif au projet (3D/CACHES) ou absolu (ex : D:/CACHES/projet)")
        self.ocio_input = QtWidgets.QLineEdit(d.get("ocio", ""))
        self.ocio_input.setPlaceholderText("vide = config de Houdini")
        self.keep_check = QtWidgets.QCheckBox("Garder la scène ouverte au lieu d'une scène vide")
        form.addRow("Images / seconde", self.fps)
        form.addRow("Frames", frames)
        form.addRow("Résolution", res)
        form.addRow("Cache", _path_field(self.cache_input, "Dossier de cache", self))
        form.addRow("OCIO", self.ocio_input)
        form.addRow("", self.keep_check)

        self.folder_tree = QtWidgets.QTreeWidget()
        self.folder_tree.setHeaderHidden(True)
        self.folder_tree.setMinimumHeight(160)
        self.folder_input = QtWidgets.QLineEdit()
        self.folder_input.setPlaceholderText("Ajouter un dossier, ex : IN/AUDIO")
        self.folder_input.returnPressed.connect(self._add_folder)
        folders = QtWidgets.QVBoxLayout()
        folders.addWidget(self.folder_tree)
        folders.addWidget(self.folder_input)
        form.addRow("Dossiers", folders)
        self.cache_input.textChanged.connect(self._refresh_folders)
        return panel

    def _on_type_toggled(self, button, checked):
        # Style set per button (not through a global :checked rule) so Houdini's own stylesheet cannot hide it
        button.setStyleSheet(TYPE_CHECKED_STYLE if checked else TYPE_STYLE)
        if checked:
            self._on_type_changed()

    def project_type(self):
        type_ = self.type_group.checkedButton().property("type_value")
        return mke_project.sanitize_name(self.other_input.text()).upper() if type_ == OTHER else type_

    def _on_type_changed(self):
        type_ = self.type_group.checkedButton().property("type_value")
        self.other_input.setVisible(type_ == OTHER)
        settings = mke_project.preset_settings(self.presets, type_)
        self.fps.setValue(settings["fps"])
        self.start.setValue(settings["frame_start"])
        self.end.setValue(settings["frame_end"])
        self.res_x.setValue(settings["resolution"][0])
        self.res_y.setValue(settings["resolution"][1])
        self._refresh_folders()
        self._refresh_preview()

    def _refresh_folders(self, *_):
        unchecked = set(self._folders(QtCore.Qt.Unchecked))
        self.folder_tree.clear()
        folders = mke_project.preset_folders(self.presets, self.project_type() or "OTHER", self.cache_input.text().strip())
        for folder in folders + self.custom_folders:
            if os.path.isabs(folder):
                continue  # an absolute cache is created on its own
            parent = self.folder_tree.invisibleRootItem()
            for part in folder.split("/"):
                match = [parent.child(i) for i in range(parent.childCount()) if parent.child(i).text(0) == part]
                if match:
                    parent = match[0]
                    continue
                item = QtWidgets.QTreeWidgetItem(parent, [part])
                item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsAutoTristate)
                item.setCheckState(0, QtCore.Qt.Checked)
                parent = item
            if folder in unchecked:
                parent.setCheckState(0, QtCore.Qt.Unchecked)
        self.folder_tree.expandAll()

    def _folders(self, state=QtCore.Qt.Checked):
        """Leaf folder paths with the given check state."""
        result = []

        def walk(item, path):
            for i in range(item.childCount()):
                child = item.child(i)
                child_path = f"{path}/{child.text(0)}" if path else child.text(0)
                if child.childCount():
                    walk(child, child_path)
                elif child.checkState(0) == state:
                    result.append(child_path)
        walk(self.folder_tree.invisibleRootItem(), "")
        return result

    def _add_folder(self):
        folder = self.folder_input.text().strip().replace("\\", "/").strip("/")
        if folder and folder not in self.custom_folders:
            self.custom_folders.append(folder)
            self._refresh_folders()
        self.folder_input.clear()

    def _refresh_preview(self, *_):
        name = mke_project.sanitize_name(self.name_input.text())
        root = os.path.join(self.parent_input.text(), name).replace("\\", "/")
        self.create_button.setEnabled(bool(name and self.project_type()))
        self.preview.setText(f"Sera créé dans : .../{'/'.join(root.split('/')[-3:])}" if name else "")
        self.preview.setToolTip(root)
        warnings = []
        if name and os.path.isfile(os.path.join(root, mke_project.PROJECT_FILE)):
            warnings.append("Ce projet existe déjà : il te sera proposé de l'ouvrir.")
        server = mke_project.server_warning(root)
        if server:
            warnings.append(server)
        self.warning.setText("\n".join(warnings))
        self.warning.setVisible(bool(warnings))

    def _create(self):
        if not self.keep_check.isChecked() and not _confirm_discard():
            return
        settings = {"fps": self.fps.value(), "frame_start": self.start.value(), "frame_end": self.end.value(),
                    "resolution": [self.res_x.value(), self.res_y.value()], "ocio": self.ocio_input.text().strip()}
        try:
            info, hip = mke_project.create_project(
                self.parent_input.text(), self.name_input.text(), self.project_type(), self._folders(), settings,
                self.cache_input.text().strip() or self.presets["cache"],
                keep_scene=self.keep_check.isChecked(), starter=self.starter_check.isChecked())
        except FileExistsError as existing:
            if hou.ui.displayMessage(f"Ce projet existe déjà :\n{existing}", buttons=("Le voir", "Annuler"),
                                     close_choice=1) == 0:
                self.existing_root = str(existing).replace("\\", "/")
                self.reject()
            return
        except Exception as error:
            hou.ui.displayMessage(f"La création a échoué : {error}", severity=hou.severityType.Error)
            return
        self.accept()
        hou.ui.setStatusMessage(f"Projet {info['name']} créé, scène {os.path.basename(hip)} ouverte.")


# ==================================================================== shots and assets

class EntitiesDialog(QtWidgets.QDialog):
    def __init__(self, info, parent=None):
        super().__init__(parent)
        self.info = info
        self.setWindowTitle(f"Plans et assets  ·  {info['name']}")
        self.setStyleSheet(STYLE)
        self.resize(560, 560)

        self.seq_input = QtWidgets.QLineEdit()
        self.seq_input.setPlaceholderText("Séquence, ex : SEQ010")
        self.shot_input = QtWidgets.QLineEdit()
        self.shot_input.setPlaceholderText("Plan, ex : SH0010")
        self.shot_start = _spin(-100000, 100000, info["frame_start"])
        self.shot_end = _spin(-100000, 100000, info["frame_end"])
        shot_button = QtWidgets.QPushButton("Ajouter / mettre à jour le plan")
        shot_button.clicked.connect(self._add_shot)
        self.shot_input.returnPressed.connect(shot_button.click)
        self.asset_input = QtWidgets.QLineEdit()
        self.asset_input.setPlaceholderText("Nom de l'asset, ex : Rocher")
        asset_button = QtWidgets.QPushButton("Ajouter l'asset")
        asset_button.clicked.connect(lambda: self._add("asset", asset=self.asset_input.text()))
        self.asset_input.returnPressed.connect(asset_button.click)

        shot_row = QtWidgets.QHBoxLayout()
        shot_row.addWidget(self.seq_input)
        shot_row.addWidget(self.shot_input)
        range_row = QtWidgets.QHBoxLayout()
        range_row.addWidget(QtWidgets.QLabel("Frames"))
        range_row.addWidget(self.shot_start)
        range_row.addWidget(QtWidgets.QLabel("à"))
        range_row.addWidget(self.shot_end)
        range_row.addStretch()
        range_row.addWidget(shot_button)
        asset_row = QtWidgets.QHBoxLayout()
        asset_row.addWidget(self.asset_input)
        asset_row.addWidget(asset_button)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.currentItemChanged.connect(self._fill_shot_fields)
        close = QtWidgets.QPushButton("Fermer")
        close.clicked.connect(self.accept)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(_section("Plan"))
        layout.addLayout(shot_row)
        layout.addLayout(range_row)
        layout.addWidget(_label("Clique un plan existant ci-dessous pour modifier sa plage de frames.", "hint"))
        layout.addWidget(_section("Asset"))
        layout.addLayout(asset_row)
        layout.addWidget(_section("Dans le projet"))
        layout.addWidget(self.tree, 1)
        layout.addWidget(close, 0, QtCore.Qt.AlignRight)
        self._refresh()

    def _refresh(self):
        self.tree.clear()
        shots = QtWidgets.QTreeWidgetItem(self.tree, [f"Plans ({len(self.info['shots'])})"])
        sequences = {}
        for entry in self.info["shots"]:
            seq, shot = entry.split("/")
            if seq not in sequences:
                sequences[seq] = QtWidgets.QTreeWidgetItem(shots, [seq])
            start, end = mke_project.shot_range(self.info, entry)
            item = QtWidgets.QTreeWidgetItem(sequences[seq], [f"{shot}    {start}-{end}"])
            item.setData(0, QtCore.Qt.UserRole, (seq, shot, start, end))
        assets = QtWidgets.QTreeWidgetItem(self.tree, [f"Assets ({len(self.info['assets'])})"])
        for asset in self.info["assets"]:
            QtWidgets.QTreeWidgetItem(assets, [asset])
        self.tree.expandAll()

    def _fill_shot_fields(self, item, *_):
        data = item.data(0, QtCore.Qt.UserRole) if item else None
        if data:
            seq, shot, start, end = data
            self.seq_input.setText(seq)
            self.shot_input.setText(shot)
            self.shot_start.setValue(start)
            self.shot_end.setValue(end)

    def _add_shot(self):
        if self.shot_end.value() < self.shot_start.value():
            hou.ui.displayMessage("La fin doit être après le début.", severity=hou.severityType.Warning)
            return
        self._add("shot", frame_range=(self.shot_start.value(), self.shot_end.value()),
                  seq=self.seq_input.text(), shot=self.shot_input.text())

    def _add(self, kind, frame_range=None, **names):
        try:
            created = mke_project.add_entity(self.info, kind, frame_range, **names)
        except ValueError:
            hou.ui.displayMessage("Remplis tous les champs.", severity=hou.severityType.Warning)
            return
        self._refresh()
        hou.ui.setStatusMessage(f"{'/'.join(names.values())} : {len(created)} dossiers prêts")


# ==================================================================== entry points

_dashboard = None


def projects():
    global _dashboard
    if _dashboard is not None:
        _dashboard.close()
    _dashboard = ProjectsDashboard(hou.qt.mainWindow() if hou.isUIAvailable() else None)
    _dashboard.show()
    return _dashboard


def open_at_startup():
    """Called once Houdini's UI is up: show the dashboard unless a scene was opened from the command line."""
    if mke_project.get_pref("open_at_startup", True) and hou.hipFile.isNewFile():
        projects()


projectSetup = projects  # old shelf buttons keep working
