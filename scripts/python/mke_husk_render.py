"""Run on the farm by Deadline (CommandLine plugin, Houdini's own python):
    python mke_husk_render.py <husk.exe> <file.usd> <start> <end> <increment> <output with $F4> <renderer> <log>
Renders one Deadline task with husk (Karma CPU / XPU) and keeps a readable log. Exit code = husk's."""
import os
import re
import subprocess
import sys
import time

ALF = re.compile(r"ALF_PROGRESS\s+(\d+)%")


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

        out(f"=== {time.strftime('%Y-%m-%d %H:%M:%S')}  frames {start}-{end} (step {inc})  {renderer}\n{' '.join(cmd)}\n")
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
        for line in process.stdout:
            match = ALF.search(line)
            if match:
                # husk's ALF_PROGRESS covers the whole task; Deadline's CommandLine plugin
                # turns "Progress: N%" lines into the task progress bar
                sys.stdout.write(f"Progress: {match.group(1)}%\n")
                sys.stdout.flush()
                continue  # keeps the log readable
            out(line)
        code = process.wait()
        out(f"=== {'OK' if code == 0 else f'ERROR: husk exited with code {code}'}\n")
    return code


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:9]))
