# Runs once when Houdini 22 starts: switch to Manual update mode once the UI is up.
import hou

if hou.isUIAvailable():
    import hdefereval
    import mke_project
    hdefereval.executeDeferred(mke_project.startup)
