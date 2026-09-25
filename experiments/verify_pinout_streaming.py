#!/usr/bin/env python3
"""Controlled PinOut ball/camera/streaming experiments on the original runtime.

Unlike observe_pinout.py this deliberately changes the in-memory ball/camera
pose and can hold Physics::update. It leaves the original table selection,
activation, preloading, deloading and resource functions running. Use a local
research installation with an active original run, not a valuable saved run.
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
import traceback

import frida

ROOT = Path(__file__).resolve().parents[1]
APK_SHA = '81c0f9048c2c12731fefcf0373f0fccb28a2e0626288bc826ba66f5002f37ab7'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def near(a, b, eps=2e-4):
    return len(a) == len(b) and all(abs(x - y) < eps for x, y in zip(a, b))


def world_ball(snapshot):
    p = snapshot['ball']['position']
    return [p[0], p[1] + snapshot['origin_y'], p[2]]


def active(snapshot):
    return [t['index'] for t in snapshot['tables'] if t['active']]


def resident(snapshot):
    return [(t['index'], t['preload_stage'], t['bodies'], t['shared_render_vertices'])
            for t in snapshot['tables'] if t['preload_stage']]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--serial', default='emulator-5554')
    parser.add_argument('--server', default='127.0.0.1:27042')
    args = parser.parse_args()
    apk = ROOT / 'incoming/pinout/pinout.apk'
    if sha(apk.read_bytes()) != APK_SHA:
        raise SystemExit('Unsupported APK')
    args.out.mkdir(parents=True, exist_ok=False)
    adb = str(ROOT / 'tools/sdk/platform-tools/adb')
    pid = int(subprocess.check_output([adb, '-s', args.serial, 'shell', 'pidof',
                                      'com.mediocre.pinout'], text=True).strip())
    sources = [ROOT / 'experiments' / name for name in
               ('pinout_probe.js', 'pinout_streaming_controls.js', 'verify_pinout_streaming.py')]
    for source in sources:
        (args.out / source.name).write_bytes(source.read_bytes())
    report = {'created_utc': datetime.now(timezone.utc).isoformat(), 'apk_sha256': APK_SHA,
              'pid': pid, 'serial': args.serial, 'frida_version': frida.__version__,
              'sources': {p.name: sha(p.read_bytes()) for p in sources},
              'mutations': 'Ball/camera pose, view rotation and Physics::update hold. Original Level/Table logic runs.',
              'checks': [], 'errors': [], 'cleanup': None}
    condition, ready = threading.Condition(), threading.Event()
    results, counts = {}, Counter()
    started = time.monotonic()
    size = 0
    session = script = None
    log_path = args.out / 'events.jsonl'
    counter = 0
    with log_path.open('wb') as log:
        def message(message, data):
            nonlocal size
            event = message.get('payload') if message.get('type') == 'send' else message
            if not isinstance(event, dict):
                event = {'event': 'invalid_message', 'payload': str(event)}
            kind = event.get('event', event.get('type', 'unknown'))
            counts[kind] += 1
            event['host_elapsed_seconds'] = time.monotonic() - started
            try:
                encoded = (json.dumps(event, separators=(',', ':'), allow_nan=False) + '\n').encode()
                with condition:
                    if size + len(encoded) > 32 * 1024 * 1024:
                        raise ValueError('Evidence log reached its 32 MiB limit')
                    log.write(encoded); log.flush(); size += len(encoded)
                    if kind == 'probe_ready':
                        report['probe'] = event
                    elif kind == 'streaming_controls_ready':
                        ready.set()
                    elif kind == 'experiment_result':
                        results[event['id']] = event
                    elif kind in ('error', 'read_error', 'experiment_error'):
                        report['errors'].append(event)
                    condition.notify_all()
            except Exception as error:
                report['errors'].append(str(error))

        def command(op='sample', _allow_errors=False, **fields):
            nonlocal counter
            counter += 1
            cmd = {'id': str(counter), 'op': op, **fields}
            script.exports_sync.command(cmd)
            deadline = time.monotonic() + 180
            with condition:
                while cmd['id'] not in results:
                    if report['errors'] and not _allow_errors:
                        raise RuntimeError(str(report['errors'][-1]))
                    left = deadline - time.monotonic()
                    if left <= 0:
                        raise TimeoutError('Native frame did not acknowledge ' + op)
                    condition.wait(min(left, 1))
                return results.pop(cmd['id'])

        def save(name, event):
            (args.out / (name + '.json')).write_text(json.dumps(event, indent=2) + '\n')
            s = event['snapshot']
            print(json.dumps({'phase': name, 'tick': event['tick'],
                              'table': (s['current_table'] or {}).get('index'),
                              'active': active(s), 'resident': resident(s)}), flush=True)
            return s

        def wait_ticks(event, n=5, timeout=120):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                now = command()
                if now['tick'] >= event['tick'] + n:
                    return now
                time.sleep(.5)
            raise TimeoutError('No native tick progress')

        def check(name, result, evidence):
            report['checks'].append({'name': name, 'passed': bool(result), 'evidence': evidence})
            if not result:
                raise AssertionError(name)

        try:
            device = frida.get_device_manager().add_remote_device(args.server)
            session = device.attach(pid)
            source = 'globalThis.pinoutStreamingExperiment = true;\n' + sources[0].read_text() + '\n' + sources[1].read_text()
            script = session.create_script(source)
            script.on('message', message); script.load()
            if not ready.wait(30):
                raise TimeoutError('Controls did not confirm the exact build')
            first = command('hold_here')
            base = save('01-hold', wait_ticks(first))
            check('Native run and table metadata', base['game_state'] == 2 and len(base['tables']) == 125,
                  '01-hold.json')
            # Finish any in-flight background preloading before comparing caches.
            deadline = time.monotonic() + 150
            while any(0 < t['preload_stage'] < 100 for t in base['tables']):
                if time.monotonic() >= deadline:
                    raise TimeoutError('Initial preloading did not settle')
                base = command()['snapshot']; time.sleep(.5)
            base_event = command(); base = save('02-stationary-baseline', base_event)
            stationary_event = wait_ticks(base_event, 15)
            stationary = save('03-stationary', stationary_event)
            check('Held ball stays fixed with native table ticks running',
                  near(world_ball(base), world_ball(stationary)) and resident(base) == resident(stationary)
                  and stationary_event['controls']['physics_held'] > base_event['controls']['physics_held'],
                  ['02-stationary-baseline.json', '03-stationary.json'])
            baseline_active, baseline_resident = active(base), resident(base)
            camera0 = base['render_camera_position'].copy(); camera0[1] += base['origin_y']
            for axis, label in enumerate(('sideways', 'forward', 'upward')):
                target = camera0.copy(); target[axis] += 100 if axis == 1 else 20
                event = command('camera_world', position=target)
                s = save('04-camera-' + label, wait_ticks(event))
                camera = s['render_camera_position'].copy(); camera[1] += s['origin_y']
                check('Camera ' + label + ' does not change table residency',
                      near(camera, target) and near(world_ball(s), world_ball(base)) and
                      active(s) == baseline_active and resident(s) == baseline_resident,
                      '04-camera-' + label + '.json')
            normal = command('camera_world', position=camera0)['snapshot']
            back = save('05-look-back', wait_ticks(command('look_back', value=True)))
            dot = sum(a * b for a, b in zip(normal['render_camera_rotation'], back['render_camera_rotation']))
            check('Looking behind does not load tables', abs(dot) < 1e-4 and
                  active(back) == baseline_active and resident(back) == baseline_resident, '05-look-back.json')
            command('look_back', value=False)
            for axis, value, label in ((0, 20, 'sideways'), (2, 20, 'up'), (2, -20, 'down')):
                target = world_ball(base); target[axis] += value
                s = save('06-ball-' + label, wait_ticks(command('ball_world', position=target)))
                check('Ball ' + label + ' does not advance longitudinal tables',
                      near(world_ball(s), target) and active(s) == baseline_active
                      and resident(s) == baseline_resident, '06-ball-' + label + '.json')
            forward = save('07-ball-table-10', command('table', index=10))
            check('Longitudinal jump selects table 10 and activates 9 through 12',
                  forward['current_table']['index'] == 10 and active(forward) == [9, 10, 11, 12],
                  '07-ball-table-10.json')
            check('Far jump retains old cached resources outside the new active window',
                  all(not forward['tables'][i]['active'] and forward['tables'][i]['preload_stage'] == 100
                      and forward['tables'][i]['bodies'] > 0 for i in (0, 1, 2, 3)),
                  '07-ball-table-10.json')
            check('Far jump does not instantiate every intermediate table body set',
                  all(forward['tables'][i]['streamed_bodies'] == 0 and forward['tables'][i]['preload_stage'] == 0
                      for i in (4, 5, 6, 7)), '07-ball-table-10.json')
            backward = save('08-ball-table-1', command('table', index=1))
            check('Backward jump restores the earlier active table window',
                  backward['current_table']['index'] == 1 and active(backward) == [0, 1, 2, 3],
                  '08-ball-table-1.json')
            for index in (2, 3, 4):
                s = save('09-adjacent-table-' + str(index), command('table', index=index))
                if index == 3:
                    check('Adjacent progress deloads table zero authored bodies while retaining metadata and its base body',
                          s['tables'][0]['address'] == base['tables'][0]['address'] and
                          s['tables'][0]['preload_stage'] == 0 and s['tables'][0]['streamed_bodies'] == 0 and
                          s['tables'][0]['retained_table_body'] == base['tables'][0]['retained_table_body'],
                          '09-adjacent-table-3.json')
            restored = save('10-restored-position', command('restore'))
            check('Original position restored through native table selection',
                  near(world_ball(restored), world_ball(first['snapshot'])) and
                  restored['current_table']['index'] == first['snapshot']['current_table']['index'],
                  '10-restored-position.json')
            release = command('release')
            resumed_event = wait_ticks(release)
            resumed = save('11-original-physics-resumed', resumed_event)
            check('Original physics resumes after controls release',
                  resumed_event['controls']['physics_calls'] > release['controls']['physics_calls']
                  and not resumed_event['controls']['physics_frozen'] and resumed['game_state'] == 2,
                  '11-original-physics-resumed.json')
        except Exception as error:
            report['errors'].append(str(error)); report['traceback'] = traceback.format_exc()
        finally:
            if script is not None and ready.is_set():
                try:
                    cleanup = command('release', _allow_errors=True)
                    report['cleanup'] = cleanup['controls']
                except Exception as error:
                    report['errors'].append('Release cleanup: ' + str(error))
            if script is not None:
                try: script.unload()
                except Exception as error: report['errors'].append('Unload: ' + str(error))
            if session is not None:
                try: session.detach()
                except Exception as error: report['errors'].append('Detach: ' + str(error))
    report.update(status='PASS' if not report['errors'] else 'INCOMPLETE', counts=dict(counts),
                  elapsed_seconds=time.monotonic() - started, events_bytes=size,
                  events_sha256=sha(log_path.read_bytes()))
    (args.out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    if report['status'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
