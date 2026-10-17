"""Project Setup window: new project, open a project, add shots and assets. Logic lives in mke_project."""
import os

import hou
from hutil.Qt import QtCore, QtWidgets

import mke_project

OTHER = "Other"


def _browse_row(line_edit, title, parent):
    row = QtWidgets.QHBoxLayout()
    button = QtWidgets.QPushButton("Parcourir")

    def browse():
        path = QtWidgets.QFileDialog.getExistingDirectory(parent, title, line_edit.text())
        if path:
            line_edit.setText(path)
    button.clicked.connect(browse)
    row.addWidget(line_edit)
    row.addWidget(button)
    return row


def _spin(minimum, maximum, value, double=False):
    spin = QtWidgets.QDoubleSpinBox() if double else QtWidgets.QSpinBox()
    spin.setRange(minimum, maximum)
    spin.setValue(value)
    return spin


class ProjectSetupDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("MKE Project Setup")
        self.resize(640, 720)
        self.presets = mke_project.load_presets()
        self.custom_folders = []

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self._new_tab(), "Nouveau projet")
        self.tabs.addTab(self._open_tab(), "Ouvrir un projet")
        self.tabs.addTab(self._entities_tab(), "Plans / Assets")
        self.tabs.currentChanged.connect(lambda i: self._refresh_entities() if i == 2 else None)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.tabs)

    # ------------------------------------------------------------ new project
    def _new_tab(self):
        tab = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout()

        self.parent_input = QtWidgets.QLineEdit(os.path.dirname(hou.getenv("JOB") or "") or os.path.expanduser("~"))
        form.addRow("Dossier parent :", _browse_row(self.parent_input, "Dossier parent du projet", self))
        self.name_input = QtWidgets.QLineEdit()
        self.name_input.setPlaceholderText("Nom du projet (espaces et accents seront remplacés)")
        form.addRow("Nom :", self.name_input)

        self.type_combo = QtWidgets.QComboBox()
        self.type_combo.addItems(list(self.presets["types"]) + [OTHER])
        self.other_input = QtWidgets.QLineEdit()
        self.other_input.setPlaceholderText("Type personnalisé")
        self.other_input.setVisible(False)
        type_row = QtWidgets.QHBoxLayout()
        type_row.addWidget(self.type_combo)
        type_row.addWidget(self.other_input)
        form.addRow("Type :", type_row)

        self.cache_input = QtWidgets.QLineEdit(self.presets["cache"])
        self.cache_input.setToolTip("Relatif au projet (3D/CACHES) ou chemin absolu (ex: D:/CACHES/projet)")
        form.addRow("Cache ($CACHE) :", _browse_row(self.cache_input, "Dossier de cache", self))

        d = self.presets["defaults"]
        self.fps = _spin(1, 240, d["fps"], double=True)
        self.start = _spin(-100000, 100000, d["frame_start"])
        self.end = _spin(-100000, 100000, d["frame_end"])
        self.res_x = _spin(16, 16384, d["resolution"][0])
        self.res_y = _spin(16, 16384, d["resolution"][1])
        timing = QtWidgets.QHBoxLayout()
        for label, widget in (("fps", self.fps), ("début", self.start), ("fin", self.end)):
            timing.addWidget(QtWidgets.QLabel(label))
            timing.addWidget(widget)
        form.addRow("Temps :", timing)
        res = QtWidgets.QHBoxLayout()
        res.addWidget(self.res_x)
        res.addWidget(QtWidgets.QLabel("x"))
        res.addWidget(self.res_y)
        form.addRow("Résolution :", res)
        self.ocio_input = QtWidgets.QLineEdit(d.get("ocio", ""))
        self.ocio_input.setPlaceholderText("Fichier config.ocio (vide = défaut Houdini)")
        form.addRow("OCIO :", self.ocio_input)

        self.folder_list = QtWidgets.QListWidget()
        add_row = QtWidgets.QHBoxLayout()
        self.folder_input = QtWidgets.QLineEdit()
        self.folder_input.setPlaceholderText("Ajouter un dossier (ex: IN/AUDIO)")
        add_button = QtWidgets.QPushButton("Ajouter")
        add_button.clicked.connect(self._add_folder)
        self.folder_input.returnPressed.connect(self._add_folder)
        add_row.addWidget(self.folder_input)
        add_row.addWidget(add_button)

        self.starter_check = QtWidgets.QCheckBox("Scène de départ avec les HDA MKE dans /stage")
        self.starter_check.setChecked(True)
        self.keep_check = QtWidgets.QCheckBox("Garder la scène actuelle (sinon on part d'une scène vide)")
        self.warning = QtWidgets.QLabel()
        self.warning.setStyleSheet("color: #e0a030;")
        self.warning.setWordWrap(True)

        buttons = QtWidgets.QHBoxLayout()
        create = QtWidgets.QPushButton("Créer le projet")
        create.setDefault(True)
        create.clicked.connect(self._create)
        cancel = QtWidgets.QPushButton("Annuler")
        cancel.clicked.connect(self.reject)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(create)

        layout = QtWidgets.QVBoxLayout(tab)
        layout.addLayout(form)
        layout.addWidget(QtWidgets.QLabel("Dossiers à créer :"))
        layout.addWidget(self.folder_list)
        layout.addLayout(add_row)
        layout.addWidget(self.starter_check)
        layout.addWidget(self.keep_check)
        layout.addWidget(self.warning)
        layout.addLayout(buttons)

        self.type_combo.currentTextChanged.connect(self._on_type_changed)
        self.other_input.textChanged.connect(self._refresh_folders)
        self.cache_input.textChanged.connect(self._refresh_folders)
        self.parent_input.textChanged.connect(self._refresh_warning)
        self.name_input.textChanged.connect(self._refresh_warning)
        self._on_type_changed(self.type_combo.currentText())
        return tab

    def project_type(self):
        type_ = self.type_combo.currentText()
        return mke_project.sanitize_name(self.other_input.text()).upper() if type_ == OTHER else type_

    def _on_type_changed(self, type_):
        self.other_input.setVisible(type_ == OTHER)
        settings = mke_project.preset_settings(self.presets, type_)
        self.fps.setValue(settings["fps"])
        self.start.setValue(settings["frame_start"])
        self.end.setValue(settings["frame_end"])
        self.res_x.setValue(settings["resolution"][0])
        self.res_y.setValue(settings["resolution"][1])
        self._refresh_folders()

    def _refresh_folders(self):
        unchecked = {self.folder_list.item(i).text() for i in range(self.folder_list.count())
                     if self.folder_list.item(i).checkState() != QtCore.Qt.Checked}
        self.folder_list.clear()
        folders = mke_project.preset_folders(self.presets, self.project_type() or "OTHER", self.cache_input.text().strip())
        for folder in folders + self.custom_folders:
            if os.path.isabs(folder):
                continue  # an absolute cache is created on its own
            item = QtWidgets.QListWidgetItem(folder)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Unchecked if folder in unchecked else QtCore.Qt.Checked)
            self.folder_list.addItem(item)

    def _add_folder(self):
        folder = self.folder_input.text().strip().replace("\\", "/").strip("/")
        if folder and folder not in self.custom_folders:
            self.custom_folders.append(folder)
            self._refresh_folders()
        self.folder_input.clear()

    def _refresh_warning(self):
        name = mke_project.sanitize_name(self.name_input.text())
        root = os.path.join(self.parent_input.text(), name)
        messages = []
        if name and name != self.name_input.text().strip():
            messages.append(f"Le projet s'appellera « {name} ».")
        if name and os.path.isfile(os.path.join(root, mke_project.PROJECT_FILE)):
            messages.append("Ce projet existe déjà : il sera proposé à l'ouverture au lieu d'être écrasé.")
        warning = mke_project.server_warning(root)
        if warning:
            messages.append(warning)
        self.warning.setText("\n".join(messages))

    def _create(self):
        type_ = self.project_type()
        if not mke_project.sanitize_name(self.name_input.text()) or not type_:
            hou.ui.displayMessage("Renseigne un nom et un type de projet.", severity=hou.severityType.Warning)
            return
        if not self.keep_check.isChecked() and hou.hipFile.hasUnsavedChanges():
            if hou.ui.displayMessage("La scène actuelle a des changements non sauvegardés et va être fermée.",
                                     buttons=("Continuer", "Annuler"), default_choice=1, close_choice=1) == 1:
                return
        folders = [self.folder_list.item(i).text() for i in range(self.folder_list.count())
                   if self.folder_list.item(i).checkState() == QtCore.Qt.Checked]
        settings = {"fps": self.fps.value(), "frame_start": self.start.value(), "frame_end": self.end.value(),
                    "resolution": [self.res_x.value(), self.res_y.value()], "ocio": self.ocio_input.text().strip()}
        try:
            info, hip = mke_project.create_project(
                self.parent_input.text(), self.name_input.text(), type_, folders, settings,
                self.cache_input.text().strip() or self.presets["cache"],
                keep_scene=self.keep_check.isChecked(), starter=self.starter_check.isChecked())
        except FileExistsError as existing:
            if hou.ui.displayMessage(f"Le projet existe déjà :\n{existing}\n\nL'ouvrir ?",
                                     buttons=("Ouvrir", "Annuler"), close_choice=1) == 0:
                self._open(str(existing))
            return
        except Exception as error:
            hou.ui.displayMessage(f"Erreur pendant la création : {error}", severity=hou.severityType.Error)
            return
        self.accept()
        hou.ui.displayMessage(
            f"Projet créé : {info['root']}\n\n"
            f"$JOB = {info['root']}\n$CACHE = {mke_project.cache_dir(info)}\n"
            f"{info['fps']:g} fps, frames {info['frame_start']}-{info['frame_end']}\n\n"
            f"Scène : {hip}")

    # ------------------------------------------------------------ open project
    def _open_tab(self):
        tab = QtWidgets.QWidget()
        self.recent_list = QtWidgets.QListWidget()
        self.recent_list.addItems(mke_project.recent_projects())
        self.recent_list.itemDoubleClicked.connect(lambda item: self._open(item.text()))
        browse = QtWidgets.QPushButton("Parcourir...")
        browse.clicked.connect(self._browse_open)
        open_button = QtWidgets.QPushButton("Ouvrir")
        open_button.clicked.connect(lambda: self.recent_list.currentItem() and self._open(self.recent_list.currentItem().text()))
        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(browse)
        buttons.addStretch()
        buttons.addWidget(open_button)
        layout = QtWidgets.QVBoxLayout(tab)
        layout.addWidget(QtWidgets.QLabel("Projets récents (double-clic pour ouvrir la dernière scène) :"))
        layout.addWidget(self.recent_list)
        layout.addLayout(buttons)
        return tab

    def _browse_open(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Dossier d'un projet MKE")
        if not path:
            return
        info = mke_project.find_project(path)
        if not info:
            hou.ui.displayMessage("Pas de PIPELINE/project.json dans ce dossier ni au-dessus.", severity=hou.severityType.Warning)
            return
        self._open(info["root"])

    def _open(self, root):
        if hou.hipFile.hasUnsavedChanges():
            if hou.ui.displayMessage("La scène actuelle a des changements non sauvegardés.",
                                     buttons=("Ouvrir quand même", "Annuler"), default_choice=1, close_choice=1) == 1:
                return
        info, scene = mke_project.open_project(root)
        self.accept()
        hou.ui.setStatusMessage(f"Projet {info['name']} : {scene or 'aucune scène, variables définies'}")

    # ------------------------------------------------------------ shots / assets
    def _entities_tab(self):
        tab = QtWidgets.QWidget()
        self.project_label = QtWidgets.QLabel()
        self.seq_input = QtWidgets.QLineEdit()
        self.seq_input.setPlaceholderText("SEQ010")
        self.shot_input = QtWidgets.QLineEdit()
        self.shot_input.setPlaceholderText("SH0010")
        shot_button = QtWidgets.QPushButton("Ajouter le plan")
        shot_button.clicked.connect(lambda: self._add_entity("shot", seq=self.seq_input.text(), shot=self.shot_input.text()))
        self.asset_input = QtWidgets.QLineEdit()
        self.asset_input.setPlaceholderText("Nom de l'asset")
        asset_button = QtWidgets.QPushButton("Ajouter l'asset")
        asset_button.clicked.connect(lambda: self._add_entity("asset", asset=self.asset_input.text()))
        self.entity_list = QtWidgets.QListWidget()

        shot_row = QtWidgets.QHBoxLayout()
        for widget in (self.seq_input, self.shot_input, shot_button):
            shot_row.addWidget(widget)
        asset_row = QtWidgets.QHBoxLayout()
        asset_row.addWidget(self.asset_input)
        asset_row.addWidget(asset_button)
        layout = QtWidgets.QVBoxLayout(tab)
        layout.addWidget(self.project_label)
        layout.addLayout(shot_row)
        layout.addLayout(asset_row)
        layout.addWidget(QtWidgets.QLabel("Plans et assets du projet :"))
        layout.addWidget(self.entity_list)
        return tab

    def current_project(self):
        job = hou.getenv("JOB")
        return mke_project.find_project(job) if job and os.path.isdir(job) else None

    def _refresh_entities(self):
        info = self.current_project()
        self.entity_list.clear()
        if not info:
            self.project_label.setText("Aucun projet MKE actif : crée ou ouvre un projet d'abord.")
            return
        self.project_label.setText(f"Projet actif : {info['name']}  ({info['root']})")
        self.entity_list.addItems([f"Plan  {s}" for s in info["shots"]] + [f"Asset {a}" for a in info["assets"]])

    def _add_entity(self, kind, **names):
        info = self.current_project()
        if not info:
            hou.ui.displayMessage("Aucun projet MKE actif.", severity=hou.severityType.Warning)
            return
        try:
            created = mke_project.add_entity(info, kind, **names)
        except ValueError as error:
            hou.ui.displayMessage(str(error), severity=hou.severityType.Warning)
            return
        self._refresh_entities()
        hou.ui.setStatusMessage(f"{len(created)} dossiers créés pour {'/'.join(names.values())}")


_dialog = None


def projectSetup(tab=0):
    global _dialog
    if _dialog is not None:
        _dialog.close()
    _dialog = ProjectSetupDialog(hou.qt.mainWindow())
    _dialog.tabs.setCurrentIndex(tab)
    _dialog.show()
    return _dialog
