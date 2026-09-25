#!/usr/bin/env python3
"""Prepare the known 960x540 API-30 laboratory emulator for controlled runs.

This helper deliberately uses fresh socket responses during startup: an old
snapshot.json can survive app replacement and is not evidence of readiness.
"""

from pathlib import Path
import argparse
import hashlib
import json
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.lab import adb, shell, forward, fast_request, command
from tools.android_input import start as start_input, send as android_input

APK = ROOT / "artifacts/smash-hit-lab.apk"
PACKAGE = "com.mediocre.smashhit.dev"
parser = argparse.ArgumentParser()
parser.add_argument("--install", action="store_true")
parser.add_argument("--aot", action="store_true", help="Force Android speed compilation; slow on software emulation")
parser.add_argument("--clean-data", action="store_true")
parser.add_argument("--menu", action="store_true")
parser.add_argument("--record", type=Path, default=ROOT / "experiments/device.json")
args = parser.parse_args()

if args.install:
    print(
        adb("install", "-r", "--no-incremental", APK, timeout=300).decode(), flush=True
    )
if args.aot:
    print(
        shell(["cmd", "package", "compile", "-m", "speed", "-f", PACKAGE], timeout=300),
        flush=True,
    )
if args.clean_data:
    print("Resetting only the separate laboratory package:", PACKAGE, flush=True)
    print(shell(["pm", "clear", PACKAGE]), flush=True)
print("Input helper", start_input(), flush=True)
print(
    shell(["am", "start", "-n", PACKAGE + "/com.mediocre.smashhit.MainActivity"]),
    flush=True,
)
forward()
start = time.monotonic()
last_touch = -100.0
touch_attempt = 0
while time.monotonic() - start < 300:
    try:
        state = fast_request("GET")
        if state.get("playing") or (
            args.menu and state.get("game_state") == 1 and state.get("frame", 0) > 20
        ):
            ready = command("enable", value=True)
            print("READY", ready.get("pid"), ready["player_world"], flush=True)
            break
        elapsed = time.monotonic() - start
        if (
            not args.menu
            and state.get("game_state") == 1
            and state.get("native_loaded", True)
            and state.get("native_tick", 150) >= 150
            and elapsed > 12
            and elapsed - last_touch > 30
        ):
            # Observed menu layouts: a saved continuation shifts Start left.
            # Alternate only these two verified Start locations if necessary.
            start_x = (360, 490)[touch_attempt % 2]
            touch_attempt += 1
            android_input("tap", x=start_x, y=265, duration_ms=350)
            print("Touched normal Start; frame", state.get("frame"), flush=True)
            last_touch = elapsed
    except (OSError, ValueError, RuntimeError):
        pass
    time.sleep(1)
else:
    raise SystemExit("Fresh native gameplay did not become ready")

paths = shell(["pm", "path", PACKAGE]).splitlines()
installed = next(
    line[len("package:") :] for line in paths if line.endswith("/base.apk")
)
digest = shell(["sha256sum", installed]).split()[0]
expected = hashlib.sha256(APK.read_bytes()).hexdigest()
assert digest == expected, (digest, expected)
report = dict(
    package=PACKAGE,
    apk_sha256=digest,
    native_pid=ready.get("pid"),
    game_build_id=ready.get("build_id"),
    runtime="API 30 AOSP x86_64, 960x540, SwiftShader, software CPU emulation",
    installed_apk=installed,
)
args.record.parent.mkdir(parents=True, exist_ok=True)
args.record.write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report), flush=True)
