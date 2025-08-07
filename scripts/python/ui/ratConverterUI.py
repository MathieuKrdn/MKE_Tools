import os
import sys

from PySide2 import QtWidgets, QtCore, QtGui

# Import the backend worker logic from the other file
from worker import RatConversionWorker

# STYLESHEET gemini
UI_STYLESHEET = """
QWidget {
    background-color: #2E2E2E;
    color: #E0E0E0;
    font-family: "Segoe UI", "Cantarell", "Arial", sans-serif;
    font-size: 10pt;
}
QMainWindow, QDialog {
    background-color: #252525;
}
QLineEdit {
    background-color: #3C3C3C;
    border: 1px solid #555;
    border-radius: 4px;
    padding: 6px;
    color: #F0F0F0;
}
QLineEdit:focus {
    border: 1px solid #77A6F7;
}
QPushButton {
    background-color: #4A4A4A;
    border: 1px solid #666;
    border-radius: 4px;
    padding: 6px 12px;
}
QPushButton:hover {
    background-color: #5A5A5A;
}
QPushButton:pressed {
    background-color: #3A3A3A;
}
QPushButton#generate_button {
    background-color: #4078D8;
    color: white;
    font-weight: bold;
    padding: 8px 15px;
}
QPushButton#generate_button:hover {
    background-color: #5C94F7;
}
QPushButton#generate_button:disabled {
    background-color: #3A4E69;
    color: #888;
}
QProgressBar {
    border: 1px solid #555;
    border-radius: 4px;
    text-align: center;
    color: white;
    background-color: #3C3C3C;
}
QProgressBar::chunk {
    background-color: #4078D8;
    border-radius: 3px;
    margin: 1px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
}
QCheckBox::indicator:unchecked {
    image: url(:/qt-project.org/styles/commonstyle/images/checkbox-unchecked-d.png);
}
QCheckBox::indicator:checked {
    image: url(:/qt-project.org/styles/commonstyle/images/checkbox-checked-d.png);
}
QSpinBox {
    background-color: #3C3C3C;
    border: 1px solid #555;
    border-radius: 4px;
    padding: 5px;
}
QLabel#status_label {
    color: #AAAAAA;
    font-size: 9pt;
}
"""

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

