#!/usr/bin/env python3
"""Run existing native/editor regressions with isolated original-geometry fixtures."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.simple_play_support import BASE, command, fast_request


def main():
    device = json.loads((BASE / 'device.json').read_text())
    assert hashlib.sha256((ROOT / 'artifacts/smash-hit-lab.apk').read_bytes()).hexdigest() == device['apk_sha256']
    runs = [('verify_editor_android.py', 'editor-regression/native'),
            ('verify_editor_runtime.py', 'editor-regression/runtime'),
            ('verify_travel.py', 'travel-regression/native')]
    env = {**os.environ, 'SHLAB_EDITOR_EVIDENCE': str(BASE / 'editor-regression'),
           'SHLAB_TRAVEL_EVIDENCE': str(BASE / 'travel-regression')}
    for harness, area in runs:
        current = fast_request('GET')
        assert current['pid'] == device['native_pid']
        assert current['build_id'] == device['game_build_id']
        out = BASE / area
        out.mkdir(parents=True, exist_ok=True)
        shutil.copy2(BASE / 'device.json', out.parent / 'device.json')
        # These older checks intentionally rebuild original geometry repeatedly.
        # Persistence has separate same-process and process-death checks. Disable
        # replay here so one regression's staged edits cannot alter the next fixture.
        command('workspace', value='edit')
        command('forget_level_edits')
        state = command('control_settings', use_saved_edits=False, automatic=True,
                        move_speed=6, travel_speed=1, look_speed=1,
                        custom_fov=False, play_fog=True, edit_fog=False)
        (out / 'fixture.json').write_text(json.dumps({
            'reason': 'Legacy geometry regressions rebuild original fixtures; saved replay is tested separately.',
            'native_pid': state['pid'], 'play_controls': state['play_controls'],
            'saved_edits': state['saved_edits'],
        }, indent=2) + '\n')
        source = ROOT / 'experiments' / harness
        shutil.copy2(source, out / 'executed-harness.py')
        print('Running', harness, 'on PID', device['native_pid'], flush=True)
        with (out / 'execution.log').open('w') as log:
            subprocess.run([sys.executable, str(source)], cwd=ROOT, env=env,
                           stdout=log, stderr=subprocess.STDOUT, check=True)
        report = json.loads((out / 'report.json').read_text())
        assert report['result'] == 'PASS'
        print(harness, 'PASS', len(report['checks']), flush=True)
    command('workspace', value='edit')
    command('forget_level_edits')
    command('control_settings', use_saved_edits=True)


if __name__ == '__main__':
    main()
