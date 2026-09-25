#!/usr/bin/env python3
"""Run device-mutating phases sequentially; stop and preserve evidence on failure."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ["ui_editor", "touch", "raw_pose", "editor", "noclip", "boundary", "lateral", "music",
           "idle", "teleport", "camera", "camera_streaming", "editor_rebased", "normal", "regression"]
for phase in sys.argv[1:] or DEFAULT:
    log = ROOT / "analysis/reports" / ("experiment-" + phase + ".log")
    print("Running", phase, "-", log, flush=True)
    with log.open("w") as output:
        result = subprocess.run([sys.executable, "-u", "experiments/run_experiments.py", phase],
                                cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
    print(log.read_text(), flush=True)
    if result.returncode:
        raise SystemExit(result.returncode)
