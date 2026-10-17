"""Run on the farm by Deadline (CommandLine plugin):
    hython mke_deadline_cook.py <scene> <node path> <start> <end> <log file>
Cooks a File Cache (its internal 'render' ROP) or any ROP over the frame range, and writes a readable log."""
import os
import sys
import time


class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, text):
        for stream in self.streams:
            stream.write(text)
            stream.flush()

    def flush(self):
        for stream in self.streams:
            stream.flush()


def main(scene, path, start, end, log_path):
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    log = open(log_path, "a", encoding="utf-8")
    sys.stdout = sys.stderr = Tee(sys.__stdout__, log)
    print(f"=== {time.strftime('%Y-%m-%d %H:%M:%S')}  {path}  frames {start}-{end}\nscene: {scene}")
    import hou
    hou.hipFile.load(scene, suppress_save_prompt=True, ignore_load_warnings=True)
    node = hou.node(path)
    if node is None:
        raise SystemExit(f"ERREUR : node introuvable dans la scène : {path}")
    rop = node.node("render") if node.type().nameComponents()[2] == "filecache" else node
    started = time.time()
    try:
        rop.render(frame_range=(start, end), verbose=True, output_progress=True)
    except hou.OperationFailed as error:
        print(f"ERREUR : {error}")
        raise SystemExit(1)
    print(f"=== OK en {int(time.time() - started)} s")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4]), sys.argv[5])
