# Runs every time a scene is loaded (File > Open, File > New).
import mke_project

mke_project.startup()        # Manual update mode
mke_project.on_scene_load()  # $JOB / $CACHE from the project the .hip lives in
