#!/usr/bin/env python3
"""Exercise real Android bulk mesh/collider edits, guards and object lifetimes."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.lab import command, snapshot, step, forward
from tools.android_input import send
from experiments.phase2_controls import reset, settled, near, wait_for

BASE = ROOT / os.environ.get('SHLAB_EDITOR_EVIDENCE', 'experiments/editor_improvements')
OUT = BASE / 'native'
OUT.mkdir(parents=True, exist_ok=True)


def save(name, data):
    (OUT / (name + '.json')).write_text(json.dumps(data, indent=2) + '\n')
    return data


def info(target):
    return command('select', **target)['selection']


def choose(targets):
    return command('batch', commands=[{'op': 'select', **t, 'additive': i != 0} for i, t in enumerate(targets)])


def checksums(record):
    return {k: v for k, v in record.items() if k.endswith('checksum')}


def fail(operation, expected, **kwargs):
    try:
        command(operation, **kwargs)
    except RuntimeError as error:
        assert expected in str(error), str(error)
        return str(error)
    raise AssertionError(operation + ' unexpectedly succeeded')


def run():
    forward()
    device = json.loads((BASE / 'device.json').read_text())
    assert snapshot()['pid'] == device['native_pid']
    assert snapshot()['editor_api_version'] == 2
    report = {**device, 'start_utc': datetime.now(timezone.utc).isoformat(),
              'harness_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'checks': [], 'result': 'RUNNING'}
    save('report', report)

    def check(name, **data):
        report['checks'].append({'name': name, 'result': 'PASS', **data})
        save('report', report)
        print(name, 'PASS', data, flush=True)

    s = reset()
    # A reset does not guarantee that a scripted body is present yet. Approach
    # an observed authored obstacle and advance the original loader again;
    # never manufacture a body for the test.
    if not any(o['kind'] == 'body' and o.get('editable') and o.get('shapes', 0) for o in s['objects']):
        obstacle = s['current_room']['obstacles'][0]
        z = s['current_room']['world_z_bounds'][1] + obstacle['position_in_room'][2] + 10
        command('teleport', target='player', position=[0, 1, z])
        s = step(1)
        report['fixture_approach'] = {'obstacle': obstacle['name'], 'world_z': z}
    s = save('00_baseline', s)
    start = next(b for b in s['current_room']['batches'] if b['path'].endswith('/start.mesh'))
    a, b = {'id': start['id'], 'box': 38}, {'id': start['id'], 'box': 39}
    body = next(o for o in s['objects'] if o['kind'] == 'body' and o.get('editable') and o.get('shapes', 0))
    c = {'id': body['id']}
    targets = [a, b, c]
    original = [info(t) for t in targets]
    assert all(r['editable'] for r in original)
    info(a)
    tilted = command('transform', position=original[0]['position'], rotation_degrees=[0, 60, 0], scale=[1.5, .75, 2])['selection']
    assert tilted['mesh_position_checksum'] != original[0]['mesh_position_checksum']
    baseline = [info(t) for t in targets]
    chosen = choose(targets)
    revision = chosen['selection_group']['revision']
    n = chosen['selection_group']['undo_count']
    delta = [30, 20, -2]
    moved = save('01_mixed_group_moved', command('move_selection', delta=delta, revision=revision))
    assert moved['selection_group']['count'] == 3 and moved['selection_group']['undo_count'] == n + 1
    assert near(moved['player_world'], s['player_world']) and near(moved['camera_world'], s['camera_world'])
    assert moved['updates'] == s['updates']
    after = [info(t) for t in targets]
    for before, actual in zip(baseline, after):
        assert near(actual['position'], [x+y for x,y in zip(before['position'], delta)])
        assert near(actual['rotation_degrees'], before['rotation_degrees'])
        assert actual['scale_factor'] == before['scale_factor']
    assert after[0]['mesh_position_checksum'] != baseline[0]['mesh_position_checksum']
    assert after[0]['collider_position_checksum'] != baseline[0]['collider_position_checksum']
    box = after[0]; bounds = box['bounds']; center = [(bounds['min'][i]+bounds['max'][i])/2 for i in range(3)]
    hit = save('02_moved_box_collider_hit', command('raycast', start=[center[0], bounds['max'][1]+2, center[2]], end=[center[0], bounds['min'][1]-2, center[2]]))
    assert hit['raycast']['hit'] and hit['raycast']['shape'] == box['collider'], hit['raycast']
    item = after[2]; bounds = item['bounds']; center = [(bounds['min'][i]+bounds['max'][i])/2 for i in range(3)]
    hit = save('03_moved_body_collider_hit', command('raycast', start=[center[0], center[1], bounds['max'][2]+2], end=[center[0], center[1], bounds['min'][2]-2]))
    assert hit['raycast']['hit'] and hit['raycast']['body'] == item['native_address'], hit['raycast']
    undone = save('04_mixed_group_undo', command('edit_undo'))
    assert undone['selection_group']['count'] == 3
    for target, before in zip(targets, baseline):
        restored = info(target)
        assert near(restored['position'], before['position']) and checksums(restored) == checksums(before)
    redone = save('05_mixed_group_redo', command('edit_redo'))
    assert redone['selection_group']['count'] == 3
    for target, expected in zip(targets, after): assert checksums(info(target)) == checksums(expected)
    check('mixed_blocks_and_script_body_move_meshes_colliders_and_undo', count=3, body=body['name'], delta=delta)

    chosen = choose(targets); n = chosen['selection_group']['undo_count']; revision = chosen['selection_group']['revision']
    for distance in [1, 2, 3]:
        held = command('move_selection', delta=[distance, 0, 0], revision=revision, gesture='verified-native-hold')
        assert held['selection_group']['undo_count'] == n+1
    for target, before in zip(targets, after):
        assert near(info(target)['position'], [before['position'][0]+3, *before['position'][1:]])
    command('edit_undo')
    for target, before in zip(targets, after): assert checksums(info(target)) == checksums(before)
    check('cumulative_gesture_has_one_undo', samples=3, delta=[3, 0, 0])

    chosen = choose(targets)
    reset_state = save('06_reset_group', command('reset_selection'))
    for target, before in zip(targets, original):
        actual = info(target)
        assert near(actual['position'], before['position']) and checksums(actual) == checksums(before)
    command('edit_undo')
    for target, before in zip(targets, after): assert checksums(info(target)) == checksums(before)
    check('group_reset_and_undo_restore_real_geometry')

    chosen = choose([a, b]); n = chosen['selection_group']['undo_count']; revision = chosen['selection_group']['revision']
    guard_before = [info(t) for t in [a,b]]
    choose([a,b]); revision = snapshot()['selection_group']['revision']
    errors = [fail('move_selection', 'Selection changed', delta=[1,0,0], revision=revision-1)]
    errors.append(fail('move_selection', 'coordinate range', delta=[1e9,0,0]))
    unchanged = command('move_selection', delta=[0,0,0])
    assert unchanged['selection_group']['undo_count'] == n
    errors.append(fail('apply_box_edits', 'process changed', id=a['id'], expected_pid=-1, edits=[]))
    errors.append(fail('apply_box_edits', 'inspect-only', id=a['id'], edits=[
        {'box': 38, 'position': [40,40,-10], 'rotation_degrees': [0,0,0], 'scale': [1,1,1]},
        {'box': 999999, 'position': [0,0,0], 'rotation_degrees': [0,0,0], 'scale': [1,1,1]},
    ]))
    for target, before in zip([a,b], guard_before): assert checksums(info(target)) == checksums(before)
    choose([a,b]); inspect_box = next(x['box'] for x in snapshot()['selection']['box_choices'] if not x['editable'])
    command('select', id=a['id'], box=inspect_box, additive=True)
    errors.append(fail('move_selection', 'inspect-only', delta=[1,0,0]))
    for target, before in zip([a,b], guard_before): assert checksums(info(target)) == checksums(before)
    choose([a,b]); command('freeze', value=False)
    errors.append(fail('move_selection', 'Pause the world', delta=[1,0,0]))
    command('freeze', value=True)
    for target, before in zip([a,b], guard_before): assert checksums(info(target)) == checksums(before)
    check('atomic_preflight_pause_revision_pid_and_inspect_only_guards', rejected=errors)

    # Reset the room before broad edits so source comparisons are byte-exact.
    s = reset(); start = next(b for b in s['current_room']['batches'] if b['path'].endswith('/start.mesh'))
    a = {'id': start['id'], 'box': 38}; baseline_box = info(a)
    segment = command('select_all', scope='segment', kind='boxes')
    assert segment['selection_group']['count'] == sum(x['editable'] for x in baseline_box['box_choices'])
    assert all(i['kind'] == 'box' and i['id'] == a['id'] and i['editable'] for i in segment['selection_group']['items'])
    segment_count = segment['selection_group']['count']
    room = command('select_all', scope='room'); room_count = room['selection_group']['count']
    assert room_count >= segment_count and room['selection_group']['editable_count'] == room_count
    all_loaded = command('select_all', scope='loaded')
    assert all_loaded['selection_group']['count'] >= room_count
    count = all_loaded['selection_group']['count']; n = all_loaded['selection_group']['undo_count']
    assert count > 128 and all_loaded['selection_group']['editable_count'] == count
    start_time = time.monotonic()
    moved = save('07_all_loaded_moved', command('move_selection', delta=[.25,.5,-.75]))
    elapsed = time.monotonic()-start_time
    assert moved['selection_group']['undo_count'] == n+1
    for left,right in zip(all_loaded['selection_group']['items'], moved['selection_group']['items']):
        assert near(right['position'], [left['position'][0]+.25, left['position'][1]+.5, left['position'][2]-.75])
    command('edit_undo')
    assert checksums(info(a)) == checksums(baseline_box)
    check('segment_room_all_loaded_bulk_scopes', segment=segment_count, room=room_count, all_loaded=count, command_seconds=elapsed)

    # Source-local bulk apply is native API v2 and does not temporarily reset a
    # reference box. Check its coordinate conversion after an origin rebase.
    command('teleport', target='player', position=[0,1,-55]); step(1); settled()
    rebased = snapshot(); assert rebased['world_origin_z'] != 0
    before = [info({'id':a['id'],'box':ordinal}) for ordinal in [38,39]]
    mapping = json.loads((ROOT/'dev/assets/shdev/geometry/basic/basic/start.json').read_text())
    edits = []
    for ordinal in [38,39]:
        position = mapping['boxes'][ordinal]['position']
        edits.append({'box':ordinal, 'position':[position[0]+12,position[1]+9,position[2]-1],
                      'rotation_degrees':[0,25,0], 'scale':[1.2,.8,1.1]})
    applied = save('08_rebased_bulk_source_apply', command('apply_box_edits', id=a['id'], expected_pid=device['native_pid'], edits=edits))
    assert applied['selection_group']['count'] == 2
    for ordinal, base in zip([38,39], before):
        actual = info({'id':a['id'],'box':ordinal})
        assert near(actual['position'], [base['position'][0]+12,base['position'][1]+9,base['position'][2]-1])
    command('edit_undo')
    for ordinal, base in zip([38,39], before):
        actual=info({'id':a['id'],'box':ordinal})
        assert checksums(actual)==checksums(base) and near(actual['position'],base['position'])
    check('bulk_source_apply_after_origin_rebase', origin_z=rebased['world_origin_z'])

    # Undo records must never retain pointers after reload/unload.
    s = reset(); start = next(b for b in s['current_room']['batches'] if b['path'].endswith('/start.mesh'))
    a = {'id': start['id'], 'box':38}; before = info(a)
    changed = command('move_selection', delta=[1,0,0]); revision = changed['selection_group']['revision']
    reloaded = save('09_section_reload_invalidates_history', command('reload_section'))
    assert reloaded['selection_group']['undo_count'] == 0 and reloaded['selection_group']['revision'] != revision
    assert checksums(reloaded['selection']) == checksums(before)
    command('move_selection', delta=[1,0,0])
    length = snapshot()['current_room']['length']
    command('teleport', target='player', position=[0,1,-(length-29)]); step(1); settled()
    command('teleport', target='player', position=[0,1,-(length+1)]); after = save('10_unloaded_selection', step(1))
    assert after['current_room']['id'] != s['current_room']['id']
    assert after['selection_group']['count'] == 0 and after['selection_group']['undo_count'] == 0
    fail('edit_undo','Nothing to undo')
    check('reload_and_unload_invalidate_selection_history')

    # Original input still spends a ball and creates a native projectile.
    reset(); command('teleport', target='player', position=[30,20,-10]); command('mode', value='play')
    time.sleep(2.5); base = snapshot(); balls = base['player_balls']; known = {b['id'] for b in base['balls_in_world']}
    send('tap', x=520, y=400, duration_ms=250)
    shot = save('11_normal_gameplay_shot', wait_for(lambda s:s['player_balls']<balls))
    assert not shot['enabled'] and shot['player_balls'] == balls-1
    assert any(b['id'] not in known for b in shot['balls_in_world'])
    check('normal_gameplay_still_shoots', balls_before=balls, balls_after=shot['player_balls'])
    reset()
    report.update(result='PASS', finish_utc=datetime.now(timezone.utc).isoformat())
    save('report', report)


if __name__ == '__main__':
    try: run()
    except Exception as error:
        save('failure', {'error':repr(error), 'snapshot':snapshot()})
        raise
