import random
from typing import Optional, Union, List, Dict, Any
import hou
import re
import logging
from pathlib import Path
import shutil
from pxr import Usd, Sdf
import os
import json
from datetime import datetime
import subprocess
from PySide2 import QtWidgets, QtCore

VERSION_REGEX = re.compile(r'v(\d{4})')
USER_LOGIN = os.getlogin()


def sanitize_layer_name(name: str) -> str:
    """
    Sanitize layer name to be a valid Windows folder name.
    
    Args:
        name (str): Input layer name
        
    Returns:
        str: Sanitized layer name safe for Windows filesystem
    """
    if not name:
        return "DEFAULT_LAYER"
    
    # Remove invalid Windows folder characters
    sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)
    
    # Replace spaces with underscores and convert to uppercase
    sanitized = sanitized.replace(" ", "_").upper()
    
    # Remove multiple underscores
    sanitized = re.sub(r'_+', '_', sanitized)
    
    # Remove leading/trailing underscores and periods
    sanitized = sanitized.strip('_.')
    
    # Check for reserved Windows names
    reserved_names = ['CON', 'PRN', 'AUX', 'NUL'] + \
                    [f'COM{i}' for i in range(1, 10)] + \
                    [f'LPT{i}' for i in range(1, 10)]
    
    if sanitized in reserved_names:
        sanitized = f"{sanitized}_LAYER"
    
    # Ensure it's not empty after sanitization
    if not sanitized:
        sanitized = "DEFAULT_LAYER"

    return sanitized

def colorNetwork(layer_name: str) -> hou.Color:
    """
    Get a color for network box based on layer name.
    
    Args:
        layer_name (str): Name of the layer
        
    Returns:
        hou.Color: Color object for the network box
    """
    color_map = {
        "character": [1, 0, 0],        # Red
        "environment": [0, 0.5, 1],    # Blue
        "fx": [0.5, 0, 1],             # Purple
        "crowd": [1, 1, 0],            # Yellow
        "fur": [1, 0.5, 0],            # Orange
        "atmos": [0, 0.5, 0.5],        # Teal
        "global": [1, 1, 1]            # White
    }
    
    colors = color_map.get(layer_name.lower(), [random.random(), random.random(), random.random()])
    return hou.Color(colors)

def handle_error(message: str, hda: Optional[hou.Node] = None, color: tuple =(1, 0, 0)) -> None:
    """
    Logs an error and optionally sets the HDA color.
    
    Args:
        message (str): Error message to log
        hda (hou.Node, optional): HDA node to color
        color (tuple): RGB color tuple
    """
    logging.error(message)
    if hda:
        hda.setColor(hou.Color(color))

def create_directory(path: Union[str, Path], hda: Optional[hou.Node] = None) -> bool:
    """
    Creates a directory if it doesn't exist.
    
    Args:
        path (str|Path): Directory path to create
        hda (hou.Node, optional): HDA node for logging
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
        log_debug(f"Directory created or already exists: {path}", hda)
        return True
    except OSError as e:
        handle_error(f"Failed to create directory {path}: {e}", hda)
        return False

def is_debug_mode(hda: hou.Node) -> bool:
    """
    Checks if the debug mode is enabled on the HDA.
    
    Args:
        hda (hou.Node): HDA node to check
        
    Returns:
        bool: True if debug mode is enabled
    """
    try:
        return hda.parm("debugMode").eval() == 1
    except hou.OperationFailed:
        return False

def log_debug(message: str, hda: Optional[hou.Node] = None) -> None:
    """
    Logs a message if debug mode is enabled.
    
    Args:
        message (str): Debug message to log
        hda (hou.Node, optional): HDA node to check debug mode
    """
    if is_debug_mode(hda):
        logging.info(f"DEBUG: {message}")

def manage_version_directory(base_path: Union[str, Path], 
                           hda: hou.Node, 
                           override: bool = False) -> tuple[Optional[str], Optional[str]]:
    """
    Creates a new version directory or overrides an existing one.
    
    Args:
        base_path (str|Path): Base directory path for versions
        hda (hou.Node): HDA node for parameter access and logging
        override (bool): Whether to override existing version directory
        
    Returns:
        tuple[str|None, str|None]: (version_path, version_string) or (None, None) on error
    """
    base_path = Path(base_path)
    
    # Create the base directory if it doesn't exist
    if not base_path.exists():
        if not create_directory(base_path, hda):
            return None, None
        # If directory didn't exist, start with v0001
        version_str = "v0001"
        version_path = base_path / version_str
        if not create_directory(version_path, hda):
            return None, None
        # Create USD subdirectory
        usd_path = version_path / "USD"
        create_directory(usd_path, hda)
        return str(version_path), version_str
    
    if override:
        # Get version number from HDA parameter
        try:
            version_number = hda.parm("versionNumber").eval()
            if not isinstance(version_number, int) or version_number < 1:
                handle_error("Invalid version number from HDA parameter", hda)
                return None, None
        except hou.OperationFailed:
            handle_error("Could not read versionNumber parameter from HDA", hda)
            return None, None
            
        version_str = f"v{version_number:04d}"
        version_path = base_path / version_str
        
        # Remove existing directory if it exists
        if version_path.exists() and version_path.is_dir():
            try:
                shutil.rmtree(version_path)
                log_debug(f"Removed existing version directory: {version_path}", hda)
            except OSError as e:
                handle_error(f"Error deleting directory {version_path}: {e}", hda)
                return None, None
    else:
        # Find next available version number
        try:
            # Get all version directories and extract version numbers
            versions = []
            for d in base_path.iterdir():
                if d.is_dir():
                    match = VERSION_REGEX.match(d.name)
                    if match:
                        versions.append(int(match.group(1)))
        except (OSError, FileNotFoundError) as e:
            log_debug(f"Could not read directory contents: {e}", hda)
            versions = []
            
        # Calculate next version number
        next_version_number = max(versions) + 1 if versions else 1
        version_str = f"v{next_version_number:04d}"
        version_path = base_path / version_str

    # Create the version directory
    if not create_directory(version_path, hda):
        return None, None
    
    # Create USD subdirectory
    usd_path = version_path / "USD"
    if not create_directory(usd_path, hda):
        log_debug(f"Failed to create USD subdirectory in {version_path}", hda)
        # Don't fail the whole operation if USD dir creation fails
    
    log_debug(f"Successfully created version directory: {version_path}", hda)
    return str(version_path), version_str

def get_context_info(hda):
    """Gathers context information based on the operating mode."""
    save_dir = hda.parm('saveDir').eval()
    if not save_dir:
        handle_error("'Requires a 'Save Directory'.", hda)
        return None
    return {"base_path": Path(save_dir), "context_type": "filecache"}


def get_metadata(usd_file_path: Optional[Path] = None, metadata: Optional[str] = None, usd_content_string: Optional[str] = None) -> Union[str, None]:
    """
    Extract metadata from a USD file or USD content string.
    
    Args:
        usd_file_path (str, optional): Path to USD file
        metadata (str): Metadata key to extract
        usd_content_string (str, optional): USD content as string
        
    Returns:
        str or None: Metadata value or error message
    """
    if not metadata:
        return "Error: metadata parameter is required."
    
    if not usd_file_path and not usd_content_string:
        return "Error: Either usd_file_path or usd_content_string must be provided."

    stage = None
    
    try:
        if usd_file_path:
            if not Path(usd_file_path).exists():
                return f"Error: USD file does not exist: {usd_file_path}"
            stage = Usd.Stage.Open(usd_file_path)
        elif usd_content_string:
            # Create a temporary in-memory layer from the string content
            layer = Sdf.Layer.CreateAnonymous(".usda")
            layer.ImportFromString(usd_content_string)
            stage = Usd.Stage.Open(layer)
            
    except Exception as e:
        source = "file" if usd_file_path else "string"
        return f"Error opening USD {source}: {str(e)}"

    if not stage:
        return "Failed to open or create USD stage."
        
    root_layer = stage.GetRootLayer()
    if not root_layer:
        return "Could not get the root layer of the USD stage."
        
    custom_data = root_layer.customLayerData
    if not custom_data:
        return "No customLayerData found on the root layer."
        
    return custom_data.get(metadata)
    
# --- User Information ---

def get_formatted_user_name() -> str:
    """
    Returns the user's formatted full name.
    
    Returns:
        str: Formatted user name (First Last)
    """
    try:
        first, last = USER_LOGIN.split('.')
        return f"{first.capitalize()} {last.upper()}"
    except ValueError:
        return USER_LOGIN

def get_user_trigram() -> str:
    """
    Generates a user trigram from the login name.
    
    Returns:
        str: Three-character user identifier
    """
    try:
        first, last = USER_LOGIN.split('.')
        return f"{first[0]}{last[:2]}".lower()
    except ValueError:
        return USER_LOGIN[:3].lower()
    
def get_hda_node():
    """Returns the current HDA node."""
    return hou.pwd()


# --- JSON and Dependency Management ---

def scan_dependencies(folder_path: Union[str, Path]) -> List[str]:
    """
    Scans a folder for files and returns a list of their paths.
    
    Args:
        folder_path (str|Path): Folder to scan
        
    Returns:
        List[str]: List of file paths
    """
    path = Path(folder_path)
    if not path.is_dir():
        return []
    try:
        return [str(item) for item in path.iterdir() if item.is_file()]
    except Exception as e:
        logging.error(f"Error scanning dependencies in {folder_path}: {e}")
        return []

def build_version_data(
    root: str, 
    department: str, 
    task: str, 
    project: str, 
    version: str, 
    product_type: str, 
    product: str, 
    dependencies_path: Union[str, Path], 
    **kwargs: Any
) -> Dict[str, Any]:
    """
    Builds the dictionary for the version.json file.
    
    Args:
        root (str): Project root path
        department (str): Department name (e.g., "vfx", "lighting")
        task (str): Task name (e.g., "modeling", "texturing")
        project (str): Project name
        version (str): Version string (e.g., "v0001")
        product_type (str): Type of product (e.g., "render", "cache")
        product (str): Product name
        dependencies_path (str|Path): Path to scan for dependencies
        **kwargs: Additional key-value pairs to include in the data
        
    Returns:
        Dict[str, Any]: Complete version data dictionary
    """
    # Get current scene file path safely
    try:
        current_scene = hou.hipFile.path()
    except hou.OperationFailed:
        current_scene = "untitled.hip"
    
    # Get current FPS safely
    try:
        current_fps = hou.fps()
    except hou.OperationFailed:
        current_fps = 24.0
    
    base_data = {
        "project_path": str(root),
        "department": department,
        "task": task,
        "project_name": project,
        "version": version,
        "type": product_type,
        "locations": {"global": current_scene},
        "comment": "",
        "sourceScene": current_scene,
        "product": product,
        "fps": current_fps,
        "username": get_formatted_user_name(),
        "user": get_user_trigram(),
        "date": datetime.now().strftime("%d.%m.%y %H:%M:%S"),
        "dependencies": scan_dependencies(dependencies_path),
        "externalFiles": []
    }
    
    # Add any additional parameters passed via kwargs
    base_data.update(kwargs)
    return base_data

def create_version_info(data: Dict[str, Any], folder_path: Union[str, Path]) -> bool:
    """
    Creates a versioninfo.json file.
    
    Args:
        data (Dict[str, Any]): Data to write to JSON
        folder_path (str|Path): Folder to create the file in
        
    Returns:
        bool: True if successful, False otherwise
    """
    json_path = Path(folder_path) / "versioninfo.json"
    try:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        logging.info(f"Successfully created {json_path}")
        return True
    except IOError as e:
        logging.error(f"Failed to write to {json_path}: {e}")
        return False

def create_version_with_info(
    root: str,
    department: str, 
    task: str,
    project: str,
    version: str,
    product_type: str,
    product: str,
    dependencies_path: Union[str, Path],
    output_folder: Union[str, Path],
    **kwargs: Any
) -> bool:
    """
    Convenience function to build version data and create the JSON file.
    
    Args:
        root (str): Project root path
        department (str): Department name
        task (str): Task name  
        project (str): Project name
        version (str): Version string
        product_type (str): Type of product
        product (str): Product name
        dependencies_path (str|Path): Path to scan for dependencies
        output_folder (str|Path): Output folder for the JSON file
        **kwargs: Additional data to include in the version info
        
    Returns:
        bool: True if successful, False otherwise
    """
    # Build the version data
    version_data = build_version_data(
        root=root,
        department=department,
        task=task,
        project=project,
        version=version,
        product_type=product_type,
        product=product,
        dependencies_path=dependencies_path,
        **kwargs
    )
    
    # If version data is empty, return False
    if not version_data:
        return False
    
    # Create the version info JSON file
    return create_version_info(version_data, output_folder)

def get_file_extension(file_path):
    """
    Get the file extension in lowercase
    Args:
        file_path (str): The file path.
    Returns:
        str: The file extension in lowercase.
    """
    return os.path.splitext(file_path)[1].lower()

def shorten_path(path, max_length=60):
    """
    Shorten a path for display purposes
    
    Args:
        path (str): The full file path.
        max_length (int): Maximum length of the displayed path.
    Returns:
        str: The shortened path.
    """
    if len(path) <= max_length:
        return path
    
    parts = path.split(os.sep)
    if len(parts) > 3:
        return f"{parts[0]}{os.sep}...{os.sep}{parts[-2]}{os.sep}{parts[-1]}"
    else:
        return f"...{path[-max_length:]}"

def open_file_location(file_path):
    """
    Open the file location in the explorer
    
    Args:
        file_path (str): The file path to open.
    """
    try:
        if os.path.exists(file_path):
            folder_path = os.path.dirname(file_path)
            subprocess.run(['explorer', '/select,', file_path])
        else:
            # if file doesn't exist, just open the folder if it exists
            folder_path = os.path.dirname(file_path)
            if os.path.exists(folder_path):
                subprocess.run(['explorer', folder_path])
    except Exception as e:
        print(f"Error opening file location: {e}")
