#!/usr/bin/env python3
"""Use the real Android Travel tab, then inspect native poses and rooms."""
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
from tools.lab import command, snapshot, adb
from tools.android_input import send
from experiments.phase2_controls import wait_for, near
from experiments.verify_travel import fresh, ready

BASE = ROOT / os.environ.get('SHLAB_TRAVEL_EVIDENCE', 'experiments/travel_tools')
OUT = BASE / 'ui'
OUT.mkdir(parents=True, exist_ok=True)
actions = []


def save(name, data):
    (OUT / (name+'.json')).write_text(json.dumps(data, indent=2)+'\n')
    return data


def hierarchy(name):
    deadline = time.monotonic()+25
    while True:
        try:
            xml = send('hierarchy')['xml']
            break
        except RuntimeError as error:
            if 'No active accessibility window' not in str(error) or time.monotonic() >= deadline:
                raise
            time.sleep(.3)
    (OUT/(name+'.xml')).write_text(xml)
    return ET.fromstring(xml)


def find(root, text=None, cls=None, prefix=None):
    for node in root.iter('node'):
        if node.get('visible') == 'false' or node.get('enabled') == 'false': continue
        if text is not None and node.get('text') != text: continue
        if prefix is not None and not node.get('text', '').startswith(prefix): continue
        if cls is not None and node.get('class') != cls: continue
        b = list(map(int, re.findall(r'-?\d+', node.get('bounds', ''))))
        if len(b) == 4 and b[2] > b[0] and b[3]-b[1] > 15: return node, b
    return None


def tap(text, name, native=False, scroll=False, prefix=None, list_start=False):
    for attempt in range(16):
        root = hierarchy(name+str(attempt))
        found = find(root, text=text, prefix=prefix)
        if found:
            node, b = found
            actions.append({'control': node.get('text'), 'bounds': b, 'checked_before': node.get('checked')})
            before = snapshot()['last_command']
            send('tap', x=(b[0]+b[2])/2, y=(b[1]+b[3])/2, duration_ms=250)
            if native:
                wait_for(lambda s: s['last_command'] > before)
                command('snapshot')
            else:
                time.sleep(.7)
                label = node.get('text', '')
                title = ('Campaign levels' if label.startswith('Level ') else
                         'Player travel speed' if label.startswith('Speed · ') else
                         'Rooms in selected level' if label.startswith(('Choose native room', 'Room ')) else None)
                previous_dialog = next((t for t in ['Campaign levels', 'Player travel speed', 'Rooms in selected level']
                                        if find(root, t)), None)
                if title or previous_dialog:
                    deadline = time.monotonic()+30
                    while time.monotonic() < deadline:
                        shown = hierarchy(name+'_window')
                        if (title and find(shown, title)) or (previous_dialog and not find(shown, previous_dialog)):
                            break
                        time.sleep(.3)
                    else: raise AssertionError('Dialog transition did not finish: '+label)
            return
        listing = find(root, cls='android.widget.ListView') if list_start else None
        if listing:
            _, b = listing
            actions.append({'control': 'Scroll list toward beginning', 'bounds': b})
            send('drag', x=(b[0]+b[2])/2, y=b[1]+(b[3]-b[1])*.25,
                 to_x=(b[0]+b[2])/2, to_y=b[1]+(b[3]-b[1])*.8, duration_ms=500)
            time.sleep(.5)
        elif scroll:
            send('drag', x=820, y=440, to_x=820, to_y=245, duration_ms=420)
        else:
            time.sleep(.4)
    raise AssertionError('Visible Travel control not found: ' + str(text or prefix))


def top():
    for _ in range(6):
        send('drag', x=825, y=240, to_x=825, to_y=450, duration_ms=220)
    time.sleep(.5)


def screen(name):
    (OUT/(name+'.png')).write_bytes(adb('exec-out', 'screencap', '-p', timeout=120))


def run():
    device = json.loads((BASE/'device.json').read_text())
    assert snapshot()['pid'] == device['native_pid']
    report = {**device, 'start_utc': datetime.now(timezone.utc).isoformat(),
              'harness_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'input_helper': send('info'), 'checks': [], 'result': 'RUNNING'}
    save('report', report)

    def check(name, **fields):
        assert snapshot()['pid'] == device['native_pid']
        report['checks'].append({'name': name, 'result': 'PASS', **fields})
        save('report', report); save('actions', actions)
        print(name, 'PASS', fields, flush=True)

    root = hierarchy('00_before')
    if find(root, 'CLOSE'): tap('CLOSE', '00_close_dialog')
    fresh()
    root = hierarchy('00_ready')
    if find(root, 'DEV'): tap('DEV', '00_open', native=True)
    elif find(root, 'TOOLS'): tap('TOOLS', '00_open')
    tap('Travel', '01_tab'); top()
    initial = hierarchy('01_initial_preferences')
    if any(n.get('text') == 'Arrive at the end' and n.get('checked') == 'true' for n in initial.iter('node')):
        tap('Arrive at the end', '01_clear_end_preference', scroll=True)
        top()
    node, b = find(hierarchy('01_lens'), cls='android.widget.EditText')
    send('tap', x=(b[0]+b[2])/2, y=(b[1]+b[3])/2, duration_ms=250)
    # The product field selects its current contents on focus. These are real
    # numeric KeyEvents, not an accessibility text assignment or bridge call.
    for code in [8, 8, 7]: send('key', code=code, duration_ms=80)
    send('key', code=4, duration_ms=80)  # Dismiss the soft keyboard.
    tap('Apply FOV', '02_apply_fov', native=True)
    state = save('03_numeric_fov', wait_for(lambda s: s['fov_horizontal'] == 110))
    assert state['navigation']['last_draw_fov'] == 110
    screen('android-travel-fov')
    node, b = find(hierarchy('04_slider'), cls='android.widget.SeekBar')
    before = snapshot()['last_command']
    send('drag', x=b[0]+30, y=(b[1]+b[3])/2, to_x=b[2]-45, to_y=(b[1]+b[3])/2, duration_ms=500)
    wait_for(lambda s: s['last_command'] > before)
    state = save('05_slider_fov', snapshot())
    assert 90 < state['fov_horizontal'] < 135 and state['fov_horizontal'] != 110
    tap('Original FOV', '06_original', native=True)
    state = wait_for(lambda s: not s['navigation']['fov_override'])
    assert abs(state['fov_horizontal'] - state['original_fov_horizontal']) < .001
    check('actual_numeric_slider_and_original_fov_controls')

    tap('Watch back · run', '07_back', native=True, scroll=True)
    before = snapshot()
    wait_for(lambda s: s['updates'] >= before['updates']+5)
    state = save('08_watch_back', snapshot())
    assert state['world_running'] and state['navigation']['follow_player_view']
    assert abs(abs(state['camera_rotation_degrees'][1])-180) < .001
    assert near(state['camera_world'], state['player_world'])
    assert state['player_world'][2] < before['player_world'][2]
    send('drag', x=430, y=250, to_x=520, to_y=295, duration_ms=450)
    turned = wait_for(lambda s: abs(s['camera_rotation_degrees'][0]) > 2)
    assert turned['navigation']['follow_player_view']
    tap('Free camera · pause', '09_pause', native=True, scroll=True)
    state = save('10_paused', wait_for(lambda s: s['frozen']))
    assert not state['world_running'] and not state['navigation']['follow_player_view']
    check('watch_back_runs_player_touch_drag_rotates_and_free_camera_pauses')

    tap('Forward', '11_forward', native=True, scroll=True)
    assert snapshot()['navigation']['direction'] == 1
    tap(None, '12_speed_chooser', prefix='Speed · ', scroll=True)
    tap('5×', '12_choose_speed')
    tap('Apply travel speed', '13_apply_speed', native=True, scroll=True)
    state = save('14_speed_five', wait_for(lambda s: s['navigation']['speed_multiplier'] == 5))
    assert state['world_running'] and state['navigation']['travel_enabled']
    top(); tap('Hold player', '15_hold', native=True, scroll=True)
    before = snapshot(); wait_for(lambda s: s['updates'] >= before['updates']+3)
    state = save('16_held_running', snapshot())
    assert near(before['player_world'], state['player_world']) and state['world_running']
    tap('Reverse', '17_reverse', native=True)
    before = snapshot(); wait_for(lambda s: s['updates'] >= before['updates']+3)
    state = save('18_reverse', snapshot())
    assert state['player_world'][2] > before['player_world'][2]
    assert state['navigation']['direction'] == -1
    top(); tap('Free camera · pause', '19_pause', native=True, scroll=True)
    check('visible_forward_speed_hold_and_reverse_controls', speed_multiplier=5)

    tap('Unlock all levels · this session', '20_unlock', native=True, scroll=True)
    state = wait_for(lambda s: s['navigation']['unlocked'])
    assert all(l['available'] for l in state['navigation']['levels'])
    tap(None, '21_level_chooser', prefix='Level ', scroll=True)
    tap('2 · holodeck', '22_select_holodeck')
    tap('Jump to level · pause', '23_jump', native=True, scroll=True)
    wait_for(lambda s: s['navigation']['current_checkpoint'] == 2)
    state = save('24_holodeck', ready())
    assert state['current_room']['name'].startswith('holodeck/') and not state['world_running']
    tap('Next level', '25_next', native=True, scroll=True)
    wait_for(lambda s: s['navigation']['current_checkpoint'] == 3); ready()
    tap('Previous level', '26_previous', native=True)
    wait_for(lambda s: s['navigation']['current_checkpoint'] == 2); ready()
    check('visible_unlock_level_chooser_and_neighbour_jumps')

    tap('Choose native room…', '27_choose_room', scroll=True)
    rows = [r for r in snapshot()['navigation']['rooms'] if r['checkpoint'] == 2]
    target = rows[1]
    tap('Room '+str(target['index'])+' · '+target['name'], '28_room')
    tap('Jump to room · pause', '29_jump_room', native=True, scroll=True)
    wait_for(lambda s: s['current_room']['index'] == target['index'])
    state = save('30_room', ready())
    assert not state['world_running']
    top(); tap('Arrive at the end', '31_at_end', scroll=True)
    tap('Jump to level · pause', '32_jump_end', native=True, scroll=True)
    state = save('33_level_end', ready())
    assert state['current_room']['index'] == rows[-1]['index']
    assert abs(state['current_room']['path_distance'] - (state['current_room']['length']-1)) < .001
    screen('android-travel-levels')
    tap('Reverse selected level · run', '34_reverse_level', native=True, scroll=True)
    state = ready(); before = snapshot()
    wait_for(lambda s: s['updates'] >= before['updates']+3)
    state = save('35_reverse_selected', snapshot())
    assert state['navigation']['direction'] == -1 and state['world_running']
    assert state['player_world'][2] > before['player_world'][2]
    top(); tap('Free camera · pause', '36_pause', native=True, scroll=True)
    check('visible_native_room_arrive_at_end_and_reverse_level_controls', room=target['name'])

    # Start a chosen checkpoint from the homepage through the same visible
    # control. The native pending-start path and menu transition must finish
    # even though the requested final state is a paused inspection world.
    fresh()
    command('transition', target='menu', capture=False)
    wait_for(lambda s: s['context'] == 'menu')
    command('mode', value='inspect')
    tap('Travel', '37_menu_tab'); top()
    tap('Unlock all levels · this session', '38_menu_unlock', native=True, scroll=True)
    tap(None, '39_menu_choose', prefix='Level ', scroll=True)
    # Wait for actual list bounds and scroll until the preceding item is
    # visible; an early drag during dialog creation can miss the ListView.
    tap('1 · night', '40_menu_select', list_start=True)
    # The previous end-of-level preference remains visible and intentional.
    tap('Jump to level · pause', '41_menu_jump', native=True, scroll=True)
    wait_for(lambda s: s['playing'] and s['navigation']['current_checkpoint'] == 1)
    state = save('42_menu_jump_ready', ready())
    assert state['context'] == 'game' and not state['world_running']
    assert state['menu_transition'] <= .001
    check('visible_homepage_level_jump_completes_native_transition')

    fresh()
    report.update(result='PASS', finish_utc=datetime.now(timezone.utc).isoformat())
    save('report', report); save('actions', actions)


if __name__ == '__main__':
    try: run()
    except Exception as error:
        save('failure', {'error': repr(error), 'snapshot': snapshot(), 'actions': actions})
        raise
