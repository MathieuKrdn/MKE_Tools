"""Run on the farm by Deadline (CommandLine plugin, Houdini's own python):
    python mke_husk_render.py <husk.exe> <file.usd> <start> <end> <increment> <output with $F4> <renderer> <log>
Renders one Deadline task with husk (Karma CPU / XPU) and keeps a readable log. Exit code = husk's."""
import os
import subprocess
import sys
import time


def main(husk, usd, start, end, inc, output, renderer, log_path):
    start, end, inc = int(float(start)), int(float(end)), max(1, int(float(inc)))
    count = (end - start) // inc + 1
    cmd = [husk, "-f", str(start), "-n", str(count), "-i", str(inc), "-o", output, "-R", renderer,
           "--make-output-path", "-V", "a2", usd]
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as log:
        def out(text):
            sys.stdout.write(text)
            sys.stdout.flush()
            log.write(text)
            log.flush()

        out(f"=== {time.strftime('%Y-%m-%d %H:%M:%S')}  frames {start}-{end} (pas {inc})  {renderer}\n{' '.join(cmd)}\n")
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
        for line in process.stdout:
            out(line)
        code = process.wait()
        out(f"=== {'OK' if code == 0 else f'ERREUR : husk a quitté avec le code {code}'}\n")
    return code


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:9]))
