import sys
import pathlib
import json

def houdiniVSC():
    vscode_settings = {}

    pythonexe_path = pathlib.Path(sys.prefix).resolve().joinpath("python.exe")
    vscode_settings['python.defaultInterpreterPath'] = pythonexe_path.as_posix()

    sys_paths = [pathlib.Path(p).resolve() for p in sys.path]
    vscode_settings['python.analysis.extraPaths'] = [p.as_posix() for p in sys_paths]

    print(json.dumps(vscode_settings, indent=4))
    return json.dumps(vscode_settings, indent=4)
