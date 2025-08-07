import os
import hou
from PySide2.QtWidgets import QFileDialog, QDialog, QVBoxLayout, QCheckBox, QPushButton, QLabel, QApplication, QLineEdit, QHBoxLayout, QComboBox

class FolderSelectionDialog(QDialog):
    def __init__(self, folders, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choisissez les dossiers à créer")
        self.resize(500, 400)  # Set a bigger default size
        self.setMinimumSize(400, 300)
        self.selected_folders = []
        self.checkboxes = []
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Sélectionnez les dossiers à créer :"))

        # Zone pour les checkboxes
        self.cb_layout = QVBoxLayout()
        for folder in folders:
            cb = QCheckBox(folder)
            cb.setChecked(True)
            self.checkboxes.append(cb)
            self.cb_layout.addWidget(cb)
        layout.addLayout(self.cb_layout)

        # Ajout d'un champ texte + bouton pour ajouter un dossier
        add_layout = QHBoxLayout()
        self.folder_input = QLineEdit()
        self.folder_input.setPlaceholderText("Ajouter un dossier (ex: assets/new)")
        btn_add = QPushButton("Ajouter")
        btn_add.clicked.connect(self.add_folder)
        add_layout.addWidget(self.folder_input)
        add_layout.addWidget(btn_add)
        layout.addLayout(add_layout)

        btn_ok = QPushButton("OK")
        btn_ok.clicked.connect(self.accept)
        layout.addWidget(btn_ok)
        self.setLayout(layout)

    def add_folder(self):
        folder_name = self.folder_input.text().strip()
        if folder_name and folder_name not in [cb.text() for cb in self.checkboxes]:
            cb = QCheckBox(folder_name)
            cb.setChecked(True)
            self.checkboxes.append(cb)
            self.cb_layout.addWidget(cb)
            self.folder_input.clear()

    def get_selected_folders(self):
        return [cb.text() for cb in self.checkboxes if cb.isChecked()]

class ProjectInfoDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Informations du projet")
        self.resize(600, 250)  # Less tall, still wide
        self.setMinimumSize(400, 180)
        layout = QVBoxLayout()

        # Nom du projet
        layout.addWidget(QLabel("Nom du projet :"))
        self.name_input = QLineEdit()
        layout.addWidget(self.name_input)

        # Type de projet
        layout.addWidget(QLabel("Type de projet :"))
        self.type_combo = QComboBox()
        self.type_combo.addItems(["ASSET", "CHARACTER", "ENVIRONEMENT", "FX", "RND", "Other"])
        layout.addWidget(self.type_combo)

        # Champ pour "Other"
        self.other_input = QLineEdit()
        self.other_input.setPlaceholderText("Précisez le type de projet")
        self.other_input.setVisible(False)
        layout.addWidget(self.other_input)

        self.type_combo.currentTextChanged.connect(self.on_type_changed)

        # Boutons
        btn_ok = QPushButton("OK")
        btn_ok.clicked.connect(self.accept)
        layout.addWidget(btn_ok)
        self.setLayout(layout)

    def on_type_changed(self, text):
        self.other_input.setVisible(text == "Other")

    def get_project_info(self):
        name = self.name_input.text().strip()
        type_ = self.type_combo.currentText()
        if type_ == "Other":
            type_ = self.other_input.text().strip()
        return name, type_

class CachePathDialog(QDialog):
    def __init__(self, default_cache, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Définir le dossier de cache")
        self.resize(500, 150)  # Set a bigger default size
        self.setMinimumSize(400, 120)
        layout = QVBoxLayout()
        hlayout = QHBoxLayout()
        layout.addWidget(QLabel("Chemin du dossier de cache ($CACHE) :"))
        self.cache_input = QLineEdit(default_cache)
        btn_browse = QPushButton("Parcourir")
        btn_browse.clicked.connect(self.browse)
        hlayout.addWidget(self.cache_input)
        hlayout.addWidget(btn_browse)
        layout.addLayout(hlayout)
        btn_ok = QPushButton("OK")
        btn_ok.clicked.connect(self.accept)
        layout.addWidget(btn_ok)
        self.setLayout(layout)

    def browse(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Choisir le dossier de cache")
        if dir_path:
            # Convert absolute path to relative if inside project, else keep absolute
            project_root = os.path.dirname(os.path.dirname(self.cache_input.text()))
            try:
                rel_path = os.path.relpath(dir_path, project_root)
                self.cache_input.setText(rel_path)
            except Exception:
                self.cache_input.setText(dir_path)

    def get_cache_path(self):
        return self.cache_input.text().strip()

# 1. Demander à l'utilisateur le chemin du projet
def projectSetup():
    project_path = QFileDialog.getExistingDirectory(None, "Choisir le dossier du projet")

    if not project_path:
        hou.ui.displayMessage("Aucun dossier choisi. Action annulée.")
    else:
        # 2. Fenêtre pour nom + type de projet
        app = QApplication.instance() or QApplication([])
        info_dlg = ProjectInfoDialog()
        if not info_dlg.exec_():
            hou.ui.displayMessage("Action annulée.")
        else:
            project_name, project_type = info_dlg.get_project_info()
            if not project_name:
                hou.ui.displayMessage("Nom du projet vide. Action annulée.")
            else:
                base_path = os.path.join(project_path, project_name)

                # Demander le chemin du dossier cache
                default_cache = "3D/CACHES"
                cache_dlg = CachePathDialog(default_cache)
                if not cache_dlg.exec_():
                    hou.ui.displayMessage("Action annulée.")
                else:
                    cache_path = cache_dlg.get_cache_path()
                    if not cache_path:
                        cache_path = default_cache
                    cache_path = cache_path.strip()

                    # Définir les variables d'environnement $JOB, $HIP, $CACHE
                    hou.putenv("JOB", base_path)
                    hou.putenv("HIP", base_path)
                    hou.putenv("CACHE", os.path.join(base_path, cache_path))

                    folders = [
                        cache_path,
                        "3D/SCENES",
                        "USD",
                        "PIPELINE",
                        "REFERENCES",
                        "_DAILIES",
                        "IN/ASSETS",
                        "IN/PROPS",
                        "IN/CHARACTERS",
                        "IN/ENVIRONMENT",
                        "IN/CAMERAS",
                        "IN/TEXTURES",
                        f"OUT/{project_type}",
                    ]

                    # Si le chemin cache n'est pas le défaut, retirer "3D/CACHES" de la liste
                    if cache_path != default_cache and default_cache in folders:
                        folders.remove(default_cache)

                    # Afficher la boîte de dialogue de sélection
                    dlg = FolderSelectionDialog(folders)
                    if dlg.exec_():
                        selected_folders = dlg.get_selected_folders()
                        created = []
                        for folder in selected_folders:
                            full_path = os.path.join(base_path, folder)
                            try:
                                os.makedirs(full_path, exist_ok=True)
                                created.append(full_path)
                            except Exception as e:
                                hou.ui.displayMessage(f"Erreur lors de la création de {folder} : {str(e)}")

                        # Save first version of the .hip file
                        import getpass
                        user_name = getpass.getuser()
                        hip_name = f"{project_name}_{project_type}_{user_name}_v0001.hip"
                        hip_path = os.path.join(base_path, "3D", "SCENES", hip_name)
                        try:
                            hou.hipFile.save(hip_path)

                        except Exception as e:
                            hou.ui.displayMessage(f"Erreur lors de la sauvegarde du fichier .hip : {str(e)}")

                        hou.ui.displayMessage(
                                f"Structure créée dans :\n{base_path}\n({len(created)} dossiers)"
                                f"Projet initialisé !\n\n"
                                f"$JOB = {base_path}\n"
                                f"$HIP = {base_path}\n"
                                f"$CACHE = {os.path.join(base_path, cache_path)}\n"
                                f"Fichier .hip sauvegardé dans :\n{hip_path}"
                            )
                    else:
                        hou.ui.displayMessage("Action annulée.")

