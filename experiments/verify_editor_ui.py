#!/usr/bin/env python3
"""Touch the Android editor controls and verify native world changes behind them."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.lab import command, snapshot, adb
from tools.android_input import send
from experiments.phase2_controls import reset, near, wait_for

BASE = ROOT / os.environ.get('SHLAB_EDITOR_EVIDENCE', 'experiments/editor_improvements')
OUT = BASE / 'ui'
OUT.mkdir(parents=True, exist_ok=True)
actions=[]
HOLD_MS=int(os.environ.get('SHLAB_UI_HOLD_MS','1250'))


def save(name, data):
    (OUT/(name+'.json')).write_text(json.dumps(data, indent=2)+'\n')
    return data


def hierarchy(name):
    deadline=time.monotonic()+20
    while True:
        try:
            xml=send('hierarchy')['xml']
            break
        except RuntimeError as error:
            if 'No active accessibility window' not in str(error) or time.monotonic()>=deadline: raise
            time.sleep(.3)
    (OUT/(name+'.xml')).write_text(xml)
    return ET.fromstring(xml)


def find(root, text):
    for node in root.iter('node'):
        if node.get('text')!=text or node.get('visible')=='false' or node.get('enabled')=='false': continue
        b=list(map(int,re.findall(r'\d+',node.get('bounds',''))))
        if len(b)==4 and b[2]>b[0] and b[3]-b[1]>14: return node,b
    return None


def tap(text, name, scroll=False, duration=250):
    native_action = text in {'DEV','Pause to edit','Clear','Focus','Segment blocks','Room objects','All loaded','Undo','Redo','Reset group'} or text.startswith(('Block ', '+', '−'))
    for attempt in range(15):
        found=find(hierarchy(name+str(attempt)),text)
        if found:
            node,b=found
            actions.append({'control':text,'bounds':b,'checked_before':node.get('checked'),'duration_ms':duration})
            before=snapshot()['last_command']
            send('tap',x=(b[0]+b[2])/2,y=(b[1]+b[3])/2,duration_ms=duration)
            if native_action:
                # Button.performClick can be posted after ACTION_UP returns.
                # Input injection completion alone is not command completion.
                wait_for(lambda s:s['last_command']>before)
                command('snapshot')  # Drain any final cumulative hold move.
            else: time.sleep(.65)
            return
        if scroll:
            send('drag',x=820,y=430,to_x=820,to_y=240,duration_ms=450)
            time.sleep(.45)
        else: time.sleep(.4)
    raise AssertionError('Visible control not found: '+text)


def top():
    for _ in range(4): send('drag',x=825,y=240,to_x=825,to_y=440,duration_ms=300)
    time.sleep(.5)


def positions(s):
    return np.asarray([item['position'] for item in s['selection_group']['items']])


def unchanged_world(a,b):
    assert near(a['player_world'],b['player_world']) and near(a['camera_world'],b['camera_world'])
    assert near(a['camera_quaternion_xyzw'],b['camera_quaternion_xyzw'])
    assert a['updates']==b['updates']


def run():
    device=json.loads((BASE / 'device.json').read_text())
    report={**device,'start_utc':datetime.now(timezone.utc).isoformat(),
            'harness_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'checks':[],'input_helper':send('info'),'result':'RUNNING','hold_duration_ms':HOLD_MS}
    assert snapshot()['pid']==device['native_pid']
    save('report',report)

    def check(name,**fields):
        report['checks'].append({'name':name,'result':'PASS',**fields});save('report',report)
        print(name,'PASS',fields,flush=True)

    initial=hierarchy('00_before_reset')
    if any(n.get('text')=='Blocks in selected segment' for n in initial.iter('node')):
        tap('CLOSE','00_close_dialog')
    reset()
    # Ensure panel is open, then select via actual world touch, not the bridge.
    root=hierarchy('00_initial')
    if find(root,'DEV'): tap('DEV','00_open')
    elif find(root,'TOOLS'): tap('TOOLS','00_open')
    tap('Editor','01_editor')
    top()  # The Android panel retains its scroll position between test runs.
    for label, wanted in [('Multi-select',False), ('Move handles',True), ('Snap drag',False)]:
        found=find(hierarchy('01_'+label.replace(' ','_')),label)
        if found and (found[0].get('checked')=='true') != wanted:
            tap(label,'01_set_'+label.replace(' ','_'))
    command('clear_selection')
    time.sleep(.8)
    send('tap',x=540,y=380,duration_ms=250)
    one=save('02_world_pick',wait_for(lambda s:s['selection_group']['count']==1))
    assert one['selection']['editable']
    tap('Multi-select','03_multiselect')
    send('tap',x=430,y=400,duration_ms=250)
    two=save('04_two_picked',wait_for(lambda s:s['selection_group']['count']==2))
    assert two['selection_group']['editable_count']==2
    check('real_touch_single_and_multiple_selection',items=two['selection_group']['items'])

    top()
    before=snapshot(); n=before['selection_group']['undo_count']
    tap('+X','05_nudge')
    after=save('06_nudged',wait_for(lambda s:s['selection_group']['undo_count']==n+1))
    np.testing.assert_allclose(positions(after),positions(before)+[1,0,0],atol=1e-4)
    unchanged_world(before,after)
    tap('Undo','07_undo')
    restored=save('08_undone',wait_for(lambda s:s['selection_group']['redo_count']>0))
    np.testing.assert_allclose(positions(restored),positions(before),atol=1e-4)
    tap('Redo','09_redo')
    moved=wait_for(lambda s:s['selection_group']['redo_count']==0)
    np.testing.assert_allclose(positions(moved),positions(after),atol=1e-4)
    tap('Undo','10_undo_again')
    check('visible_move_undo_redo_controls',delta=[1,0,0])

    before=snapshot(); n=before['selection_group']['undo_count']
    tap('+Y','11_hold',duration=HOLD_MS)
    moved=save('12_held_move',wait_for(lambda s:s['selection_group']['undo_count']==n+1))
    time.sleep(.5); moved=snapshot()
    delta=positions(moved)[0]-positions(before)[0]
    assert delta[1]>=2,delta
    np.testing.assert_allclose(positions(moved),positions(before)+delta,atol=1e-4)
    unchanged_world(before,moved)
    tap('Undo','13_hold_undo')
    np.testing.assert_allclose(positions(snapshot()),positions(before),atol=1e-4)
    check('real_touch_hold_is_one_undo',delta=delta.tolist())

    # Native Focus projects world axes; drag the real visible X endpoint.
    tap('Focus','14_focus'); focused=snapshot()
    camera_label='CAM '+'  '.join('%.2f'%v for v in focused['camera_world'])
    for attempt in range(30):
        if any(camera_label in n.get('text','') for n in hierarchy('14_camera'+str(attempt)).iter('node')): break
        time.sleep(.3)
    else: raise AssertionError('Android panel did not display the focused camera pose')
    handle=next(h for h in focused['move_handles'] if h['axis']==0)
    x,y=handle['end'][0]*960,handle['end'][1]*540
    before=focused; n=before['selection_group']['undo_count']
    send('drag',x=x,y=y,to_x=x+46,to_y=y,duration_ms=800)
    command('snapshot')
    after=save('15_axis_drag',wait_for(lambda s:s['selection_group']['undo_count']==n+1))
    time.sleep(.5);after=snapshot()
    delta=positions(after)[0]-positions(before)[0]
    assert delta[0]>.1 and abs(delta[1])<1e-4 and abs(delta[2])<1e-4,delta
    np.testing.assert_allclose(positions(after),positions(before)+delta,atol=1e-4)
    unchanged_world(before,after)
    (OUT/'android-group-handles.png').write_bytes(adb('exec-out','screencap','-p',timeout=120))
    tap('Undo','16_drag_undo')
    np.testing.assert_allclose(positions(snapshot()),positions(before),atol=1e-4)
    check('real_axis_handle_drag_moves_world_not_camera',delta=delta.tolist())

    tap('Snap drag','17_snap')
    before=snapshot(); center=next(h for h in before['move_handles'] if h['axis']==-1)['end']; n=before['selection_group']['undo_count']
    send('drag',x=center[0]*960,y=center[1]*540,to_x=center[0]*960+40,to_y=center[1]*540-30,duration_ms=700)
    command('snapshot')
    after=wait_for(lambda s:s['selection_group']['undo_count']==n+1)
    time.sleep(.5);after=save('18_plane_drag',snapshot())
    delta=positions(after)[0]-positions(before)[0]
    assert delta[0]>0 and delta[1]>0
    np.testing.assert_allclose(delta,np.round(delta),atol=1e-4)
    np.testing.assert_allclose(positions(after),positions(before)+delta,atol=1e-4)
    unchanged_world(before,after)
    tap('Undo','19_plane_undo')
    check('center_handle_screen_plane_drag_and_snap',delta=delta.tolist())

    before=snapshot(); n=before['selection_group']['undo_count']
    send('key',code=22,duration_ms=100)  # DPAD_RIGHT, actual Activity key routing
    after=wait_for(lambda s:s['selection_group']['undo_count']==n+1)
    np.testing.assert_allclose(positions(after),positions(before)+[1,0,0],atol=1e-4)
    unchanged_world(before,after)
    tap('Undo','20_key_undo')
    check('keyboard_editor_nudge')

    # A loaded segment's source-box list is an actual picker with the current
    # block preselected; repeated polls must not create extra selection events.
    current=snapshot(); batch=next(b for b in current['current_room']['batches'] if b['path'].endswith('/start.mesh'))
    command('select',id=batch['id'],box=38);time.sleep(.8)
    tap('Multi-select','21_multi_off')
    tap('Choose a block in this segment…','22_choose_block',scroll=True)
    tap('Block 39 · XML 39','23_dialog_box')
    selected=wait_for(lambda s:s['selection']['box']==39)
    revision=selected['selection_group']['revision'];time.sleep(2)
    assert snapshot()['selection_group']['revision']==revision
    top();tap('Segment blocks','24_segment')
    segment=save('25_segment_selected',wait_for(lambda s:s['selection_group']['count']>100))
    assert segment['selection_group']['count']==182
    tap('Room objects','26_room');room=save('27_room_selected',snapshot())
    assert room['selection_group']['count']>=182
    tap('All loaded','28_all');all_loaded=save('29_all_selected',snapshot())
    assert all_loaded['selection_group']['count']>=room['selection_group']['count']
    n=all_loaded['selection_group']['undo_count']
    tap('+Z','30_bulk_move')
    moved=save('31_bulk_moved',wait_for(lambda s:s['selection_group']['undo_count']==n+1))
    np.testing.assert_allclose(positions(moved),positions(all_loaded)+[0,0,1],atol=1e-4)
    tap('Undo','32_bulk_undo')
    np.testing.assert_allclose(positions(snapshot()),positions(all_loaded),atol=1e-4)
    check('source_picker_segment_room_loaded_and_bulk_ui',segment=182,room=room['selection_group']['count'],all_loaded=all_loaded['selection_group']['count'])
    (OUT/'android-bulk-controls.png').write_bytes(adb('exec-out','screencap','-p',timeout=120))
    report.update(result='PASS',finish_utc=datetime.now(timezone.utc).isoformat(),actions=actions)
    save('report',report)
    reset()


if __name__=='__main__':
    try: run()
    except Exception as error:
        save('failure',{'error':repr(error),'actions':actions,'snapshot':snapshot()})
        raise
