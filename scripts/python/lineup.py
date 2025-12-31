import hou

def get_best_unit_and_value(value):
    """Convert value to the most appropriate unit (km, m, cm, mm)"""
    abs_value = abs(value)
    if abs_value >= 1000:
        return value / 1000, "km"
    elif abs_value >= 1:
        return value, "m"
    elif abs_value >= 0.01:
        return value * 100, "cm"
    else:
        return value * 1000, "mm"

def format_size_text(width, height, depth):
    """Format size text with best units on 3 lines"""
    w_val, w_unit = get_best_unit_and_value(width)
    h_val, h_unit = get_best_unit_and_value(height)
    d_val, d_unit = get_best_unit_and_value(depth)
    return f"W: {w_val:.2f}{w_unit}\nH: {h_val:.2f}{h_unit}\nD: {d_val:.2f}{d_unit}"

def get_world_bbox(node):
    """Get world-space bounding box for an object node"""
    display_node = node.displayNode()
    if not display_node:
        return None
    
    geo = display_node.geometry()
    if not geo:
        return None
    
    bbox = geo.boundingBox()
    xform = node.worldTransform()
    min_world = bbox.minvec() * xform
    max_world = bbox.maxvec() * xform
    
    return hou.BoundingBox(
        min_world[0], min_world[1], min_world[2],
        max_world[0], max_world[1], max_world[2]
    )
    
def lineup():
    selection = hou.selectedNodes()

    if not selection:
        hou.ui.displayMessage("Please select at least one object node")
    else:
        #bounding boxes and sizes
        object_data = []
        
        for node in selection:
            try:
                world_bbox = get_world_bbox(node)
                if world_bbox:
                    size = world_bbox.sizevec()
                    object_data.append({
                        'node': node,
                        'width': size[0],
                        'height': size[1],
                        'depth': size[2]
                    })
            except:
                pass  #Skip nodes without geometry
        
        if not object_data:
            hou.ui.displayMessage("No valid geometry found in selected nodes")
        else:
            #show padding selection dialog
            padding_options = ["Small (0.2m)", "Medium (0.5m)", "Large (1.0m)", "Extra Large (2.0m)"]
            padding_values = [0.2, 0.5, 1.0, 2.0]
            
            selected_idx = hou.ui.selectFromList(
                padding_options,
                default_choices=(1,),
                message="Select padding between objects:",
                title="Object Alignment Settings",
                column_header="Padding Size",
                num_visible_rows=4
            )
            
            if not selected_idx:
                hou.ui.displayMessage("Operation cancelled")
            else:
                spacing = padding_values[selected_idx[0]]
                obj_context = hou.node("/obj")
                
                # Create CONTROLLER
                controller = obj_context.createNode("null", "CONTROLLER")
                controller.setColor(hou.Color(1, 0.5, 0))
                controller.setPosition([0, 2])
                
                #Hide controller interface folders (null default)
                ptg = controller.parmTemplateGroup()
                for folder_name in ["Transform", "Render", "Misc"]:
                    ptg.hideFolder(folder_name, True)
                controller.setParmTemplateGroup(ptg)
                
                # Track created nodes
                created_nulls = []
                created_labels = []
                current_x = 0
                
                for obj in object_data:
                    node, width, height, depth = obj['node'], obj['width'], obj['height'], obj['depth']
                    new_x = current_x + width / 2
                    
                    #Create null to ajust position
                    null = obj_context.createNode("null", f"{node.name()}_null")
                    null.parmTuple('t').set((new_x, 0, 0))
                    null.setColor(hou.Color(0, 0.7, 0))
                    null.setInput(0, controller)
                    created_nulls.append(null)
                    
                    #Create label geo for size display
                    label_geo = obj_context.createNode("geo", f"{node.name()}_label")
                    label_geo.setInput(0, null)
                    label_geo.setColor(hou.Color(0, 0, 0))
                    created_labels.append(label_geo)
                    
                    for child in label_geo.children():
                        child.destroy()
                    
                    #Build label network ---------------------------------------------------
                    font_node = label_geo.createNode("font", "size_label")
                    font_node.parm("text").set(format_size_text(width, height, depth))
                    font_node.parm("fontsize").set(0.2)
                    
                    color_node = label_geo.createNode("color", "red_color")
                    color_node.setInput(0, font_node)
                    color_node.parmTuple("color").set((1, 0, 0))
                    
                    obj_merge = label_geo.createNode("object_merge", "ref_object")
                    obj_merge.parm("objpath1").set(node.path())
                    obj_merge.parm("xformtype").set(1)
                    
                    matchsize = label_geo.createNode("matchsize", "scale_to_object")
                    matchsize.setInput(0, color_node)
                    matchsize.setInput(1, obj_merge)
                    matchsize.parm("justifytarget").set(1)
                    matchsize.parm("doscale").set(1)
                    
                    xform_node = label_geo.createNode("xform", "position_above")
                    xform_node.setInput(0, matchsize)
                    xform_node.parm("ty").set(height + 0.2)
                    xform_node.setDisplayFlag(True)
                    xform_node.setRenderFlag(True)
                    
                    label_geo.layoutChildren()
                    
                    # Parent original object to null and reset transform
                    node.setInput(0, null)
                    node.parmTuple('t').set((0, 0, 0))
                    node.parmTuple('r').set((0, 0, 0))
                    node.parmTuple('s').set((1, 1, 1))
                    
                    # Position nodes in network
                    null.setPosition([new_x * 2, 0])
                    label_geo.setPosition([new_x * 2, -2])
                    node.setPosition([new_x * 2, -4])
                    
                    current_x += width + spacing
                
                #Add controller buttons
                ptg = controller.parmTemplateGroup()
                
                null_paths = ";".join([n.path() for n in created_nulls])
                label_paths = ";".join([l.path() for l in created_labels])
                original_paths = ";".join([obj['node'].path() for obj in object_data])
                
                button_delete = hou.ButtonParmTemplate("delete_alignment", "Delete Alignment")
                callback_delete = f"""
    import hou

    null_paths = "{null_paths}".split(";")
    label_paths = "{label_paths}".split(";")

    for path in null_paths + label_paths:
        node = hou.node(path)
        if node:
            children = [c for c in hou.node("/obj").children() if c.inputs() and node in c.inputs()]
            for child in children:
                for i, inp in enumerate(child.inputs()):
                    if inp == node:
                        child.setInput(i, None)
            node.destroy()

    controller = hou.node(hou.pwd().path())
    if controller:
        controller.destroy()

    hou.ui.displayMessage("Alignment deleted successfully!")
    """
                button_delete.setScriptCallback(callback_delete)
                button_delete.setScriptCallbackLanguage(hou.scriptLanguage.Python)
                
                # Update button
                button_update = hou.ButtonParmTemplate("update_alignment", "Update Alignment")
                callback_update = f"""
    import hou

    def get_best_unit_and_value(value):
        abs_value = abs(value)
        return (value / 1000, "km") if abs_value >= 1000 else (value, "m") if abs_value >= 1 else (value * 100, "cm") if abs_value >= 0.01 else (value * 1000, "mm")

    def format_size_text(width, height, depth):
        w_val, w_unit = get_best_unit_and_value(width)
        h_val, h_unit = get_best_unit_and_value(height)
        d_val, d_unit = get_best_unit_and_value(depth)
        return f"W: {{w_val:.2f}}{{w_unit}}\\nH: {{h_val:.2f}}{{h_unit}}\\nD: {{d_val:.2f}}{{d_unit}}"

    null_paths = "{null_paths}".split(";")
    label_paths = "{label_paths}".split(";")
    original_paths = "{original_paths}".split(";")
    spacing = {spacing}
    current_x = 0

    for null_path, label_path, orig_path in zip(null_paths, label_paths, original_paths):
        null, label_geo, orig_node = hou.node(null_path), hou.node(label_path), hou.node(orig_path)
        
        if null and label_geo and orig_node:
            display_node = orig_node.displayNode()
            if display_node:
                geo = display_node.geometry()
                if geo:
                    bbox = geo.boundingBox()
                    xform = orig_node.worldTransform()
                    min_world, max_world = bbox.minvec() * xform, bbox.maxvec() * xform
                    
                    world_bbox = hou.BoundingBox(min_world[0], min_world[1], min_world[2], max_world[0], max_world[1], max_world[2])
                    size = world_bbox.sizevec()
                    width, height, depth = size[0], size[1], size[2]
                    
                    new_x = current_x + width / 2
                    null.parmTuple('t').set((new_x, 0, 0))
                    
                    font_node = label_geo.node("size_label")
                    if font_node:
                        font_node.parm("text").set(format_size_text(width, height, depth))
                    
                    xform_node = label_geo.node("position_above")
                    if xform_node:
                        xform_node.parm("ty").set(height + 0.2)
                    
                    current_x += width + spacing

    hou.ui.displayMessage("Alignment updated successfully!")
    """
                button_update.setScriptCallback(callback_update)
                button_update.setScriptCallbackLanguage(hou.scriptLanguage.Python)
                
                ptg.addParmTemplate(button_delete)
                ptg.addParmTemplate(button_update)
                controller.setParmTemplateGroup(ptg)
                
                obj_context.layoutChildren()
                hou.ui.displayMessage(f"Successfully aligned {len(object_data)} objects!")
