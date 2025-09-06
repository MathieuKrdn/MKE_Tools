import hou
from pxr import Usd, UsdShade, Sdf, Ar
import os
from collections import defaultdict
import mke_utils
from PySide2 import QtWidgets, QtCore, QtGui

def analyze_layers_and_references(stage, dependencies, texture_exts, alembic_exts, usd_exts):
    """
    Analyze USD layers and references to find dependencies
    
    Args:
        stage (Usd.Stage): The USD stage to analyze.
        dependencies (dict): A dictionary to store found dependencies.
        texture_exts (list): List of supported texture file extensions.
        alembic_exts (list): List of supported Alembic file extensions.
        usd_exts (list): List of supported USD file extensions.
    """

    # Analyze the layers
    layer_count = 0
    try:
        root_layer_path = stage.GetRootLayer().realPath
        for layer in stage.GetUsedLayers():
            if layer.realPath:
                layer_count += 1
                layer_path = layer.realPath
                ext = mke_utils.get_file_extension(layer_path)
                
                if ext in usd_exts and layer_path != root_layer_path:
                    dependencies['usd_references'][layer_path].append("Layer référencé")
        
    except Exception as e:
        print(f"Warning: Could not analyze layers: {e}")

    # Analyze direct references
    ref_count = 0
    try:
        for prim in stage.Traverse():
            # USD References
            if prim.HasAuthoredReferences():
                try:
                    refs = prim.GetReferences()
                    
                    # Method 1: Try GetAddedItems()
                    try:
                        if hasattr(refs, 'GetAddedItems'):
                            for ref in refs.GetAddedItems():
                                if hasattr(ref, 'assetPath') and ref.assetPath:
                                    resolved_path = resolve_asset_path(ref.assetPath, stage)
                                    if resolved_path:
                                        ext = mke_utils.get_file_extension(resolved_path)
                                        if ext in usd_exts:
                                            dependencies['usd_references'][resolved_path].append(f"Référence depuis {prim.GetPath()}")
                                            ref_count += 1
                    except Exception as e:
                        print(f"Warning: GetAddedItems failed for {prim.GetPath()}: {e}")
                    
                    # Method 2: Try composition stack
                    try:
                        if hasattr(prim, 'GetPrimStack'):
                            for stack_item in prim.GetPrimStack():
                                if (hasattr(stack_item, 'layer') and 
                                    hasattr(stack_item, 'path') and 
                                    stack_item.layer.realPath and 
                                    stack_item.layer.realPath != root_layer_path):
                                    
                                    layer_path = stack_item.layer.realPath
                                    ext = mke_utils.get_file_extension(layer_path)
                                    if ext in usd_exts:
                                        dependencies['usd_references'][layer_path].append(f"Composition reference from {prim.GetPath()}")
                                        ref_count += 1
                    except Exception as e:
                        print(f"Warning: Composition stack analysis failed for {prim.GetPath()}: {e}")
                        
                except Exception as e:
                    print(f"Warning: Could not analyze references for {prim.GetPath()}: {e}")
            
            # Also check payloads
            if prim.HasAuthoredPayloads():
                try:
                    payloads = prim.GetPayloads()
                    
                    if hasattr(payloads, 'GetAddedItems'):
                        for payload in payloads.GetAddedItems():
                            if hasattr(payload, 'assetPath') and payload.assetPath:
                                resolved_path = resolve_asset_path(payload.assetPath, stage)
                                if resolved_path:
                                    ext = mke_utils.get_file_extension(resolved_path)
                                    if ext in usd_exts:
                                        dependencies['usd_references'][resolved_path].append(f"Payload depuis {prim.GetPath()}")
                                        ref_count += 1
                except Exception as e:
                    print(f"Warning: Could not analyze payloads for {prim.GetPath()}: {e}")
                
    except Exception as e:
        print(f"Warning: Could not traverse prims for references: {e}")

def analyze_shaders_and_textures(stage, dependencies, texture_exts):
    """
    Analyze shaders to find textures
    
    Args:
        stage (Usd.Stage): The USD stage to analyze.
        dependencies (dict): A dictionary to store found dependencies.
        texture_exts (list): List of supported texture file extensions.
    """

    for prim in stage.Traverse():
        # Check regular shaders
        if prim.IsA(UsdShade.Shader):
            shader = UsdShade.Shader(prim)
            
            # Analyze all shader inputs
            for shader_input in shader.GetInputs():
                if shader_input.GetTypeName() == Sdf.ValueTypeNames.Asset:
                    asset_value = shader_input.Get()
                    
                    if asset_value and isinstance(asset_value, Sdf.AssetPath):
                        asset_path = asset_value.path
                        resolved_path = resolve_asset_path(asset_path, stage)
                        
                        if resolved_path:
                            ext = mke_utils.get_file_extension(resolved_path)
                            if ext in texture_exts:
                                context = f"Shader: {shader.GetPath()} → Input: {shader_input.GetBaseName()}"
                                dependencies['textures'][resolved_path].append(context)
        
        # Check dome lights specifically
        elif prim.GetTypeName() == 'DomeLight':
            
            # Check common dome light texture attributes
            dome_texture_attrs = [
                'inputs:texture:file',
                'texture:file', 
                'file',
                'inputs:file'
            ]
            
            for attr_name in dome_texture_attrs:
                if prim.HasAttribute(attr_name):
                    attr = prim.GetAttribute(attr_name)
                    if attr.GetTypeName() == Sdf.ValueTypeNames.Asset:
                        asset_value = attr.Get()
                        
                        if asset_value and isinstance(asset_value, Sdf.AssetPath):
                            asset_path = asset_value.path
                            resolved_path = resolve_asset_path(asset_path, stage)
                            
                            if resolved_path:
                                ext = mke_utils.get_file_extension(resolved_path)
                                if ext in texture_exts:
                                    context = f"DomeLight: {prim.GetPath()} → Attribute: {attr_name}"
                                    dependencies['textures'][resolved_path].append(context)
            
            # Also check all attributes for any asset paths
            for attr in prim.GetAttributes():
                if attr.GetTypeName() == Sdf.ValueTypeNames.Asset:
                    asset_value = attr.Get()
                    
                    if asset_value and isinstance(asset_value, Sdf.AssetPath):
                        asset_path = asset_value.path
                        resolved_path = resolve_asset_path(asset_path, stage)
                        
                        if resolved_path:
                            ext = mke_utils.get_file_extension(resolved_path)
                            if ext in texture_exts:
                                context = f"DomeLight: {prim.GetPath()} → Attribute: {attr.GetName()}"
                                dependencies['textures'][resolved_path].append(context)
        
        # Check other light types that might have textures
        elif prim.GetTypeName() in ['RectLight', 'CylinderLight', 'SphereLight']:
            
            # Check for texture attributes in other lights
            light_texture_attrs = [
                'inputs:texture:file',
                'texture:file',
                'file',
                'inputs:file',
                'inputs:color:file'
            ]
            
            for attr_name in light_texture_attrs:
                if prim.HasAttribute(attr_name):
                    attr = prim.GetAttribute(attr_name)
                    if attr.GetTypeName() == Sdf.ValueTypeNames.Asset:
                        asset_value = attr.Get()
                        
                        if asset_value and isinstance(asset_value, Sdf.AssetPath):
                            asset_path = asset_value.path
                            resolved_path = resolve_asset_path(asset_path, stage)
                            
                            if resolved_path:
                                ext = mke_utils.get_file_extension(resolved_path)
                                if ext in texture_exts:
                                    context = f"Light ({prim.GetTypeName()}): {prim.GetPath()} → Attribute: {attr_name}"
                                    dependencies['textures'][resolved_path].append(context)

def analyze_geometry_references(stage, dependencies, alembic_exts):
    """
    Analyze geometry references (Alembic, etc.)
    
    Args:
        stage (Usd.Stage): The USD stage to analyze.
        dependencies (dict): A dictionary to store found dependencies.
        alembic_exts (list): List of supported Alembic file extensions.
    """

    for prim in stage.Traverse():
        # Look at attributes for asset paths
        for attr in prim.GetAttributes():
            if attr.GetTypeName() == Sdf.ValueTypeNames.Asset:
                asset_value = attr.Get()
                
                if asset_value and isinstance(asset_value, Sdf.AssetPath):
                    asset_path = asset_value.path
                    resolved_path = resolve_asset_path(asset_path, stage)
                    
                    if resolved_path:
                        ext = mke_utils.get_file_extension(resolved_path)
                        if ext in alembic_exts:
                            context = f"Prim: {prim.GetPath()} → Attribut: {attr.GetName()}"
                            dependencies['alembics'][resolved_path].append(context)
                        elif ext not in ['.jpg', '.jpeg', '.png', '.tif', '.tiff', '.exr', '.tx', '.rat', '.pic', '.hdr', '.usd', '.usda', '.usdc', '.usdz']:
                            context = f"Prim: {prim.GetPath()} → Attribut: {attr.GetName()}"
                            dependencies['autres'][resolved_path].append(context)

def resolve_asset_path(asset_path, stage):
    """Solve and resolve an asset path using USD resolver and relative paths
    
    Args:
        asset_path (str): The asset path to resolve.
        stage (Usd.Stage): The USD stage for context.
    Returns:
        str or None: The resolved absolute path, or None if not found.
    """
    try:
        # Use the USD resolver
        resolver = Ar.GetResolver()
        resolved = resolver.Resolve(asset_path)
        if resolved:
            return resolved.GetPathString()
        
        # absolute path check
        if os.path.isabs(asset_path):
            return asset_path if os.path.exists(asset_path) else None
        else:
            # relative path check
            stage_dir = os.path.dirname(stage.GetRootLayer().realPath)
            full_path = os.path.join(stage_dir, asset_path)
            return full_path if os.path.exists(full_path) else None
    except:
        return None

def check_non_serveur_drive_files(dependencies, server_path):
    """
    Check files that are not on the server
    
    Args:
        dependencies (dict): The dictionary of dependencies.
        server_path (str): The server path prefix.
    """
    non_serveur_files = []

    # check each dependency category
    for category, deps in dependencies.items():
        for file_path in deps.keys():
            # Normalize the path
            normalized_path = os.path.normpath(file_path).upper()
            file_path_cleaned = os.path.normpath(file_path)

            # Check if the file is not on the server
            if not normalized_path.startswith(server_path.upper()):
                non_serveur_files.append({
                    'path': file_path_cleaned,
                    'category': category,
                    'contexts': deps[file_path],
                    'exists': os.path.exists(file_path_cleaned)
                })

    # Show the dialog if non-server files are found
    if non_serveur_files:
        show_non_serveur_dialog(non_serveur_files)

def show_non_serveur_dialog(non_serveur_files):
    """
    Show a dialog with files that are not on the server.

    Args:
        non_serveur_files (list): List of dictionaries with file info.
    """

    class NonServeurDialog(QtWidgets.QDialog):
        def __init__(self, files_data):
            """
            Initialize the dialog
            
            Args:
                files_data (list): List of dictionaries with file info.
            """
            super().__init__(hou.qt.mainWindow())
            self.files_data = files_data
            self.setup_ui()
            
        def setup_ui(self):
            """Set up the UI components"""
            self.setWindowTitle(f"Off-Server Files - {len(self.files_data)} file(s) found")
            self.setMinimumSize(1000, 600)
            self.resize(1200, 700)
            
            layout = QtWidgets.QVBoxLayout(self)
            
            # Header
            header_label = QtWidgets.QLabel(
                f"<h2>⚠️ WARNING: {len(self.files_data)} file(s) are not on the server</h2>"
                "<p>If these files are needed for rendering, they should be copied to the server. "
                "<b>Right-click</b> on a file for more options.</p>"
            )
            header_label.setStyleSheet("color: #FF6B35; margin: 10px;")
            layout.addWidget(header_label)
            
            # Tree widget to display files with dark theme
            self.tree = QtWidgets.QTreeWidget()
            self.tree.setHeaderLabels(['Status', 'File', 'Type', 'Context'])
            self.tree.setAlternatingRowColors(True)
            self.tree.setSortingEnabled(True)
            self.tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
            self.tree.customContextMenuRequested.connect(self.show_context_menu)
            
            self.tree.setStyleSheet("""
                QTreeWidget {
                    background-color: #2b2b2b;
                    color: white;
                    alternate-background-color: #353535;
                    selection-background-color: #404040;
                }
                QTreeWidget::item {
                    border: none;
                    padding: 2px;
                }
                QTreeWidget::item:hover {
                    background-color: #505050;
                }
                QTreeWidget::item:selected {
                    background-color: #606060;
                }
                QHeaderView::section {
                    background-color: #404040;
                    color: white;
                    border: 1px solid #555555;
                    padding: 4px;
                }
            """)
            
            # Populate tree
            self.populate_tree()
            
            layout.addWidget(self.tree)
            
            # Statistics
            stats_layout = QtWidgets.QHBoxLayout()
            
            missing_count = sum(1 for f in self.files_data if not f['exists'])
            existing_count = len(self.files_data) - missing_count
            
            stats_label = QtWidgets.QLabel(
                f"📊 Statistics: {existing_count} existing file(s), "
                f"{missing_count} missing file(s)"
            )
            stats_label.setStyleSheet("color: white; margin: 5px;")  # White text for dark theme
            stats_layout.addWidget(stats_label)
            
            # Buttons
            button_layout = QtWidgets.QHBoxLayout()
            
            button_layout.addStretch()
            
            close_btn = QtWidgets.QPushButton("Validate and Close")
            close_btn.setStyleSheet("""
                QPushButton {
                    background-color: #505050;
                    color: white;
                    border: 1px solid #666666;
                    padding: 5px 15px;
                    border-radius: 3px;
                }
                QPushButton:hover {
                    background-color: #606060;
                }
                QPushButton:pressed {
                    background-color: #404040;
                }
            """)
            close_btn.clicked.connect(self.accept)
            button_layout.addWidget(close_btn)
            
            stats_layout.addLayout(button_layout)
            layout.addLayout(stats_layout)
            
            self.setStyleSheet("""
                QDialog {
                    background-color: #2b2b2b;
                    color: white;
                }
            """)
        
        def show_context_menu(self, position):
            """
            Display context menu on right-click
            
            Args:
                position (QPoint): The position where the menu should appear.
            """
            item = self.tree.itemAt(position)
            if not item:
                return

            # Get the file path
            file_path = None

            if item.parent() is None:  # Main item (not a context sub-item)
                file_path = item.text(1)  # Column "File"
            else:  # Context sub-item
                file_path = item.parent().text(1)
            if not file_path:
                return

            # Create context menu
            menu = QtWidgets.QMenu(self)

            # Action: Copy path
            copy_path_action = menu.addAction("Copy path")
            copy_path_action.triggered.connect(lambda: self.copy_file_path(file_path))

            # Action: Open location
            if os.path.exists(file_path):
                open_location_action = menu.addAction("Open location")
                open_location_action.triggered.connect(lambda: mke_utils.open_file_location(file_path))
            else:
                # If the file doesn't exist, offer to open the parent folder
                parent_dir = os.path.dirname(file_path)
                if os.path.exists(parent_dir):
                    open_parent_action = menu.addAction("Open parent folder")
                    open_parent_action.triggered.connect(lambda: mke_utils.open_file_location(parent_dir))
            
            menu.addSeparator()

            # Action: Copy only the filename
            filename = os.path.basename(file_path)
            copy_filename_action = menu.addAction(f"Copy '{filename}'")
            copy_filename_action.triggered.connect(lambda: self.copy_file_path(filename))

            # Show the menu
            menu.exec_(self.tree.mapToGlobal(position))
        
        def copy_file_path(self, path):
            """Copy the given path to clipboard and show a message
            
            Args:
                path (str): The path to copy.
            """
            QtWidgets.QApplication.clipboard().setText(path)
            QtWidgets.QMessageBox.information(self, "Copié", f"Chemin copié:\n{path}")
            
        def populate_tree(self):
            """Fill tree widget with file data"""
            category_icons = {
                'textures': '🖼️',
                'alembics': '📦',
                'usd_references': '🔗',
                'autres': '📄'
            }
            
            for file_data in self.files_data:
                # Status
                status = "✅ Exists" if file_data['exists'] else "❌ MISSING"
                
                # Shorten path for display
                short_path = mke_utils.shorten_path(file_data['path'], 70)
                
                # Create main item
                item = QtWidgets.QTreeWidgetItem([
                    status,
                    file_data['path'],  # Full path (hidden but accessible)
                    f"{category_icons.get(file_data['category'], '📄')} {file_data['category'].upper()}",
                    f"{len(file_data['contexts'])} usage(s)"
                ])
                
                # Set displayed text (shortened) in file column
                item.setText(1, short_path)
                
                # Tooltip with full path
                item.setToolTip(1, file_data['path'])
                
                if not file_data['exists']:
                    for col in range(4):
                        item.setBackground(col, QtGui.QColor(80, 40, 40))    # Dark red
                        item.setForeground(col, QtGui.QColor(255, 180, 180)) # Light red text
                else:
                    for col in range(4):
                        item.setBackground(col, QtGui.QColor(60, 60, 60))    # Dark grey
                        item.setForeground(col, QtGui.QColor(255, 255, 255)) # White text
                
                self.tree.addTopLevelItem(item)
                
                # Add context children
                for context in set(file_data['contexts']):
                    # Shorten context too
                    short_context = context if len(context) <= 80 else context[:77] + "..."
                    context_item = QtWidgets.QTreeWidgetItem(['', '', '', short_context])
                    context_item.setToolTip(3, context)  # Column 3 is the Context column
                    
                    for col in range(4):
                        context_item.setBackground(col, QtGui.QColor(45, 45, 45))    # Very dark grey
                        context_item.setForeground(col, QtGui.QColor(200, 200, 200)) # Light grey text
                    
                    item.addChild(context_item)
            
            # Set column widths
            self.tree.setColumnWidth(0, 80)   # Status
            self.tree.setColumnWidth(1, 400)  # File
            self.tree.setColumnWidth(2, 120)  # Type
            self.tree.setColumnWidth(3, 200)  # Context
    
    # Afficher la fenêtre
    dialog = NonServeurDialog(non_serveur_files)
    dialog.exec_()

def start_with_file(usd_save_path, server_path):
    """
    Start USD dependency check with specific file and server path.
    This function bypasses any dialogs and runs directly.
    
    Args:
        usd_save_path (str): Path to the USD file to analyze
        server_path (str): Server path to check against (e.g., "W:/")
    """

    # Validate inputs
    if not usd_save_path:
        print("❌ No USD file path provided")
        return
        
    if not os.path.exists(usd_save_path):
        print(f"❌ USD file not found: {usd_save_path}")
        hou.ui.displayMessage(f"USD file not found: {usd_save_path}", severity=hou.severityType.Error)
        return
        
    if not server_path:
        print("⚠️ No server path provided, using default (W:/)")
        server_path = "W:/"
    
    # Ensure server path ends with separator
    if not server_path.endswith(('/', '\\')):
        server_path += os.sep
        
    # Open USD stage
    try:
        stage = Usd.Stage.Open(usd_save_path)
        if not stage:
            hou.ui.displayMessage("Cannot open USD file", severity=hou.severityType.Error)
            return
    except Exception as e:
        error_msg = f"Error opening USD file: {e}"
        hou.ui.displayMessage(error_msg, severity=hou.severityType.Error)
        return
    
    # Initialize dependencies dictionary
    dependencies = {
        'textures': defaultdict(list),
        'alembics': defaultdict(list),
        'usd_references': defaultdict(list),
        'autres': defaultdict(list)
    }
    
    # Supported extensions
    texture_exts = ['.jpg', '.jpeg', '.png', '.tif', '.tiff', '.exr', '.tx', '.rat', '.pic', '.hdr']
    alembic_exts = ['.abc']
    usd_exts = ['.usd', '.usda', '.usdc', '.usdz']
        
    try:
        # 1. Analyze layers and references
        analyze_layers_and_references(stage, dependencies, texture_exts, alembic_exts, usd_exts)
        
        # 2. Analyze shaders, textures, and lights (including dome lights)
        analyze_shaders_and_textures(stage, dependencies, texture_exts)
        
        # 3. Analyze geometry references
        analyze_geometry_references(stage, dependencies, alembic_exts)
        
        # 4. Comprehensive scan for any missed assets
        analyze_all_asset_attributes(stage, dependencies, texture_exts, alembic_exts, usd_exts)
        
        # Check for non-server files and show results
        check_non_serveur_drive_files(dependencies, server_path)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        hou.ui.displayMessage(f"USD dependency check failed: {e}", severity=hou.severityType.Error)

def analyze_all_asset_attributes(stage, dependencies, texture_exts, alembic_exts, usd_exts):
    """Comprehensive analysis of all asset attributes (fallback method)
    
    Args:
        stage (Usd.Stage): The USD stage to analyze.
        dependencies (dict): A dictionary to store found dependencies.
        texture_exts (list): List of supported texture file extensions.
        alembic_exts (list): List of supported Alembic file extensions.
        usd_exts (list): List of supported USD file extensions.
    """    
    found_count = 0
    for prim in stage.Traverse():
        # Check ALL attributes for asset paths
        for attr in prim.GetAttributes():
            if attr.GetTypeName() == Sdf.ValueTypeNames.Asset:
                asset_value = attr.Get()
                
                if asset_value and isinstance(asset_value, Sdf.AssetPath):
                    asset_path = asset_value.path
                    resolved_path = resolve_asset_path(asset_path, stage)
                    
                    if resolved_path:
                        ext = mke_utils.get_file_extension(resolved_path)
                        attr_name = attr.GetName()
                        prim_type = prim.GetTypeName()
                        
                        if ext in texture_exts:
                            context = f"Prim ({prim_type}): {prim.GetPath()} → Attribute: {attr_name}"
                            if resolved_path not in dependencies['textures']:
                                dependencies['textures'][resolved_path].append(context)
                                found_count += 1
                        elif ext in alembic_exts:
                            context = f"Prim ({prim_type}): {prim.GetPath()} → Attribute: {attr_name}"
                            if resolved_path not in dependencies['alembics']:
                                dependencies['alembics'][resolved_path].append(context)
                                found_count += 1
                        elif ext in usd_exts:
                            context = f"Prim ({prim_type}): {prim.GetPath()} → Attribute: {attr_name}"
                            if resolved_path not in dependencies['usd_references']:
                                dependencies['usd_references'][resolved_path].append(context)
                                found_count += 1
                        elif ext not in []:  # Don't exclude any extensions
                            context = f"Prim ({prim_type}): {prim.GetPath()} → Attribute: {attr_name}"
                            if resolved_path not in dependencies['autres']:
                                dependencies['autres'][resolved_path].append(context)
                                found_count += 1