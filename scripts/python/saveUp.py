import hou

import mke_project


def saveUp():
    if hou.hipFile.isNewFile():
        hou.ui.displayMessage("Veuillez d'abord enregistrer la scène.")
        return
    choice, comment = hou.ui.readInput("Commentaire pour cette version (optionnel) :", buttons=("Enregistrer", "Annuler"),
                                       default_choice=0, close_choice=1, title="Save Up")
    if choice == 1:
        return
    new_path = mke_project.save_version(comment.strip())
    hou.ui.setStatusMessage(f"Saved: {new_path}")
