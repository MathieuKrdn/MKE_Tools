import hou

import mke_project


def saveUp():
    if hou.hipFile.isNewFile():
        hou.ui.displayMessage("Please save the scene first.")
        return
    if hou.licenseCategory().name() in mke_project.NON_COMMERCIAL and hou.ui.displayMessage(
            "Houdini is not in Indie: this version would be saved as a non-commercial file.",
            buttons=("Cancel", "Save anyway"), default_choice=0, close_choice=0,
            severity=hou.severityType.Warning) == 0:
        return
    choice, comment = hou.ui.readInput("Comment for this version (optional):", buttons=("Save", "Cancel"),
                                       default_choice=0, close_choice=1, title="Save Up")
    if choice == 1:
        return
    new_path = mke_project.save_version(comment.strip())
    hou.ui.setStatusMessage(f"Saved: {new_path}")
