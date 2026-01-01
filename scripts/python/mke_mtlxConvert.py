"""
MKE Tools - Mtlx Convert
Convert selected materials between MaterialX and Houdini native formats
"""

import hou

def convert():
    node = hou.selectedNodes()

    if node==():
        hou.ui.displayMessage("Please select a material node to convert.", severity=hou.severityType.Error)
        return
    
    matContext = node.parent()
    matsubnet = matContext.createNode("subnet", node.name()+"_materialx_convert")

    # Define the output material node
    mtlOutput = matsubnet.createNode("subnetconnector", "surface_output")
    mtlOutput.parm("parmname").set("surface")
    mtlOutput.parm("parmlabel").set("Surface")
    mtlOutput.parm("parmtype").set("surface")
    mtlOutput.parm("connectorkind").set("output")