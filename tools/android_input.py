#!/usr/bin/env python3
"""Persistent adb-shell input injector for laboratory UI tests.

Starts Java once instead of starting a slow app_process for each input command
under software CPU emulation. All events enter Android's actual InputManager.
The helper is separate from the APK and accepts only adb shell/root peers.
"""
from pathlib import Path
import json
import os
import socket
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.lab import adb, ADB

PORT = int(os.environ.get('MEDIOCRE_INPUT_PORT', '18766'))

def send(op, **fields):
    with socket.create_connection(('127.0.0.1', PORT), timeout=3) as connection:
        connection.settimeout(90)
        connection.sendall((json.dumps(dict(op=op, **fields)) + '\n').encode())
        with connection.makefile('rb') as stream:
            answer = json.loads(stream.readline())
        if not answer.get('ok'):
            raise RuntimeError('Android input injection failed: ' + str(answer))
        return answer

def start(restart=False):
    adb('forward', 'tcp:' + str(PORT), 'localabstract:smashhit_input_lab')
    try:
        running = send('info')
        if not restart:
            return running
        # PID is returned by this experiment helper, not by a process-name glob.
        adb('shell', 'kill', str(running['pid']))
        time.sleep(1)
    except (OSError, ValueError):
        pass
    from tools.build_debug import JDK, SDK, BT, run
    work = ROOT / 'build/input-driver'
    (work / 'classes').mkdir(parents=True, exist_ok=True)
    (work / 'dex').mkdir(exist_ok=True)
    run(JDK / 'bin/javac', '--release', '8', '-classpath', SDK / 'platforms/android-35/android.jar',
        '-d', work / 'classes', ROOT / 'experiments/input_driver/DevInput.java')
    run(JDK / 'bin/jar', 'cf', work / 'input-classes.jar', '-C', work / 'classes', '.')
    run(BT / 'd8', '--min-api', '23', '--lib', SDK / 'platforms/android-35/android.jar',
        '--output', work / 'dex', work / 'input-classes.jar')
    with zipfile.ZipFile(work / 'shdev-input.jar', 'w') as jar:
        jar.write(work / 'dex/classes.dex', 'classes.dex')
    adb('push', work / 'shdev-input.jar', '/data/local/tmp/shdev-input.jar', timeout=180)
    adb('forward', 'tcp:' + str(PORT), 'localabstract:smashhit_input_lab')
    try:
        return send('info')
    except (OSError, ValueError):
        pass
    with (ROOT / 'analysis/reports/input-driver.log').open('w') as log:
        launch = 'CLASSPATH=/data/local/tmp/shdev-input.jar app_process /system/bin dev.smashhit.testing.DevInput'
        subprocess.Popen([str(ADB), 'shell', launch], stdout=log, stderr=subprocess.STDOUT,
                         start_new_session=True)
    for _ in range(120):
        try:
            return send('info')
        except (OSError, ValueError):
            time.sleep(1)
    raise TimeoutError('Input helper did not become ready; inspect input-driver.log')

if __name__ == '__main__':
    if len(sys.argv) == 1 or sys.argv[1] == 'start':
        print(json.dumps(start(restart='--restart' in sys.argv)))
    else:
        print(json.dumps(send(**json.loads(sys.argv[1]))))
