import hou

import mke_project


def saveUp():
    if hou.hipFile.isNewFile():
        hou.ui.displayMessage("Please save the scene first.")
        return
    choice, comment = hou.ui.readInput("Comment for this version (optional):", buttons=("Save", "Cancel"),
                                       default_choice=0, close_choice=1, title="Save Up")
    if choice == 1:
        return
    new_path = mke_project.save_version(comment.strip())
    hou.ui.setStatusMessage(f"Saved: {new_path}")
