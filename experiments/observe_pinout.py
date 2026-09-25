#!/usr/bin/env python3
"""Record bounded, read-only PinOut native lifecycle evidence via Frida.

Requires the original supplied PinOut running on a rooted x86_64 Android device
and a matching Frida server forwarded to localhost:27042. Input may be supplied
normally while this recorder runs; it does not alter gameplay or stored data.
"""
from datetime import datetime, timezone
from pathlib import Path
from collections import Counter
import argparse
import hashlib
import json
import subprocess
import threading
import time

import frida

ROOT = Path(__file__).resolve().parents[1]
APK_SHA = '81c0f9048c2c12731fefcf0373f0fccb28a2e0626288bc826ba66f5002f37ab7'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--duration', type=float, default=180)
    parser.add_argument('--serial', default='emulator-5554')
    parser.add_argument('--server', default='127.0.0.1:27042')
    parser.add_argument('--apk', type=Path, default=ROOT / 'incoming/pinout/pinout.apk')
    args = parser.parse_args()
    if not 1 <= args.duration <= 3600:
        parser.error('Duration must be between 1 and 3600 seconds')
    if sha(args.apk) != APK_SHA:
        raise SystemExit('Unsupported input APK; independently map a new build first')
    args.out.mkdir(parents=True, exist_ok=False)
    adb = str(ROOT / 'tools/sdk/platform-tools/adb')
    pid_text = subprocess.check_output([adb, '-s', args.serial, 'shell', 'pidof',
                                       'com.mediocre.pinout'], text=True).strip()
    pid = int(pid_text)
    probe_path = ROOT / 'experiments/pinout_probe.js'
    (args.out / 'pinout_probe.js').write_bytes(probe_path.read_bytes())
    (args.out / 'observe_pinout.py').write_bytes(Path(__file__).read_bytes())
    report = {
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'apk_sha256': APK_SHA, 'pid': pid, 'serial': args.serial,
        'read_only_probe': True, 'requested_duration_seconds': args.duration,
        'probe_sha256': sha(probe_path), 'harness_sha256': sha(Path(__file__)),
        'frida_version': frida.__version__, 'errors': [], 'detached': [],
        'scope': 'Original runtime observation only; not an addon functionality test.'
    }
    counts, size = Counter(), 0
    ready, stop = threading.Event(), threading.Event()
    lock = threading.Lock()
    started = time.monotonic()
    log_path = args.out / 'events.jsonl'
    with log_path.open('wb') as log:
        def record(event):
            nonlocal size
            data = (json.dumps(event, separators=(',', ':'), allow_nan=False) + '\n').encode()
            with lock:
                if size + len(data) > 16 * 1024 * 1024:
                    if not stop.is_set():
                        report['errors'].append('16 MiB evidence limit reached')
                    stop.set()
                    return
                log.write(data); log.flush(); size += len(data)

        def on_message(message, data):
            event = message.get('payload') if message.get('type') == 'send' else message
            if not isinstance(event, dict):
                event = {'event': 'unexpected_message', 'data': str(event)}
            kind = event.get('event', event.get('type', 'unknown'))
            counts[kind] += 1
            try:
                record({'host_elapsed_seconds': time.monotonic() - started, **event})
            except Exception as error:
                report['errors'].append('Record error: ' + str(error)); stop.set()
            if kind == 'probe_ready':
                report['probe'] = event; ready.set()
                print(json.dumps({'event': 'attached', 'pid': pid, 'build_id': event['build_id']}), flush=True)
            if kind in ('error', 'read_error'):
                report['errors'].append(event)
                print(json.dumps(event), flush=True)
                stop.set()

        def detached(reason, crash):
            report['detached'].append({'reason': reason, 'crash': str(crash) if crash else None})
            stop.set()

        session = script = None
        try:
            device = frida.get_device_manager().add_remote_device(args.server)
            session = device.attach(pid)
            session.on('detached', detached)
            script = session.create_script(probe_path.read_text())
            script.on('message', on_message)
            script.load()
            if not ready.wait(30):
                raise TimeoutError('Probe did not confirm its exact build')
            deadline = time.monotonic() + args.duration
            while not stop.wait(1) and time.monotonic() < deadline:
                pass
        except Exception as error:
            report['errors'].append(str(error))
        finally:
            if script is not None:
                try:
                    script.unload()
                except Exception as error:
                    report['errors'].append('Unload: ' + str(error))
            if session is not None:
                session.off('detached', detached)
                try:
                    session.detach()
                except Exception as error:
                    report['errors'].append('Detach: ' + str(error))
    report.update(elapsed_seconds=time.monotonic() - started, counts=dict(counts),
                  log_bytes=size, events_sha256=sha(log_path))
    report['status'] = ('OBSERVED' if not report['errors'] and not report['detached']
                        and counts['sample'] > 0 else 'INCOMPLETE')
    (args.out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    if report['status'] != 'OBSERVED':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
