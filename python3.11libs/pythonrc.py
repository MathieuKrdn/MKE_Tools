# Runs once when Houdini 22 starts: once the UI is up, Manual update mode and the Projects dashboard.
import hou

if hou.isUIAvailable():
    import hdefereval

    def _startup():
        import mke_project
        import projectSetup
        mke_project.startup()
        projectSetup.open_at_startup()

    hdefereval.executeDeferred(_startup)
