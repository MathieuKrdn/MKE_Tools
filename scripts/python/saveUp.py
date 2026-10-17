import hou

import mke_project


def saveUp():
    current_path = hou.hipFile.path()
    if hou.hipFile.isNewFile():
        hou.ui.displayMessage("Veuillez d'abord enregistrer la scène.")
        return
    new_path = mke_project.free_version_path(mke_project.version_up_path(current_path))
    hou.hipFile.save(new_path)
    hou.ui.setStatusMessage(f"Saved: {new_path}")
