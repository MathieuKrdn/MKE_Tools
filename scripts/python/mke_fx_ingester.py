import hou
import os
import re
import json
from datetime import datetime
from pathlib import Path
import shutil
import logging
import mke_utils

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S')

# --- Constants ---
VERSION_REGEX = re.compile(r'v(\d{4})')

# --- Houdini-Specific Logic ---

def setup_vdb(hda, dependencies_path, name, version, fxtype, vdbcached):
    """Configures VDB caching and file paths."""
    hou.putenv('HOUDINI_VDB_FORCE_STEAM_SAVE', '1')
    mke_utils.log_debug("HOUDINI_VDB_FORCE_STEAM_SAVE is set to 1.", hda)

    dependencies_path = Path(dependencies_path)
    if fxtype == 0: # VDB
        if vdbcached:
            vdb_file_path = hda.parm('vdbCached').eval()
            source_dir = Path(vdb_file_path).parent
            if source_dir.is_dir():
                mke_utils.create_directory(dependencies_path, hda)
                for item in source_dir.iterdir():
                    if item.is_file():
                        shutil.copy2(item, dependencies_path / item.name)
                
                vdb_files = [f for f in dependencies_path.glob('*.vdb')]
                if vdb_files:
                    # Constructing the file path for the file node
                    file_pattern = str(vdb_files[0]).replace(f".{hou.frame():04d}", ".$F4")
                    hda.node('file1').parm('file').set(file_pattern)
        else:
            vdb_path = dependencies_path / f"{name}_{version}.$F4.vdb"
            hda.node('filecache1').parm('file').set(str(vdb_path))
            # hda.node('filecache1').parm('execute').pressButton()

def setup_rbd(lop_node, folder_path, name_fracture, version):
    """Configures RBD export paths."""
    save_path = Path(folder_path) / "dependencies" / f"{name_fracture}_{version}.usdc"
    mke_utils.create_directory(save_path.parent, lop_node.parent())
    lop_node.node('configurelayer_RBD_ingest').parm('savepath').set(str(save_path))
    # lop_node.node('usd_rop6').parm('execute').pressButton()

def setup_usd_stitch(folder_path, lop_node, name, version, rop_node, product):
    """Sets up paths for USD stitching."""
    dependencies_path = Path(folder_path) / "dependencies"
    mke_utils.create_directory(dependencies_path, lop_node.parent())
    
    base_name = f"{name}_{version}"
    lop_node.node('usd_rop1').parm('lopoutput').set(str(dependencies_path / f"{base_name}.$F4.usdc"))
    rop_node.node('usdstitchclips1').parm('outtemplatefile1').set(str(dependencies_path / f"{base_name}_geoclip.usdc"))
    rop_node.node('usdstitchclips1').parm('clippath1').set(f"/{product}")
    
    usd_file = f"{base_name}.usdc"
    lop_node.node('fx').parm('lopoutput').set(str(Path(folder_path) / usd_file))
    
    return usd_file, str(dependencies_path)

def execute_tops(topnet_node):
    """Executes the TOP network."""
    import nodegraphtopui
    nodegraphtopui.cookOutputNode(topnet_node)
    logging.info("TOP network execution started.")

# --- Main Workflow Functions ---

def get_context_info(hda):
    """Gathers context information based on the operating mode."""
    save_dir = hda.parm('saveDir').eval()
    if not save_dir:
        mke_utils.handle_error("'Out of Pipe' mode requires a 'Save Directory'.", hda)
        return None
    return {"base_path": Path(save_dir), "context_type": "fx"}