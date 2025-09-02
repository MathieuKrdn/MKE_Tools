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
        print(pool)
        writer.write("SecondaryPool={}\n".format(secondary_pool.strip('"')))
        print(secondary_pool)
        writer.write("Group={}\n".format(group.strip('"')))
        print(group)
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
        self.setWindowTitle("Deadline")
        self.setMinimumWidth(400)

        # Outer layout
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        title = QtWidgets.QLabel("Deadline")
        title.setStyleSheet("font-weight: bold;")
        layout.addWidget(title)

        # Form layout
        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignRight)
        form.setFormAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(4)

        # Main fields
        self.priority = QtWidgets.QSpinBox()
        self.priority.setRange(0, 100)
        self.priority.setValue(50)

        self.frames_per_task = QtWidgets.QSpinBox()
        self.frames_per_task.setRange(1, 50)
        self.frames_per_task.setValue(1)

        self.timeout = QtWidgets.QSpinBox()
        self.timeout.setRange(1, 9999)
        self.timeout.setValue(180)

        self.submit_suspended = QtWidgets.QCheckBox()

        self.machine_limit = QtWidgets.QSpinBox()
        self.machine_limit.setRange(0, 100)

        # Add fields to form
        form.addRow("Priority:", self.priority)
        form.addRow("Frames per Task:", self.frames_per_task)
        form.addRow("Task Timeout (min):", self.timeout)
        form.addRow("Submit suspended:", self.submit_suspended)
        form.addRow("Machine Limit:", self.machine_limit)

        layout.addLayout(form)

        # Submit button
        self.submit_btn = QtWidgets.QPushButton("Submit")
        self.submit_btn.setFixedHeight(28)
        layout.addWidget(self.submit_btn, alignment=QtCore.Qt.AlignHCenter)
        print(scene_file)
        print(frame_range)
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
        # Create a message box to show submission status
        msg_box = QtWidgets.QMessageBox(self)
        msg_box.setWindowTitle("Please wait")
        msg_box.setText("Submitting to Deadline...")
        msg_box.setStandardButtons(QtWidgets.QMessageBox.NoButton)
        msg_box.setMinimumSize(600, 300)
        msg_box.show()
    
        QtCore.QTimer.singleShot(1000, msg_box.accept)  # Ferme après 1 seconde
        
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
            suspended=False,
            exr_save_path=self.exr_save_path,
            startFrame=self.startFrame,
            endFrame=self.endFrame,
            IncFrame=self.IncFrame,
            version=self.version,
            group=self.group,
            pool=self.pool,
            secondary_pool=self.secondary_pool,
            hda=self.hda,
            renderName=self.renderName
        ))
        QtCore.QTimer.singleShot(1000, self.accept)  # Close main dialog after 1 second

#---------------- USEFUL DEFINITIONS ----------------#
