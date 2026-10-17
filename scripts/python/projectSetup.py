"""Project Setup window: create a project, open one, add shots and assets. Logic lives in mke_project."""
import os

import hou
from hutil.Qt import QtCore, QtGui, QtWidgets

import mke_project

OTHER = "Autre"
TYPE_STYLE = "padding: 6px 12px;"
TYPE_CHECKED_STYLE = TYPE_STYLE + "background: #3d6ea8; color: white; border: 1px solid #5b8cc8;"
STYLE = """
QLabel#title { font-size: 15pt; font-weight: bold; }
QLabel#hint { color: #8a8a8a; }
QLabel#warning { color: #e0a030; }
QLabel#active { padding: 6px 10px; border-radius: 4px; background: rgba(255, 255, 255, 18); }
QPushButton#primary { padding: 6px 18px; font-weight: bold; }
"""


def _label(text, name=None):
    label = QtWidgets.QLabel(text)
    label.setWordWrap(True)
    if name:
        label.setObjectName(name)
    return label


def _section(title):
    label = QtWidgets.QLabel(title.upper())
    label.setStyleSheet("color: #8a8a8a; font-size: 8pt; font-weight: bold; margin-top: 10px;")
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


def _project_label(info):
    return f"{info['name']}  ·  {info['type']}" if info else "Aucun projet actif"


class ProjectSetupDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("MKE Project Setup")
        self.setStyleSheet(STYLE)
        self.resize(760, 860)
        self.presets = mke_project.load_presets()
        self.custom_folders = []

        self.active = _label("", "active")
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self._create_tab(), "Créer")
        self.tabs.addTab(self._open_tab(), "Scènes")
        self.tabs.addTab(self._entities_tab(), "Plans et assets")
        self.tabs.currentChanged.connect(self._refresh_active)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.active)
        layout.addWidget(self.tabs)
        self._refresh_active()

    def current_project(self):
        job = hou.getenv("JOB")
        return mke_project.find_project(job) if job and os.path.isdir(job) else None

    def _refresh_active(self, *_):
        info = self.current_project()
        self.active.setText(f"Projet actif : <b>{_project_label(info)}</b>" if info else "Aucun projet actif")
        self._refresh_entities(info)

    # ------------------------------------------------------------ create
    def _create_tab(self):
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)

        layout.addWidget(_section("Nom du projet"))
        self.name_input = QtWidgets.QLineEdit()
        self.name_input.setPlaceholderText("ex : Ocean_Teaser")
        self.name_input.setStyleSheet("font-size: 12pt; padding: 4px;")
        layout.addWidget(self.name_input)

        layout.addWidget(_section("Type"))
        self.type_group = QtWidgets.QButtonGroup(self)
        type_row = QtWidgets.QHBoxLayout()
        for i, type_ in enumerate(list(self.presets["types"]) + [OTHER]):
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
        self.parent_input = QtWidgets.QLineEdit(os.path.dirname(hou.getenv("JOB") or "") or os.path.expanduser("~"))
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
        layout.addStretch()

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch()
        self.create_button = QtWidgets.QPushButton("Créer le projet")
        self.create_button.setObjectName("primary")
        self.create_button.setDefault(True)
        self.create_button.clicked.connect(self._create)
        buttons.addWidget(self.create_button)
        layout.addLayout(buttons)

        for widget in (self.name_input, self.parent_input, self.other_input):
            widget.textChanged.connect(self._refresh_preview)
        self.other_input.textChanged.connect(self._refresh_folders)
        self.type_group.buttons()[0].setChecked(True)  # fires _on_type_toggled
        return tab

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
        add_row = QtWidgets.QHBoxLayout()
        self.folder_input = QtWidgets.QLineEdit()
        self.folder_input.setPlaceholderText("Ajouter un dossier, ex : IN/AUDIO")
        self.folder_input.returnPressed.connect(self._add_folder)
        add_row.addWidget(self.folder_input)
        folders = QtWidgets.QVBoxLayout()
        folders.addWidget(self.folder_tree)
        folders.addLayout(add_row)
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
        short = "/".join(root.split("/")[-3:])
        self.preview.setText(f"Sera créé dans : .../{short}" if name else "")
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
        type_ = self.project_type()
        if not self.keep_check.isChecked() and hou.hipFile.hasUnsavedChanges():
            if hou.ui.displayMessage("La scène ouverte a des changements non sauvegardés et va être fermée.",
                                     buttons=("Continuer", "Annuler"), default_choice=1, close_choice=1) == 1:
                return
        settings = {"fps": self.fps.value(), "frame_start": self.start.value(), "frame_end": self.end.value(),
                    "resolution": [self.res_x.value(), self.res_y.value()], "ocio": self.ocio_input.text().strip()}
        try:
            info, hip = mke_project.create_project(
                self.parent_input.text(), self.name_input.text(), type_, self._folders(), settings,
                self.cache_input.text().strip() or self.presets["cache"],
                keep_scene=self.keep_check.isChecked(), starter=self.starter_check.isChecked())
        except FileExistsError as existing:
            if hou.ui.displayMessage(f"Ce projet existe déjà :\n{existing}", buttons=("Voir ses scènes", "Annuler"),
                                     close_choice=1) == 0:
                root = str(existing).replace("\\", "/")
                mke_project.add_recent(root)
                self._fill_projects(select=root)
                self._refresh_browser()
                self.tabs.setCurrentIndex(1)
            return
        except Exception as error:
            hou.ui.displayMessage(f"La création a échoué : {error}", severity=hou.severityType.Error)
            return
        self.accept()
        hou.ui.setStatusMessage(f"Projet {info['name']} créé, scène {os.path.basename(hip)} ouverte.")

    # ------------------------------------------------------------ scene browser
    def _open_tab(self):
        tab = QtWidgets.QWidget()

        self.project_combo = QtWidgets.QComboBox()
        self.project_combo.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        browse = QtWidgets.QPushButton("Parcourir...")
        browse.clicked.connect(self._browse_open)
        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel("Projet"))
        top.addWidget(self.project_combo, 1)
        top.addWidget(browse)

        self.browser_tree = QtWidgets.QTreeWidget()
        self.browser_tree.setHeaderHidden(True)
        self.browser_tree.currentItemChanged.connect(lambda *_: self._refresh_versions())

        self.version_list = QtWidgets.QTreeWidget()
        self.version_list.setHeaderLabels(["Version", "Date", "Auteur", "Commentaire"])
        self.version_list.setRootIsDecorated(False)
        self.version_list.setAlternatingRowColors(True)
        self.version_list.header().setStretchLastSection(True)
        self.version_list.currentItemChanged.connect(lambda *_: self._refresh_thumbnail())
        self.version_list.itemDoubleClicked.connect(lambda *_: self._open_version())

        self.thumbnail = QtWidgets.QLabel("Pas d'aperçu")
        self.thumbnail.setAlignment(QtCore.Qt.AlignCenter)
        self.thumbnail.setFixedHeight(180)
        self.thumbnail.setObjectName("hint")
        self.thumbnail.setStyleSheet("border: 1px solid rgba(255, 255, 255, 30); border-radius: 4px;")

        right = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.version_list, 1)
        right_layout.addWidget(self.thumbnail)
        splitter = QtWidgets.QSplitter()
        splitter.addWidget(self.browser_tree)
        splitter.addWidget(right)
        splitter.setSizes([200, 480])

        new_button = QtWidgets.QPushButton("Nouvelle scène ici")
        new_button.setToolTip("Crée la v0001 de ce plan / asset dans son dossier, avec sa plage de frames")
        new_button.clicked.connect(self._new_scene)
        self.open_button = QtWidgets.QPushButton("Ouvrir la version")
        self.open_button.setObjectName("primary")
        self.open_button.clicked.connect(self._open_version)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(new_button)
        buttons.addStretch()
        buttons.addWidget(self.open_button)

        layout = QtWidgets.QVBoxLayout(tab)
        layout.addLayout(top)
        layout.addWidget(splitter, 1)
        layout.addLayout(buttons)

        self._fill_projects()
        self.project_combo.currentIndexChanged.connect(lambda *_: self._refresh_browser())
        self._refresh_browser()
        return tab

    def _fill_projects(self, select=None):
        current = self.current_project()
        roots = mke_project.recent_projects()
        if current and current["root"] not in roots:
            roots.insert(0, current["root"])
        select = select or (current["root"] if current else None)
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        for root in roots:
            info = mke_project.read_project(root)
            self.project_combo.addItem(f"{info['name']}  ·  {info['type']}", root)
            self.project_combo.setItemData(self.project_combo.count() - 1, root, QtCore.Qt.ToolTipRole)
        if select in roots:
            self.project_combo.setCurrentIndex(roots.index(select))
        self.project_combo.blockSignals(False)

    def browser_project(self):
        root = self.project_combo.currentData()
        return mke_project.read_project(root) if root else None

    def _refresh_browser(self):
        self.browser_tree.clear()
        info = self.browser_project()
        if not info:
            self._refresh_versions()
            return
        project = QtWidgets.QTreeWidgetItem(self.browser_tree, ["Scènes du projet"])
        project.setData(0, QtCore.Qt.UserRole, ("project", {}))
        shots = QtWidgets.QTreeWidgetItem(self.browser_tree, ["Plans"])
        sequences = {}
        for entry in info["shots"]:
            seq, shot = entry.split("/")
            if seq not in sequences:
                sequences[seq] = QtWidgets.QTreeWidgetItem(shots, [seq])
            start, end = mke_project.shot_range(info, entry)
            item = QtWidgets.QTreeWidgetItem(sequences[seq], [f"{shot}    {start}-{end}"])
            item.setData(0, QtCore.Qt.UserRole, ("shot", {"seq": seq, "shot": shot}))
        assets = QtWidgets.QTreeWidgetItem(self.browser_tree, ["Assets"])
        for asset in info["assets"]:
            item = QtWidgets.QTreeWidgetItem(assets, [asset])
            item.setData(0, QtCore.Qt.UserRole, ("asset", {"asset": asset}))
        self.browser_tree.expandAll()
        self._select_current_scene(info) or self.browser_tree.setCurrentItem(project)

    def _select_current_scene(self, info):
        """Pre-select the entity of the scene that is open, if it belongs to this project."""
        hip = hou.hipFile.path()
        folder = os.path.dirname(hip).replace("\\", "/")
        iterator = QtWidgets.QTreeWidgetItemIterator(self.browser_tree)
        while iterator.value():
            item = iterator.value()
            entity = item.data(0, QtCore.Qt.UserRole)
            if entity and mke_project.entity_dir(info, entity[0], **entity[1]) == folder:
                self.browser_tree.setCurrentItem(item)
                return True
            iterator += 1
        return False

    def selected_entity(self):
        item = self.browser_tree.currentItem()
        return item.data(0, QtCore.Qt.UserRole) if item else None

    def _refresh_versions(self):
        self.version_list.clear()
        info, entity = self.browser_project(), self.selected_entity()
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
        self.open_button.setEnabled(bool(self.version_list.topLevelItemCount()))
        self._refresh_thumbnail()

    def _refresh_thumbnail(self):
        item = self.version_list.currentItem()
        thumb = item.data(0, QtCore.Qt.UserRole)["thumb"] if item else None
        pixmap = QtGui.QPixmap(thumb) if thumb else QtGui.QPixmap()
        if pixmap.isNull():
            self.thumbnail.setPixmap(QtGui.QPixmap())
            self.thumbnail.setText("Pas d'aperçu (il sera pris au prochain Save Up)" if item else "Aucune version")
        else:
            self.thumbnail.setPixmap(pixmap.scaled(320, 180, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))

    def _browse_open(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Dossier d'un projet MKE")
        if not path:
            return
        info = mke_project.find_project(path)
        if not info:
            hou.ui.displayMessage("Ce dossier n'est pas un projet MKE (pas de PIPELINE/project.json).",
                                  severity=hou.severityType.Warning)
            return
        mke_project.add_recent(info["root"])
        self._fill_projects(select=info["root"])
        self._refresh_browser()

    def _confirm_discard(self):
        return not hou.hipFile.hasUnsavedChanges() or hou.ui.displayMessage(
            "La scène ouverte a des changements non sauvegardés.",
            buttons=("Continuer", "Annuler"), default_choice=1, close_choice=1) == 0

    def _open_version(self):
        item = self.version_list.currentItem()
        if not item or not self._confirm_discard():
            return
        version = item.data(0, QtCore.Qt.UserRole)
        info = mke_project.open_scene(version["path"])
        self.accept()
        hou.ui.setStatusMessage(f"{info['name'] if info else ''} : {version['file']} ouvert")

    def _new_scene(self):
        info, entity = self.browser_project(), self.selected_entity()
        if not info or not entity or not self._confirm_discard():
            return
        hip = mke_project.new_entity_scene(info, entity[0], **entity[1])
        self.accept()
        hou.ui.setStatusMessage(f"Nouvelle scène : {os.path.basename(hip)}")

    # ------------------------------------------------------------ shots and assets
    def _entities_tab(self):
        tab = QtWidgets.QWidget()
        self.seq_input = QtWidgets.QLineEdit()
        self.seq_input.setPlaceholderText("Séquence, ex : SEQ010")
        self.shot_input = QtWidgets.QLineEdit()
        self.shot_input.setPlaceholderText("Plan, ex : SH0010")
        self.shot_start = _spin(-100000, 100000, 1001)
        self.shot_end = _spin(-100000, 100000, 1100)
        shot_button = QtWidgets.QPushButton("Ajouter / mettre à jour le plan")
        shot_button.clicked.connect(self._add_shot)
        self.shot_input.returnPressed.connect(shot_button.click)
        self.asset_input = QtWidgets.QLineEdit()
        self.asset_input.setPlaceholderText("Nom de l'asset, ex : Rocher")
        asset_button = QtWidgets.QPushButton("Ajouter l'asset")
        asset_button.clicked.connect(lambda: self._add_entity("asset", asset=self.asset_input.text()))
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
        self.entity_tree = QtWidgets.QTreeWidget()
        self.entity_tree.setHeaderHidden(True)
        self.entity_tree.currentItemChanged.connect(self._fill_shot_fields)
        self.no_project = _label("Crée ou ouvre un projet pour ajouter des plans et des assets.", "hint")

        self.entity_form = QtWidgets.QWidget()
        form = QtWidgets.QVBoxLayout(self.entity_form)
        form.setContentsMargins(0, 0, 0, 0)
        form.addWidget(_section("Plan"))
        form.addLayout(shot_row)
        form.addLayout(range_row)
        form.addWidget(_label("Clique un plan existant ci-dessous pour modifier sa plage de frames.", "hint"))
        form.addWidget(_section("Nouvel asset"))
        form.addLayout(asset_row)
        form.addWidget(_section("Dans le projet"))
        form.addWidget(self.entity_tree)

        layout = QtWidgets.QVBoxLayout(tab)
        layout.addWidget(self.no_project)
        layout.addWidget(self.entity_form)
        return tab

    def _refresh_entities(self, info):
        self.no_project.setVisible(not info)
        self.entity_form.setVisible(bool(info))
        self.entity_tree.clear()
        if not info:
            return
        self.shot_start.setValue(info["frame_start"])
        self.shot_end.setValue(info["frame_end"])
        shots = QtWidgets.QTreeWidgetItem(self.entity_tree, [f"Plans ({len(info['shots'])})"])
        sequences = {}
        for entry in info["shots"]:
            seq, shot = entry.split("/")
            if seq not in sequences:
                sequences[seq] = QtWidgets.QTreeWidgetItem(shots, [seq])
            start, end = mke_project.shot_range(info, entry)
            item = QtWidgets.QTreeWidgetItem(sequences[seq], [f"{shot}    {start}-{end}"])
            item.setData(0, QtCore.Qt.UserRole, (seq, shot, start, end))
        assets = QtWidgets.QTreeWidgetItem(self.entity_tree, [f"Assets ({len(info['assets'])})"])
        for asset in info["assets"]:
            QtWidgets.QTreeWidgetItem(assets, [asset])
        self.entity_tree.expandAll()

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
        self._add_entity("shot", frame_range=(self.shot_start.value(), self.shot_end.value()),
                         seq=self.seq_input.text(), shot=self.shot_input.text())

    def _add_entity(self, kind, frame_range=None, **names):
        info = self.current_project()
        if not info:
            return
        try:
            created = mke_project.add_entity(info, kind, frame_range, **names)
        except ValueError:
            hou.ui.displayMessage("Remplis tous les champs.", severity=hou.severityType.Warning)
            return
        self._refresh_entities(info)
        self._refresh_browser()
        hou.ui.setStatusMessage(f"{'/'.join(names.values())} : {len(created)} dossiers prêts")


_dialog = None


def projectSetup(tab=None):
    """tab: 0 create, 1 scenes, 2 shots and assets. Default: Scenes if there is a project, else Create."""
    global _dialog
    if _dialog is not None:
        _dialog.close()
    _dialog = ProjectSetupDialog(hou.qt.mainWindow() if hou.isUIAvailable() else None)
    if tab is None:
        tab = 1 if _dialog.project_combo.count() else 0
    _dialog.tabs.setCurrentIndex(tab)
    _dialog.show()
    return _dialog
