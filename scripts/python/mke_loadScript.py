"""
MKE Tools - Load Python Script
Opens a file browser to select and execute a Python script
"""
import hou
import os

def loadScript():
    """Open file dialog to select and execute a Python script"""
    print("Loading script...")
    #open file browser
    script_path = hou.ui.selectFile(
        start_directory=hou.expandString("$HIP"),
        title="Select the python script to load",
        collapse_sequences=False,
        file_type=hou.fileType.Any,
        pattern="*.py",
        default_value="",
        multiple_select=False,
        image_chooser=False
    )
    
    #check if user selected a file
    if not script_path:
        return
    
    #expand environment variables
    script_path = hou.expandString(script_path)
    
    if not os.path.exists(script_path):
        hou.ui.displayMessage(f"File not found: {script_path}", severity=hou.severityType.Error)
        return
    
    # Execute the script
    try:
        with open(script_path, 'r') as f:
            script_code = f.read()
        
        exec(script_code, globals())
        
        hou.ui.displayMessage(f"Successfully loaded: {os.path.basename(script_path)}", severity=hou.severityType.Message)
        print(f"Loaded script: {script_path}")
        
    except Exception as e:
        hou.ui.displayMessage(f"Error executing script:\n{str(e)}", severity=hou.severityType.Error)
        print(f"Error loading script: {e}")
