"""Project Setup window: create a project, open one, add shots and assets. Logic lives in mke_project."""
import os

import hou
from hutil.Qt import QtCore, QtWidgets

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
        self.resize(580, 860)
        self.presets = mke_project.load_presets()
        self.custom_folders = []

        self.active = _label("", "active")
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self._create_tab(), "Créer")
        self.tabs.addTab(self._open_tab(), "Ouvrir")
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
            if hou.ui.displayMessage(f"Ce projet existe déjà :\n{existing}", buttons=("L'ouvrir", "Annuler"),
                                     close_choice=1) == 0:
                self._open(str(existing))
            return
        except Exception as error:
            hou.ui.displayMessage(f"La création a échoué : {error}", severity=hou.severityType.Error)
            return
        self.accept()
        hou.ui.setStatusMessage(f"Projet {info['name']} créé, scène {os.path.basename(hip)} ouverte.")

    # ------------------------------------------------------------ open
    def _open_tab(self):
        tab = QtWidgets.QWidget()
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Rechercher un projet")
        self.search.textChanged.connect(self._filter_recent)
        self.recent_list = QtWidgets.QListWidget()
        self.recent_list.setSpacing(2)
        self.recent_list.setTextElideMode(QtCore.Qt.ElideMiddle)
        self.recent_list.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.recent_list.setWordWrap(False)
        for root in mke_project.recent_projects():
            info = mke_project.read_project(root)
            item = QtWidgets.QListWidgetItem(f"{info['name']}   ·   {info['type']}\n{root}")
            item.setData(QtCore.Qt.UserRole, root)
            item.setToolTip(root)
            self.recent_list.addItem(item)
        if self.recent_list.count():
            self.recent_list.setCurrentRow(0)
        self.recent_list.itemDoubleClicked.connect(lambda item: self._open(item.data(QtCore.Qt.UserRole)))

        empty = _label("Aucun projet récent. Utilise « Parcourir » pour en ouvrir un.", "hint")
        empty.setVisible(not self.recent_list.count())
        browse = QtWidgets.QPushButton("Parcourir...")
        browse.clicked.connect(self._browse_open)
        open_button = QtWidgets.QPushButton("Ouvrir")
        open_button.setObjectName("primary")
        open_button.clicked.connect(self._open_selected)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(browse)
        buttons.addStretch()
        buttons.addWidget(open_button)

        layout = QtWidgets.QVBoxLayout(tab)
        layout.addWidget(self.search)
        layout.addWidget(self.recent_list)
        layout.addWidget(empty)
        layout.addWidget(_label("Ouvre la dernière scène du projet et remet $JOB et $CACHE.", "hint"))
        layout.addLayout(buttons)
        return tab

    def _filter_recent(self, text):
        for i in range(self.recent_list.count()):
            item = self.recent_list.item(i)
            item.setHidden(text.lower() not in item.text().lower())

    def _open_selected(self):
        item = self.recent_list.currentItem()
        if item and not item.isHidden():
            self._open(item.data(QtCore.Qt.UserRole))

    def _browse_open(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Dossier d'un projet MKE")
        if not path:
            return
        info = mke_project.find_project(path)
        if not info:
            hou.ui.displayMessage("Ce dossier n'est pas un projet MKE (pas de PIPELINE/project.json).",
                                  severity=hou.severityType.Warning)
            return
        self._open(info["root"])

    def _open(self, root):
        if hou.hipFile.hasUnsavedChanges():
            if hou.ui.displayMessage("La scène ouverte a des changements non sauvegardés.",
                                     buttons=("Ouvrir quand même", "Annuler"), default_choice=1, close_choice=1) == 1:
                return
        info, scene = mke_project.open_project(root)
        self.accept()
        hou.ui.setStatusMessage(f"Projet {info['name']} : {os.path.basename(scene) if scene else 'aucune scène, variables définies'}")

    # ------------------------------------------------------------ shots and assets
    def _entities_tab(self):
        tab = QtWidgets.QWidget()
        self.seq_input = QtWidgets.QLineEdit()
        self.seq_input.setPlaceholderText("Séquence, ex : SEQ010")
        self.shot_input = QtWidgets.QLineEdit()
        self.shot_input.setPlaceholderText("Plan, ex : SH0010")
        shot_button = QtWidgets.QPushButton("Ajouter le plan")
        shot_button.clicked.connect(lambda: self._add_entity("shot", seq=self.seq_input.text(), shot=self.shot_input.text()))
        self.shot_input.returnPressed.connect(shot_button.click)
        self.asset_input = QtWidgets.QLineEdit()
        self.asset_input.setPlaceholderText("Nom de l'asset, ex : Rocher")
        asset_button = QtWidgets.QPushButton("Ajouter l'asset")
        asset_button.clicked.connect(lambda: self._add_entity("asset", asset=self.asset_input.text()))
        self.asset_input.returnPressed.connect(asset_button.click)

        shot_row = QtWidgets.QHBoxLayout()
        shot_row.addWidget(self.seq_input)
        shot_row.addWidget(self.shot_input)
        shot_row.addWidget(shot_button)
        asset_row = QtWidgets.QHBoxLayout()
        asset_row.addWidget(self.asset_input)
        asset_row.addWidget(asset_button)
        self.entity_tree = QtWidgets.QTreeWidget()
        self.entity_tree.setHeaderHidden(True)
        self.no_project = _label("Crée ou ouvre un projet pour ajouter des plans et des assets.", "hint")

        self.entity_form = QtWidgets.QWidget()
        form = QtWidgets.QVBoxLayout(self.entity_form)
        form.setContentsMargins(0, 0, 0, 0)
        form.addWidget(_section("Nouveau plan"))
        form.addLayout(shot_row)
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
        shots = QtWidgets.QTreeWidgetItem(self.entity_tree, [f"Plans ({len(info['shots'])})"])
        sequences = {}
        for entry in info["shots"]:
            seq, shot = entry.split("/")
            if seq not in sequences:
                sequences[seq] = QtWidgets.QTreeWidgetItem(shots, [seq])
            QtWidgets.QTreeWidgetItem(sequences[seq], [shot])
        assets = QtWidgets.QTreeWidgetItem(self.entity_tree, [f"Assets ({len(info['assets'])})"])
        for asset in info["assets"]:
            QtWidgets.QTreeWidgetItem(assets, [asset])
        self.entity_tree.expandAll()

    def _add_entity(self, kind, **names):
        info = self.current_project()
        if not info:
            return
        try:
            created = mke_project.add_entity(info, kind, **names)
        except ValueError:
            hou.ui.displayMessage("Remplis tous les champs.", severity=hou.severityType.Warning)
            return
        self._refresh_entities(info)
        hou.ui.setStatusMessage(f"{'/'.join(names.values())} : {len(created)} dossiers créés")


_dialog = None


def projectSetup(tab=None):
    """tab: 0 create, 1 open, 2 shots and assets. Default: Open if there are recent projects, else Create."""
    global _dialog
    if _dialog is not None:
        _dialog.close()
    _dialog = ProjectSetupDialog(hou.qt.mainWindow())
    if tab is None:
        tab = 1 if _dialog.recent_list.count() else 0
    _dialog.tabs.setCurrentIndex(tab)
    _dialog.show()
    return _dialog
