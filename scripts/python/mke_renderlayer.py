import loputils
import random
import hou
import re
import webbrowser
import mke_renderlayer
import mke_utils

def help():
    webbrowser.open("https://www.sidefx.com/docs/houdini/solaris/pattern.html")

def getCameras(kwargs):
    import loputils
    lop = kwargs['node'].node('warning')
    cams = loputils.globPrims(lop, '%type:Camera')
    return [x.GetPrimPath().pathString for x in cams for y in range(2)]

def getPlanes(kwargs):
    import loputils
    lop = kwargs['node'].node('renderproduct')
    vars = loputils.globPrims(lop, '/Render/** & %type:RenderVar')
    retval = []
    for var in vars:
        option = []
        option.append(var.GetProperty('driver:parameters:aov:name').Get(hou.frame()))
        option.append(var.GetName())
        retval += option
    return retval

def quicksetup(kwargs):
    node = kwargs["node"]
    setup = kwargs["script_value"]
    if setup == "optimization":
        for aov in ["directdiffuse", "indirectdiffuse", 
                    "directglossyreflection", "indirectglossyreflection", 
                    "glossytransmission", "directemission", "indirectemission",
                    "directvolume", "indirectvolume", "sss"]:
            node.parm(aov).set(1)
      
        debugaovs = ["cputime", "primarysamples", "indirectraycount"]
        extraaovs = node.evalParm("extrarendervars")
        for x in range(extraaovs):
            name = node.evalParm("name%d" % (x + 1))
            if name in debugaovs:
                debugaovs.remove(name)
                node.parm("enable%d" % (x + 1)).set(1)
        
        numvars = extraaovs + len(debugaovs)
        node.parm("extrarendervars").set(numvars)
        for x, aov in enumerate(debugaovs):
            idx = numvars - x
            parmname = "name%d" % idx
            parm = node.parm(parmname)
            parm.set(aov)
            kwargs["parm"] = parm
            kwargs["script_value"] = aov
            kwargs["parm_name"] = parmname
            kwargs["script_parm"] = parmname
            kwargs["script_multiparm_index"] = "%d" % idx
            node.node("additionalrendervars").hm().setAOV(kwargs)
  
            
    node.parm("quicksetup").set("menu")

def execute(pnode='.', key=None):
    hda = hou.node(".")
    layerName = mke_renderlayer.sanitize_layer_name(hda.parm("layerName").eval())
    
    karmaNode = hda.parent().createNode("karmarenderproperties", "Karma_Render_" + layerName.lower())
    motionBlurNode = hda.parent().createNode("motionblur")
    mkeSubmitterNode= hda.parent().createNode("MKE::mke_submitter", "Submitter_" + layerName.lower() + "_FML")
    mkeSubmitterNode2= hda.parent().createNode("MKE::mke_submitter", "Submitter_" + layerName.lower() + "_QuarterRes")
    mkeSubmitterNode3= hda.parent().createNode("MKE::mke_submitter", "Submitter_" + layerName.lower() + "_FullRes")

    network = hda.parent()
    network_box = network.createNetworkBox()
    network_box.setName('MyNetworkBox')
    network_box.setColor(mke_utils.colorNetwork(layerName))
    
    network_box.addItem(hda)
    network_box.addItem(karmaNode)
    network_box.addItem(motionBlurNode)
    network_box.addItem(mkeSubmitterNode)
    network_box.addItem(mkeSubmitterNode2)
    network_box.addItem(mkeSubmitterNode3)
    network_box.setComment(layerName+" LAYER")

    # Connect the new nodes to the current HDA
    karmaNode.setInput(0, hda)
    motionBlurNode.setInput(0, karmaNode)
    mkeSubmitterNode.setInput(0, motionBlurNode)
    mkeSubmitterNode2.setInput(0, motionBlurNode)
    mkeSubmitterNode3.setInput(0, motionBlurNode)
        
    # Node positions
    karmaNode.setPosition(hou.Vector2(hda.position()[0], hda.position()[1] - 1))
    motionBlurNode.setPosition(hou.Vector2(karmaNode.position()[0], karmaNode.position()[1] - 1)) 
    mkeSubmitterNode.setPosition(hou.Vector2(motionBlurNode.position()[0], motionBlurNode.position()[1] - 1))
    mkeSubmitterNode2.setPosition(hou.Vector2(motionBlurNode.position()[0] + 5, motionBlurNode.position()[1] - 1))
    mkeSubmitterNode3.setPosition(hou.Vector2(motionBlurNode.position()[0] + 10, motionBlurNode.position()[1] - 1))

    #network
    network_box.fitAroundContents()
            
    #--------------SETUP CAMERA------------------
    #motionBlurNode.parm('sample_shuttermode').set("manual")
    motionBlurNode.parm('sample_includeframe').set("1")
        
    #--------------SETUP NODES------------------
    
    #renderCamera = hda.parm("camera").eval()
    karmaNode.parm("camera").set(hda.parm("camera"))
    
    #Change resolution
    karmaNode.parm("res_mode").set("manual")
    loputils.updateResolutionParameters(karmaNode, True)
    karmaNode.parm("resolutionx").set(hda.parm("cameraResolutionx"))
    karmaNode.parm("resolutiony").set(hda.parm("cameraResolutiony"))
    karmaNode.parm("picture").set("")
    karmaNode.parm("picture").lock("on")
    karmaNode.parm("primpath").lock("on")
    
    karmaNode.parm("convergence_mode").set("Path Traced")
    
    karmaNode.parm("enabledof").set(0)
    karmaNode.parm("vblur").set("Velocity Blur")
    karmaNode.parm("enabledof").set(0)
    karmaNode.parm("disableimageblur").set(0)
    
    #----------------------------------
    
    karmaNode.allowEditingOfContents()

    parm_template_group = karmaNode.parmTemplateGroup()
    
    # Get the parameters you want to modify
    parm = parm_template_group.find("pathtracedsamples")
    parm2 = parm_template_group.find("samplesperpixel")
    # Modify the XPU samples parameter
    if parm is not None:
        parm.setConditional(hou.parmCondType.HideWhen, "{engine == cpu}")
        parm.setLabel("XPU Samples")
        parm_template_group.replace("pathtracedsamples", parm)
    
    # Modify the CPU samples parameter  
    if parm2 is not None:
        parm2.setConditional(hou.parmCondType.HideWhen, "{engine == xpu}")
        parm2.setLabel("CPU Samples")
        parm_template_group.replace("samplesperpixel", parm2)
    
    # Apply changes to the HDA definition (not the node instance)
    karmaNode.setParmTemplateGroup(parm_template_group)
    
    # Match the current definition to apply changes
    #karmaNode.matchCurrentDefinition()
    #------------------

    #ASPECT RATIO
    karmaNode.parm("aspectRatioConformPolicy").set("cropAperture")
    
    karmaNode.parm("dataWindowNDC1").set(hda.parm("overscanx"))
    karmaNode.parm("dataWindowNDC2").set(hda.parm("overscany"))
    karmaNode.parm("dataWindowNDC3").set(hda.parm("overscanz"))
    karmaNode.parm("dataWindowNDC4").set(hda.parm("overscanw"))
    
    #MODES
    
    if hda.parm('progressiveBucket').eval() == 1:
        karmaNode.parm("imagemode").set("Bucket")
    
    renderEngine = hda.parm('renderer').eval()
    karmaNode.parm('engine').set(hda.parm('renderer'))
         
    mkeSubmitterNode.parm('renderer').set(hda.parm('renderer'))
    mkeSubmitterNode2.parm('renderer').set(hda.parm('renderer'))
    mkeSubmitterNode3.parm('renderer').set(hda.parm('renderer'))
    
    #AOV
    karmaNode.parm("beautyperlpe").set(1)
    karmaNode.parm("shadow").set(1)
    karmaNode.parm("combineddiffuse").set(1)
    karmaNode.parm("combinedglossyreflection").set(1)
    karmaNode.parm("combinedemission").set(1)
    karmaNode.parm("combinedvolume").set(1)
    
    karmaNode.parm("albedo").set(1)
    karmaNode.parm("hitP").set(1)
    karmaNode.parm("hitPz").set(1)
    karmaNode.parm("hituv").set(1)
    
    karmaNode.parm("hitN").set(1)
    karmaNode.parm("motionvectors").set(1)
    
    #SUBMITTERS
    #FML Submitter
    
    mkeSubmitterNode.parm("renderName").set(hda.parm("layerName"))
    mkeSubmitterNode.parm("saveDir").set(hda.parm("saveDir"))
    mkeSubmitterNode.parm("rendersettings").lock("on")
    mkeSubmitterNode.parm("trange").set("normal")
    mkeSubmitterNode.parm("submitOnFarm").set(1)
    #mkeSubmitterNode.parm("f1").set("$FSTART")
    #mkeSubmitterNode.parm("f2").set("$FEND")
    mkeSubmitterNode.parm("f3").setExpression("(ch('f2')-ch('f1'))/2")

    # Quarter Res Submitter
    mkeSubmitterNode2.parm("renderName").set(hda.parm("layerName"))
    mkeSubmitterNode2.parm("saveDir").set(hda.parm("saveDir"))
    mkeSubmitterNode2.parm("rendersettings").lock("on")
    mkeSubmitterNode2.parm("trange").set("normal")
    mkeSubmitterNode2.parm("submitOnFarm").set(1)
    mkeSubmitterNode2.parm("overrideResToggle").set(1)
    mkeSubmitterNode2.parm("overrideResx").setExpression(f"ch('{hda.path()}/cameraResolutionx') / 2")
    mkeSubmitterNode2.parm("overrideResy").setExpression(f"ch('{hda.path()}/cameraResolutiony') / 2")

    # Full Res Submitter
    mkeSubmitterNode3.parm("renderName").set(hda.parm("layerName"))
    mkeSubmitterNode3.parm("saveDir").set(hda.parm("saveDir"))
    mkeSubmitterNode3.parm("rendersettings").lock("on")
    mkeSubmitterNode3.parm("trange").set("normal")
    mkeSubmitterNode3.parm("submitOnFarm").set(1)  

