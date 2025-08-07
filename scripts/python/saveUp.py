import hou
import re
import os

def saveUp():
    # Get current .hip file path
    current_path = hou.hipFile.path()

    # If the scene is unsaved, ask for a location
    if current_path == "untitled.hip":
        hou.ui.displayMessage("Veuillez d'abord enregistrer la scène.")
    else:
        # Split path and extension
        base, ext = os.path.splitext(current_path)
        # Regex to find _v#### at the end
        match = re.search(r'_v(\d{4})$', base)
        if match:
            # Increment version
            version = int(match.group(1)) + 1
            new_base = re.sub(r'_v\d{4}$', f'_v{version:04d}', base)
        else:
            # Add _v0001
            new_base = base + "_v0001"
        new_path = new_base + ext

        # Save the scene with the new version
        if new_path:
            hou.hipFile.save(new_path)