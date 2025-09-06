from ast import arguments
import hou
from PySide2 import QtWidgets, QtCore, QtGui
import subprocess
import tempfile
import os
import time
import logging
import re
import mke_utils


LoggingMap = {
    "info": "Info",
    "warning": "Warning",
    "error": "Error",
    "debug": "Debug",
    0: "Info",
    1: "Warning",
    2: "Error",
    3: "Debug"
}
VERSION_REGEX = re.compile(r'v(\d{4})')

scriptDialog = None
ProjectManagementOptions = None
settings = None
shotgunPath = None
startup = None
versionID = None
deadlineJobID = None

logger = logging.getLogger(__name__)

#---------------- DEADLINE SUBMITTER ----------------#
def submitPythonJob(self, hda, jobName, jobOutput="", jobPool="", jobSndPool="", jobGroup="",
                    jobPrio=0, jobTimeOut=0, jobMachineLimit=0, jobFramesPerTask=0, jobComment="", jobBatchName="", frames=0,
                    suspended=False, dependencies=[], jobDependencies=[], environment={},
                    args=[], state="", exr_save_path="", startFrame=0, endFrame=0, IncFrame=1, renderName="", version="", group="", pool="", secondary_pool="", renderEngine=""):
    """
    Function to submit a Python job to Deadline.
    """
    hip_file = hou.hipFile.name()
    hip_name = os.path.splitext(os.path.basename(hip_file))[0]
    #Create Job file
    jobInfoFilename = os.path.join(tempfile.gettempdir(), "usd_job_info.job")
    with open(jobInfoFilename, "w", encoding="utf-8") as writer:
        writer.write("Plugin=HuskStandalone\n")
        #writer.write("HouVersion={}\n".format(hou.applicationVersionString()[:-4]))
        writer.write("Name={}\n".format("["+hip_name.upper()+"] "+jobName+ "_" + version))
        writer.write("Comment={}\n".format(hip_name+" "+jobName+ "_" + version))
        writer.write("Priority={}\n".format(jobPrio))
        writer.write("MachineLimit={}\n".format(jobMachineLimit))
        writer.write("Pool={}\n".format(pool.strip('"')))
        writer.write("SecondaryPool={}\n".format(secondary_pool.strip('"')))
        writer.write("Group={}\n".format(group.strip('"')))
        writer.write("TaskTimeoutMinutes={}\n".format(jobTimeOut))
        writer.write("ChunkSize={}\n".format(jobFramesPerTask))  # Use ChunkSize instead of FramesPerTask
        if suspended:
            writer.write("InitialStatus=Suspended\n")  # Use InitialStatus instead of SubmitSuspended
        if exr_save_path:
            writer.write("OutputFilename0={}\n".format(exr_save_path))  # Use OutputFilename0 instead of OutImage

        #writer.write("RenderEngine={}\n".format(renderEngine))  # Add render engine to environment

        # if a framerange overide is not specified then just grab the nsi file range from the files
        if self.IncFrame == 1:
            FrameList = "{0}-{1}".format(self.startFrame, self.endFrame)
        #elif "FML" in hda.name():
            #FrameList = "{0},{1},{2}".format(self.startFrame, self.IncFrame, self.endFrame)
            
        else:
            frames = []
            frames.append(str(self.startFrame))
            i = self.startFrame
            while i < self.endFrame:
                if i % self.IncFrame == 0:
                    frames.append(str(i))
                i += 1
            FrameList = ",".join(frames)

        writer.write("Frames={}\n".format(FrameList))

    # Create plugin info file.
    pluginInfoFilename = os.path.join(tempfile.gettempdir(), "USD_plugin_info.job")
    with open(pluginInfoFilename, "w", encoding="utf-8") as writer:
        writer.write("SceneFile={}\n".format(self.scene_file))
        writer.write("LogLevel={}\n".format(LoggingMap.get(getattr(self, "log_level", "info"), "Info")))
        writer.write("RenderEngine={}\n".format(renderEngine))  # Add render engine to environment
        if self.exr_save_path:
            writer.write("OutImage={}\n".format(self.exr_save_path))

    # Setup the command line arguments.
    arguments = [jobInfoFilename, pluginInfoFilename]

    # Now submit the job.
    deadline_cmd = r"C:\Program Files\Thinkbox\Deadline10\bin\DeadlineCommand.exe"
    results = subprocess.run([deadline_cmd] + arguments, capture_output=True, text=True)
    QtWidgets.QMessageBox.information(None, "Submission Results", results.stdout)
    hda.setColor(hou.Color((0, 1, 0)))  # Set color to green on successful submission
    hda.parm("exportexr").set(exr_save_path)


#---------------- WINDOW ----------------#
def get_main_window():
    return hou.ui.mainQtWindow()

class DeadlineSubmitUI(QtWidgets.QDialog):
    def __init__(self, parent=None, frame_range="", startFrame="", endFrame="", IncFrame="", scene_file="", exr_save_path="", renderName="", folder_path="", version="", group="", pool="", secondary_pool="", hda="", renderEngine=""):
        """ Initializes the Deadline Submit UI dialog."""
        super(DeadlineSubmitUI, self).__init__(parent)
        self.setWindowTitle("Deadline Submission")
        self.setMinimumWidth(450)
        self.setMinimumHeight(350)

        # DARK THEME STYLING - ORANGE ACCENT
        self.setStyleSheet("""
            QDialog {
                background-color: #2b2b2b;
                color: white;
            }
            QLabel {
                color: white;
                font-size: 12px;
            }
            QSpinBox {
                background-color: #404040;
                color: white;
                border: 1px solid #666666;
                padding: 4px;
                border-radius: 3px;
            }
            QSpinBox:focus {
                border: 2px solid #ff6b35;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: #505050;
                border: 1px solid #666666;
                width: 16px;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background-color: #606060;
            }
            QSpinBox::up-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-bottom: 4px solid white;
                width: 0px;
                height: 0px;
            }
            QSpinBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 4px solid white;
                width: 0px;
                height: 0px;
            }
            QCheckBox {
                color: white;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                background-color: #404040;
                border: 1px solid #666666;
                border-radius: 3px;
            }
            QCheckBox::indicator:checked {
                background-color: #ff6b35;
                border: 1px solid #e55a2b;
            }
            QCheckBox::indicator:checked::after {
                content: "✓";
                color: white;
                font-weight: bold;
            }
            QPushButton {
                background-color: #ff6b35;
                color: white;
                border: none;
                padding: 8px 20px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #e55a2b;
            }
            QPushButton:pressed {
                background-color: #cc4f24;
            }
            QPushButton:disabled {
                background-color: #404040;
                color: #888888;
            }
        """)

        # Outer layout
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Title without icon
        title_layout = QtWidgets.QHBoxLayout()
        title_text = QtWidgets.QLabel("Deadline Submission")
        title_text.setStyleSheet("font-weight: bold; font-size: 18px; color: #ff6b35;")
        title_layout.addWidget(title_text)
        title_layout.addStretch()
        layout.addLayout(title_layout)

        # Add separator line
        separator = QtWidgets.QFrame()
        separator.setFrameShape(QtWidgets.QFrame.HLine)
        separator.setFrameShadow(QtWidgets.QFrame.Sunken)
        separator.setStyleSheet("color: #666666;")
        layout.addWidget(separator)

        # Form layout with better spacing
        form_widget = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(form_widget)
        form.setLabelAlignment(QtCore.Qt.AlignRight)
        form.setFormAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        form.setHorizontalSpacing(15)
        form.setVerticalSpacing(12)

        # Main fields with better labels (no emojis)
        self.priority = QtWidgets.QSpinBox()
        self.priority.setRange(0, 100)
        self.priority.setValue(50)
        self.priority.setToolTip("Job priority (0-100, higher = more priority)")

        self.frames_per_task = QtWidgets.QSpinBox()
        self.frames_per_task.setRange(1, 50)
        self.frames_per_task.setValue(1)
        self.frames_per_task.setToolTip("Number of frames to render per task")

        self.timeout = QtWidgets.QSpinBox()
        self.timeout.setRange(1, 9999)
        self.timeout.setValue(180)
        self.timeout.setToolTip("Task timeout in minutes")

        self.machine_limit = QtWidgets.QSpinBox()
        self.machine_limit.setRange(0, 100)
        self.machine_limit.setValue(0)
        self.machine_limit.setToolTip("Maximum number of machines to use (0 = no limit)")

        self.submit_suspended = QtWidgets.QCheckBox()
        self.submit_suspended.setToolTip("Submit job in suspended state")

        # Add fields to form without emojis
        priority_label = QtWidgets.QLabel("Priority:")
        priority_label.setStyleSheet("font-weight: bold;")
        form.addRow(priority_label, self.priority)

        frames_label = QtWidgets.QLabel("Frames per Task:")
        frames_label.setStyleSheet("font-weight: bold;")
        form.addRow(frames_label, self.frames_per_task)

        timeout_label = QtWidgets.QLabel("Task Timeout (min):")
        timeout_label.setStyleSheet("font-weight: bold;")
        form.addRow(timeout_label, self.timeout)

        suspended_label = QtWidgets.QLabel("Submit Suspended:")
        suspended_label.setStyleSheet("font-weight: bold;")
        form.addRow(suspended_label, self.submit_suspended)

        machine_label = QtWidgets.QLabel("Machine Limit:")
        machine_label.setStyleSheet("font-weight: bold;")
        form.addRow(machine_label, self.machine_limit)

        layout.addWidget(form_widget)

        # Add some spacing
        layout.addStretch()

        # Submit button with better styling (no emoji)
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addStretch()
        
        self.submit_btn = QtWidgets.QPushButton("Submit to Deadline")
        self.submit_btn.setFixedHeight(40)
        self.submit_btn.setFixedWidth(200)
        button_layout.addWidget(self.submit_btn)
        button_layout.addStretch()
        
        layout.addLayout(button_layout)

        # Store parameters
        self.frame_range = frame_range
        self.scene_file = scene_file
        self.renderName = renderName
        self.startFrame = startFrame
        self.endFrame = endFrame
        self.IncFrame = IncFrame
        self.exr_save_path = exr_save_path
        self.folder_path = folder_path
        self.version = version
        self.group = group
        self.pool = pool
        self.secondary_pool = secondary_pool
        self.hda = hda
        self.renderEngine = renderEngine
        self.submit_btn.clicked.connect(self.on_submit_clicked)

    def on_submit_clicked(self):
        """Handles the submit button click event."""
        # Create a styled dark theme message box (no emoji)
        msg_box = QtWidgets.QMessageBox(self)
        msg_box.setWindowTitle("Deadline Submission")
        msg_box.setText("Submitting job to Deadline...")
        msg_box.setInformativeText("Please wait while your job is being submitted.")
        msg_box.setStandardButtons(QtWidgets.QMessageBox.NoButton)
        msg_box.setMinimumSize(400, 200)
        
        # Apply dark theme to message box
        msg_box.setStyleSheet("""
            QMessageBox {
                background-color: #2b2b2b;
                color: white;
            }
            QMessageBox QLabel {
                color: white;
                font-size: 13px;
            }
        """)
        
        msg_box.show()
    
        QtCore.QTimer.singleShot(1000, msg_box.accept)  # Close after 1 second
        
        # Call the function to submit the job
        QtCore.QTimer.singleShot(1000, lambda: submitPythonJob(
            self,
            jobName=self.renderName,
            jobOutput=None,
            jobPool="testing",
            jobSndPool="testing",
            jobGroup="None",
            jobPrio=self.priority.value(),
            jobTimeOut=self.timeout.value(),
            jobMachineLimit=self.machine_limit.value(),
            jobFramesPerTask=self.frames_per_task.value(),
            jobComment=None,
            frames="1",
            suspended=self.submit_suspended.isChecked(),  # Use the checkbox value
            exr_save_path=self.exr_save_path,
            startFrame=self.startFrame,
            endFrame=self.endFrame,
            IncFrame=self.IncFrame,
            version=self.version,
            group=self.group,
            pool=self.pool,
            secondary_pool=self.secondary_pool,
            hda=self.hda,
            renderName=self.renderName,
            renderEngine=self.renderEngine
        ))
        QtCore.QTimer.singleShot(1000, self.accept)  # Close main dialog after 1 second

