#!/usr/bin/env python3
"""Observe Granny Smith's original ARMv7 runtime after verifying its mapped ELF.

Start a matching Frida server on a rooted research device, forward its port,
and run the original game. This recorder does not inject gameplay commands.
Experimental: Frida 17.17.0's ARM agent crashed before this probe started on
the inspected API 23 emulator. No successful runtime observation is claimed.
"""
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import threading
import time

import frida

ROOT = Path(__file__).resolve().parents[1]
LIBRARY_SHA = 'ab1fd12d06952937aa802c3a4e6a4e2c413a20ebfa51a95ca33ca5cd75f788f1'
APK_SHA = 'cb5eb4d70bab1b2c9da9210b18dfecbde09314c2efd0fa3288fcbacd55efda03'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--serial', default='emulator-5556')
    parser.add_argument('--server', default='127.0.0.1:27043')
    parser.add_argument('--duration', type=float, default=180)
    args = parser.parse_args()
    if not 1 <= args.duration <= 3600:
        parser.error('Duration must be between 1 and 3600 seconds')
    if sha((ROOT / 'incoming/granny-smith/granny-smith.apk').read_bytes()) != APK_SHA:
        raise SystemExit('Unsupported APK')
    adb = [str(ROOT / 'tools/sdk/platform-tools/adb'), '-s', args.serial]
    lines = subprocess.check_output(adb + ['shell', 'ps'], text=True).splitlines()
    processes = [line.split() for line in lines if line.split() and line.split()[-1] == 'com.mediocre.grannysmith']
    if len(processes) != 1:
        raise SystemExit('Exactly one running original Granny Smith process is required')
    pid = int(processes[0][1])
    maps = subprocess.check_output(adb + ['shell', 'cat', f'/proc/{pid}/maps'], text=True)
    library = next(line.split()[-1] for line in maps.splitlines() if line.endswith('/libgrannysmith.so'))
    library_bytes = subprocess.check_output(adb + ['exec-out', 'cat', library])
    if sha(library_bytes) != LIBRARY_SHA:
        raise SystemExit('Mapped Granny Smith library does not match the inspected ARMv7 ELF')
    args.out.mkdir(parents=True, exist_ok=False)
    probe = ROOT / 'experiments/granny_probe.js'
    for source in (probe, Path(__file__)):
        (args.out / source.name).write_bytes(source.read_bytes())
    report = {'created_utc': datetime.now(timezone.utc).isoformat(), 'pid': pid, 'serial': args.serial,
              'apk_sha256': APK_SHA, 'mapped_library': library, 'mapped_library_sha256': sha(library_bytes),
              'probe_sha256': sha(probe.read_bytes()), 'harness_sha256': sha(Path(__file__).read_bytes()),
              'frida_version': frida.__version__, 'read_only': True, 'errors': [],
              'scope': 'Exported-function runtime observation, not a developer addon or editor test.'}
    ready, stop = threading.Event(), threading.Event()
    lock, counts, steps = threading.Lock(), Counter(), []
    size, started = 0, time.monotonic()
    session = script = None
    log_path = args.out / 'events.jsonl'
    with log_path.open('wb') as log:
        def message(message, data):
            nonlocal size
            event = message.get('payload') if message.get('type') == 'send' else message
            if not isinstance(event, dict):
                event = {'event': 'invalid_message', 'payload': str(event)}
            kind = event.get('event', event.get('type', 'unknown'))
            event['host_elapsed_seconds'] = time.monotonic() - started
            try:
                encoded = (json.dumps(event, separators=(',', ':'), allow_nan=False) + '\n').encode()
                with lock:
                    if size + len(encoded) > 8 * 1024 * 1024:
                        raise ValueError('Evidence log reached 8 MiB')
                    log.write(encoded); log.flush(); size += len(encoded); counts[kind] += 1
                    if kind == 'probe_ready':
                        report['probe'] = event; ready.set()
                        print(json.dumps(event), flush=True)
                    elif kind == 'sample' and event.get('last_step'):
                        steps.append(event['last_step'])
                    elif kind == 'error':
                        report['errors'].append(event); stop.set()
            except Exception as error:
                report['errors'].append(str(error)); stop.set()
        try:
            device = frida.get_device_manager().add_remote_device(args.server)
            session = device.attach(pid)
            source = 'globalThis.grannyVerifiedLibrarySha = ' + json.dumps(LIBRARY_SHA) + ';\n' + probe.read_text()
            script = session.create_script(source); script.on('message', message); script.load()
            if not ready.wait(30):
                raise TimeoutError('Probe did not become ready')
            deadline = time.monotonic() + args.duration
            while not stop.wait(1) and time.monotonic() < deadline:
                pass
        except Exception as error:
            report['errors'].append(str(error))
        finally:
            if script is not None:
                try: script.unload()
                except Exception as error: report['errors'].append('Unload: ' + str(error))
            if session is not None:
                try: session.detach()
                except Exception as error: report['errors'].append('Detach: ' + str(error))
    report.update(counts=dict(counts), elapsed_seconds=time.monotonic() - started,
                  events_bytes=size, events_sha256=sha(log_path.read_bytes()),
                  box2d_iteration_pairs=sorted({(s['velocity_iterations'], s['position_iterations']) for s in steps}),
                  observed_dt_range=None if not steps else [min(s['dt'] for s in steps), max(s['dt'] for s in steps)])
    report['observed_expected_box2d_call'] = bool(steps) and all(
        s['velocity_iterations'] == 5 and s['position_iterations'] == 2 and 0 < s['dt'] <= 1 for s in steps)
    report['status'] = 'OBSERVED' if not report['errors'] and report['observed_expected_box2d_call'] else 'INCOMPLETE'
    (args.out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    if report['status'] != 'OBSERVED':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
