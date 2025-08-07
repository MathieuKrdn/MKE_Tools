import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

# Import the backend worker logic from the other file
from worker import RatConversionWorker

from PySide2 import QtCore, QtWidgets, QtCore, QtGui
# UI WINDOW
class RatGeneratorUI(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super(RatGeneratorUI, self).__init__(parent)
        # Setup ui
        self.setWindowTitle("RAT Texture Generator")
        self.setParent(parent, QtCore.Qt.Window)
        self.setStyleSheet(UI_STYLESHEET)
        self.setMinimumSize(600, 250)
        self.thread = None
        self.worker = None

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(20, 20, 20, 20)
        self.main_layout.setSpacing(15)

        dir_layout = QtWidgets.QHBoxLayout()
        self.dir_line_edit = QtWidgets.QLineEdit()
        self.dir_line_edit.setPlaceholderText("Select a directory containing textures...")
        self.browse_button = QtWidgets.QPushButton("Browse")
        dir_layout.addWidget(self.dir_line_edit)
        dir_layout.addWidget(self.browse_button)
        
        options_layout = QtWidgets.QHBoxLayout()
        self.subfolders_checkbox = QtWidgets.QCheckBox("Search in Subfolders")
        self.subfolders_checkbox.setChecked(True)
        self.batch_label = QtWidgets.QLabel("Threads:")
        self.batch_spinbox = QtWidgets.QSpinBox()
        self.batch_spinbox.setMinimum(1)
        self.batch_spinbox.setValue(os.cpu_count() // 2 or 1)
        self.batch_spinbox.setMaximum(os.cpu_count() or 1)
        options_layout.addWidget(self.subfolders_checkbox)
        options_layout.addStretch()
        options_layout.addWidget(self.batch_label)
        options_layout.addWidget(self.batch_spinbox)
        
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setVisible(False)
        self.status_label = QtWidgets.QLabel("Ready to start.")
        self.status_label.setObjectName("status_label")
        self.status_label.setAlignment(QtCore.Qt.AlignCenter)
        
        self.generate_button = QtWidgets.QPushButton("Generate RATs")
        self.generate_button.setObjectName("generate_button")
        
        self.main_layout.addLayout(dir_layout)
        self.main_layout.addLayout(options_layout)
        self.main_layout.addSpacing(10)
        self.main_layout.addWidget(self.status_label)
        self.main_layout.addWidget(self.progress_bar)
        self.main_layout.addWidget(self.generate_button)

        self.browse_button.clicked.connect(self.browse_for_directory)
        self.generate_button.clicked.connect(self.start_conversion)
        
    def browse_for_directory(self):
        # Directory
        directory = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Texture Directory")
        if directory:
            self.dir_line_edit.setText(directory)

    def start_conversion(self):
        # start worker 
        folder = self.dir_line_edit.text()
        if not os.path.isdir(folder):
            # Assumes 'hou' module is available in the execution environment (e.g., Houdini)
            try:
                import hou
                hou.ui.displayMessage("Error: Please select a valid directory first.", severity=hou.severityType.Error)
            except ImportError:
                print("Error: Please select a valid directory first.")
            return

        self.set_ui_enabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.generate_button.setText("Cancel")
        self.generate_button.clicked.disconnect()
        self.generate_button.clicked.connect(self.cancel_conversion)

        # multithread assignment
        self.thread = QtCore.QThread()
        self.worker = RatConversionWorker( # This class is now imported from worker.py
            folder=folder,
            use_subfolders=self.subfolders_checkbox.isChecked(),
            max_workers=self.batch_spinbox.value()
        )
        self.worker.moveToThread(self.thread)

        self.worker.signals.scan_complete.connect(self.on_scan_complete)
        self.worker.signals.progress_update.connect(self.update_progress)
        self.worker.signals.status_update.connect(self.update_status)
        self.worker.signals.finished.connect(self.on_conversion_finished)
        self.thread.started.connect(self.worker.run)

        self.thread.start()

    def cancel_conversion(self):
        self.status_label.setText("Cancelling...")
        if self.worker:
            self.worker.is_cancelled = True
        self.generate_button.setEnabled(False)

    def on_conversion_finished(self):
        self.thread.quit()
        self.thread.wait()
        self.thread = None
        self.worker = None
        self.close()

    def set_ui_enabled(self, is_enabled):
        self.dir_line_edit.setEnabled(is_enabled)
        self.browse_button.setEnabled(is_enabled)
        self.subfolders_checkbox.setEnabled(is_enabled)
        self.batch_spinbox.setEnabled(is_enabled)

    @QtCore.Slot(int)
    def on_scan_complete(self, total_files):
        # Create the progress bar
        if total_files > 0:
            self.progress_bar.setMaximum(total_files)
            self.status_label.setText(f"Found {total_files} files to convert.")
        else:
            self.progress_bar.setMaximum(1) # Avoid division error

    @QtCore.Slot(int)
    def update_progress(self, current_value):
        # progress set value
        self.progress_bar.setValue(current_value)

    @QtCore.Slot(str)
    def update_status(self, text):
        self.status_label.setText(text)

    def closeEvent(self, event):
        if self.thread and self.thread.isRunning():
            self.cancel_conversion()
            self.thread.quit()
            self.thread.wait()
        event.accept()

# MAIN - This block runs the UI.
# It is designed to run within an environment like Houdini that has a 'hou' module
# and a running QApplication instance.
if __name__ == '__main__':
    # This part is for running the script standalone for testing purposes
    # It will not use the Houdini main window.
    app = QtWidgets.QApplication(sys.argv)
    ui = RatGeneratorUI()
    ui.show()
    sys.exit(app.exec_())

# WORKER Signal
class WorkerSignals(QtCore.QObject):
    """
    Define signals for the worker thread.
    - scan_complete: Emits total file count after scanning.
    - progress_update: Emits the number of files converted so far.
    - status_update: Emits a string for the status label ui.
    - finished: Signals the entire process is done.
    """
    scan_complete = QtCore.Signal(int)
    progress_update = QtCore.Signal(int)
    status_update = QtCore.Signal(str)
    finished = QtCore.Signal()


# WORKER
class RatConversionWorker(QtCore.QObject):
    def __init__(self, folder, use_subfolders, max_workers):
        super(RatConversionWorker, self).__init__()
        self.signals = WorkerSignals()
        self.folder = folder
        self.use_subfolders = use_subfolders
        self.max_workers = max_workers
        self.is_cancelled = False

    @QtCore.Slot()
    def run(self):
        # Scan root and return the number of files
        self.signals.status_update.emit("Scanning for image files...")
        image_files = self._find_files()
        total_files = len(image_files)
        self.signals.scan_complete.emit(total_files)

        if self.is_cancelled:
            self.signals.finished.emit()
            return
            
        if not image_files:
            self.signals.status_update.emit("No new image files found to convert.")
            time.sleep(1.5)
            self.signals.finished.emit()
            return

        # STAGE 2: Convert files and report progress for each one.
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # enumerate the count of completed tasks
            for i, _ in enumerate(executor.map(self._convert_single_file, image_files)):
                if self.is_cancelled:
                    self.signals.status_update.emit(f"Cancelled. Processed {i} of {total_files} files.")
                    break
                # number of files done
                self.signals.progress_update.emit(i + 1)
        
        if not self.is_cancelled:
            self.signals.status_update.emit(f"Successfully converted {total_files} files.")
        
        time.sleep(1.5)
        self.signals.finished.emit()

    def _find_files(self):
        # find files based on extension (with or without subfolder process)
        valid_extensions = (".exr", ".tif", ".tiff", ".png", ".jpg", ".jpeg")
        files_to_process = []
        if self.use_subfolders:
            for root, _, files in os.walk(self.folder):
                for f in files:
                    if f.lower().endswith(valid_extensions):
                        files_to_process.append(os.path.join(root, f))
        else:
            for f in os.listdir(self.folder):
                path = os.path.join(self.folder, f)
                if os.path.isfile(path) and f.lower().endswith(valid_extensions):
                    files_to_process.append(path)
        return files_to_process

    def _convert_single_file(self, image_path):
        # convert process
        if self.is_cancelled:
            return
        base_name = os.path.basename(image_path)
        self.signals.status_update.emit(f"Converting: {base_name}")
        rat_path = f"{os.path.splitext(image_path)[0]}.rat"
        cmd = ["iconvert", image_path, rat_path]
        try:
            creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            subprocess.run(cmd, check=True, creationflags=creation_flags, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            print(f"Error converting {base_name}: {e.stderr}")
        except FileNotFoundError:
            self.signals.status_update.emit("'iconvert' not found")
            self.is_cancelled = True