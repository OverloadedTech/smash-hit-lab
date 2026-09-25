"""Shared evidence helpers for real-device Play/Edit experiments."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.lab import command, snapshot, fast_request, step, adb, PACKAGE
from tools.android_input import send
from experiments.phase2_controls import reset, wait_for, near

BASE = ROOT / os.environ.get('SHLAB_PLAY_EVIDENCE', 'experiments/simple_play')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ready():
    s = wait_for(lambda s: not s['navigation']['loading'], timeout=240)
    assert not s['navigation']['error'], s['navigation']['error']
    assert all(b['loaded'] for b in s['current_room']['batches'])
    return s


def fresh():
    command('enable', value=True)
    if snapshot()['playing']:
        command('travel', enabled=False)
    reset()
    return ready()


def play_paused(mode='free', rotation=(0, 0, 0), position=(30, 20, -25)):
    return command('batch', commands=[
        {'op': 'workspace', 'value': 'play'},
        {'op': 'play_mode', 'value': mode},
        {'op': 'play_backward', 'value': False} if mode == 'rails' else {'op': 'play_stop', 'value': False},
        {'op': 'teleport', 'target': 'player', 'position': list(position)},
        {'op': 'look', 'rotation_degrees': list(rotation)},
        {'op': 'freeze', 'value': True},
    ])


def steps(count):
    before = snapshot()
    assert before['frozen'] and not before['navigation']['loading']
    step(count, timeout=240)
    after = ready()
    assert after['updates'] - before['updates'] == count, (before['updates'], after['updates'], count)
    assert after['frozen'] and after['steps_remaining'] == 0
    return after


class Evidence:
    def __init__(self, area, harness):
        self.out = BASE / area
        self.out.mkdir(parents=True, exist_ok=True)
        self.device = json.loads((BASE / 'device.json').read_text())
        self.identity()
        assert sha(ROOT / 'artifacts/smash-hit-lab.apk') == self.device['apk_sha256']
        dependencies = [Path(__file__), ROOT/'tools/lab.py', ROOT/'tools/android_input.py',
                        ROOT/'experiments/phase2_controls.py']
        if 'experiments.verify_simple_play' in sys.modules:
            dependencies.append(ROOT/'experiments/verify_simple_play.py')
        archived = BASE/'harness-sources'; archived.mkdir(exist_ok=True)
        for p in dependencies: (archived/(sha(p)+p.suffix)).write_bytes(p.read_bytes())
        self.report = {**self.device, 'start_utc': datetime.now(timezone.utc).isoformat(),
                       'harness_sha256': sha(harness),
                       'helper_sources': {str(p.relative_to(ROOT)): sha(p) for p in dependencies},
                       'input_helper': send('info'), 'checks': [], 'result': 'RUNNING'}
        self.save('report', self.report)
        (self.out/'executed-harness.py').write_bytes(Path(harness).read_bytes())

    def identity(self):
        current = fast_request('GET')
        assert current['pid'] == self.device['native_pid'], (current['pid'], self.device)
        assert current['build_id'] == self.device['game_build_id']
        return current

    def save(self, name, data=None):
        data = self.identity() if data is None else data
        (self.out/(name+'.json')).write_text(json.dumps(data, indent=2)+'\n')
        return data

    def check(self, name, **fields):
        self.identity()
        self.report['checks'].append({'name': name, 'result': 'PASS', **fields})
        self.save('report', self.report)
        print(name, 'PASS', fields, flush=True)

    def finish(self):
        self.report.update(result='PASS', finish_utc=datetime.now(timezone.utc).isoformat())
        self.save('report', self.report)

    def failure(self, error):
        self.report.update(result='FAIL', error=repr(error), finish_utc=datetime.now(timezone.utc).isoformat())
        self.save('report', self.report)
        try: self.save('failure-state')
        except Exception: pass

    def screen(self, name):
        (self.out/(name+'.png')).write_bytes(adb('exec-out', 'screencap', '-p', timeout=120))


class UI:
    def __init__(self, evidence):
        self.evidence = evidence
        self.actions = []
        self.sequence = 0

    def hierarchy(self, name='window'):
        deadline = time.monotonic()+30
        while True:
            try: xml = send('hierarchy')['xml']; break
            except RuntimeError as error:
                if 'No active accessibility window' not in str(error) or time.monotonic() > deadline: raise
                time.sleep(.3)
        self.sequence += 1
        name = re.sub(r'[^a-zA-Z0-9_.-]+', '-', name)
        (self.evidence.out/(f'{self.sequence:03d}-{name}.xml')).write_text(xml)
        root = ET.fromstring(xml)
        assert not any("isn't responding" in n.get('text', '') for n in root.iter('node')), 'Android ANR shown; record and recover explicitly before restarting the test'
        return root

    @staticmethod
    def find(root, text=None, prefix=None, cls=None):
        for n in root.iter('node'):
            if n.get('visible') == 'false' or n.get('enabled') == 'false': continue
            if text is not None and n.get('text','').casefold() != text.casefold(): continue
            if prefix is not None and not n.get('text', '').casefold().startswith(prefix.casefold()): continue
            if cls is not None and n.get('class') != cls: continue
            bounds = list(map(int, re.findall(r'-?\d+', n.get('bounds', ''))))
            if len(bounds) == 4 and bounds[2] > bounds[0] and bounds[3]-bounds[1] >= 24:
                return n, bounds
        return None

    def visible(self, text=None, prefix=None, timeout=30):
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            found = self.find(self.hierarchy('await-control'), text=text, prefix=prefix)
            if found: return found
            time.sleep(.3)
        raise AssertionError('Visible control did not appear: '+str(text or prefix))

    def tap(self, text=None, prefix=None, scroll=False):
        for _ in range(18):
            root = self.hierarchy('tap-control')
            found = self.find(root, text=text, prefix=prefix)
            if found:
                node, b = found
                self.actions.append({'text': node.get('text'), 'bounds': b, 'checked': node.get('checked')})
                self.evidence.save('actions', self.actions)
                send('tap', x=(b[0]+b[2])/2, y=(b[1]+b[3])/2, duration_ms=250)
                return
            if scroll:
                item = self.find(root, cls='android.widget.ScrollView')
                if item:
                    b = item[1]
                    send('drag', x=(b[0]+b[2])/2, y=b[1]+(b[3]-b[1])*.82,
                         to_x=(b[0]+b[2])/2, to_y=b[1]+(b[3]-b[1])*.25, duration_ms=500)
            time.sleep(.35)
        raise AssertionError('Visible control not found: '+str(text or prefix))

    def to_top(self):
        for _ in range(9):
            root = self.hierarchy('scroll-top')
            if self.find(root, prefix='Forward speed'): return
            found = self.find(root, cls='android.widget.ScrollView')
            assert found, 'Settings scroll view missing'
            b = found[1]
            send('drag', x=(b[0]+b[2])/2, y=b[1]+40, to_x=(b[0]+b[2])/2,
                 to_y=b[3]-20, duration_ms=350)

    def resume_drawer(self):
        root = self.hierarchy('before-play-input')
        if self.find(root, 'Resume game'): self.tap('Resume game')
