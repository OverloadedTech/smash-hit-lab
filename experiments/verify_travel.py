#!/usr/bin/env python3
"""Exercise real native projection, view/travel separation and campaign resets.

No geometry is invented. Fixtures approach existing obstacle definitions and
every jump uses the live native RoomDef list. Run after prepare_device.py.
"""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import math
import os
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.lab import command, snapshot, step, forward
from tools.android_input import send
from experiments.phase2_controls import reset, wait_for, near

BASE = ROOT / os.environ.get('SHLAB_TRAVEL_EVIDENCE', 'experiments/travel_tools')
OUT = BASE / 'native'
OUT.mkdir(parents=True, exist_ok=True)


def save(name, data):
    (OUT / (name + '.json')).write_text(json.dumps(data, indent=2) + '\n')
    return data


def ready():
    state = wait_for(lambda s: not s['navigation']['loading'], timeout=240)
    assert not state['navigation']['error'], state['navigation']['error']
    assert all(b['loaded'] for b in state['current_room']['batches'])
    return state


def fresh():
    command('enable', value=True)
    command('fov_original')
    command('unlock_levels', value=False)
    if snapshot()['playing']:
        command('travel', enabled=False)
    state = reset()
    command('travel_speed', value=1)
    return ready()


def paused_steps(count):
    before = snapshot()
    assert before['frozen'] and not before['navigation']['loading']
    step(count, timeout=240)
    after = ready()
    assert after['updates'] - before['updates'] == count, (before['updates'], after['updates'], count)
    assert after['frozen'] and after['steps_remaining'] == 0
    return after


def fail(op, **fields):
    try:
        command(op, **fields)
    except RuntimeError as error:
        return str(error)
    raise AssertionError(op + ' unexpectedly succeeded')


def run():
    forward()
    device = json.loads((BASE / 'device.json').read_text())
    assert snapshot()['pid'] == device['native_pid']
    assert snapshot()['navigation_api_version'] == 1
    assert hashlib.sha256((ROOT / 'artifacts/smash-hit-lab.apk').read_bytes()).hexdigest() == device['apk_sha256']
    report = {**device, 'start_utc': datetime.now(timezone.utc).isoformat(),
              'harness_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'checks': [], 'result': 'RUNNING'}
    save('report', report)

    def check(name, **fields):
        assert snapshot()['pid'] == device['native_pid']
        report['checks'].append({'name': name, 'result': 'PASS', **fields})
        save('report', report)
        print(name, 'PASS', fields, flush=True)

    base = save('00_initial', fresh())
    projection = []
    for value in [20, 80, 110, 140]:
        before = snapshot()
        command('fov', value=value)
        state = save('01_fov_' + str(value), wait_for(lambda s: s['navigation']['last_draw_frame'] > before['frame']))
        nav = state['navigation']
        assert abs(nav['last_draw_fov'] - value) < .001
        expected = 1 / math.tan(math.radians(value) / 2)
        assert abs(nav['last_draw_projection_x'] - expected) < .0001
        assert abs(nav['last_draw_projection_y'] - expected * state['aspect']) < .0002
        assert state['updates'] == base['updates']
        assert near(state['player_world'], base['player_world']) and near(state['camera_world'], base['camera_world'])
        projection.append({'horizontal_fov': value, 'projection_x': nav['last_draw_projection_x'], 'projection_y': nav['last_draw_projection_y']})
    restored = command('fov_original')
    assert not restored['navigation']['fov_override']
    assert abs(restored['fov_horizontal'] - restored['original_fov_horizontal']) < .001
    check('native_projection_and_restore', projections=projection)

    command('mode', value='ride')
    command('look', rotation_degrees=[0, 180, 0])
    before = snapshot()
    wait_for(lambda s: s['updates'] >= before['updates'] + 12)
    state = save('02_watch_back_forward_motion', command('freeze', value=True))
    assert state['player_world'][2] < before['player_world'][2]
    assert near(state['player_world'], state['camera_world'])
    assert abs(abs(state['camera_rotation_degrees'][1]) - 180) < .001
    assert not state['navigation']['travel_enabled']
    check('watch_back_while_original_player_moves_forward', before=before['player_world'], after=state['player_world'])

    command('look', rotation_degrees=[25, 90, 0])
    command('speed', value=2)
    before = snapshot()
    command('move', value=[1, 1, 0])
    wait_for(lambda s: s['camera_world'][1] > before['camera_world'][1] + 1)
    state = save('03_view_offset', command('move', value=[0, 0, 0]))
    assert near(before['player_world'], state['player_world']) and state['updates'] == before['updates']
    assert not near(before['camera_world'], state['camera_world'])
    assert state['current_room']['id'] == before['current_room']['id']
    assert near(state['camera_world'], [a+b for a,b in zip(state['player_world'], state['navigation']['view_offset'])])
    check('independent_view_rotation_and_offset', offset=state['navigation']['view_offset'])

    fresh()
    command('teleport', target='player', position=[30, 20, -25])
    command('travel', direction=1)
    paces = []
    for multiplier in [.25, 1, 4]:
        command('travel_speed', value=multiplier)
        before = snapshot()
        after = save('04_speed_' + str(multiplier), paused_steps(6))
        elapsed = after['navigation']['travel_seconds'] - before['navigation']['travel_seconds']
        distance = after['player_world'][2] - before['player_world'][2]
        expected = -before['current_room']['length'] / 32 * multiplier * elapsed
        assert abs(distance - expected) < .0002, (distance, expected)
        assert after['navigation']['travel_updates'] - before['navigation']['travel_updates'] == 6
        paces.append({'multiplier': multiplier, 'native_dt_total': elapsed, 'world_delta_z': distance, 'expected_delta_z': expected})
    command('travel', direction=0)
    before = snapshot(); after = save('05_hold', paused_steps(6))
    assert near(before['player_world'], after['player_world'])
    assert after['navigation']['velocity_world_z'] == 0
    check('speed_uses_actual_dt_and_hold_keeps_world_ticking', paces=paces, held_updates=6)

    before = snapshot()
    command('travel', direction=-1)
    after = save('06_reverse_motion', paused_steps(6))
    assert after['player_world'][2] > before['player_world'][2]
    assert after['current_room']['id'] == before['current_room']['id']
    check('actual_player_reverses_with_forward_simulation', before=before['player_world'], after=after['player_world'])

    # Approach an authored object, let native forward cleanup remove it, then
    # turn around. Verify actual instance identities, not just created flags.
    state = fresh()
    original = state['current_room']['obstacles'][0]
    index = original['index']
    z = original['position_in_room'][2]
    command('teleport', target='player', position=[30, 20, z+5])
    live = save('07_obstacle_forward_live', paused_steps(1))['current_room']['obstacles'][index]
    assert live['live']
    command('teleport', target='player', position=[30, 20, z-12])
    expired = save('08_obstacle_forward_expired', paused_steps(2))['current_room']['obstacles'][index]
    assert expired['created_once'] and not expired['live']
    before = snapshot()
    command('travel', direction=-1)
    state = save('09_obstacle_reverse_recreated', paused_steps(1))
    recreated = state['current_room']['obstacles'][index]
    assert recreated['live'] and recreated['instance'] != live['instance']
    assert state['navigation']['restored_obstacle_definitions'] > before['navigation']['restored_obstacle_definitions']
    held = save('10_reverse_instance_retained', paused_steps(3))['current_room']['obstacles'][index]
    assert held['live'] and held['instance'] == recreated['instance']
    command('travel', direction=0)
    stopped = save('10_reverse_hold_retains_instance', paused_steps(2))
    assert stopped['current_room']['obstacles'][index]['instance'] == recreated['instance']
    assert stopped['navigation']['obstacle_cleanup_direction'] == -1
    command('travel', direction=-1)
    command('teleport', target='player', position=[30, 20, z+8])
    passed = save('11_reverse_instance_expired', paused_steps(2))['current_room']['obstacles'][index]
    assert not passed['live']
    check('reverse_recreates_passed_owned_obstacles_and_reverses_expiry', name_in_game=original['name'], original_id=live['instance'], recreated_id=recreated['instance'])
    command('travel', direction=0)
    command('travel', direction=1)
    returned = save('11_turn_forward_recreates_instance', paused_steps(2))
    again = returned['current_room']['obstacles'][index]
    assert again['live'] and again['instance'] != recreated['instance']
    assert returned['navigation']['obstacle_cleanup_direction'] == 1
    check('turning_forward_again_recreates_reverse_expired_objects', returned_instance=again['instance'])

    fresh()
    before = snapshot()
    original_records = [l['recorded_balls'] for l in before['navigation']['levels']]
    unlocked = save('12_unlock', command('unlock_levels', value=True))
    assert len(unlocked['navigation']['levels']) == 13
    assert all(l['available'] for l in unlocked['navigation']['levels'])
    assert [l['recorded_balls'] for l in unlocked['navigation']['levels']] == original_records
    locked = command('unlock_levels', value=False)
    assert [l['available'] for l in locked['navigation']['levels']] == [l['available'] for l in before['navigation']['levels']]
    assert [l['recorded_balls'] for l in locked['navigation']['levels']] == original_records
    check('unlock_is_reversible_without_filling_checkpoint_records', recorded_balls=original_records)

    before = snapshot()
    errors = [fail('jump_level', index=-1), fail('jump_level', index=13),
              fail('jump_room', index=100000), fail('travel_speed', value=0),
              fail('travel_speed', value=101), fail('travel', direction=2), fail('fov', value='invalid')]
    after = snapshot()
    assert after['current_room']['id'] == before['current_room']['id']
    assert near(after['player_world'], before['player_world'])
    for key in ['room_rebuilds', 'speed_multiplier', 'direction', 'unlocked', 'fov_override']:
        assert after['navigation'][key] == before['navigation'][key], key
    command('snapshot')
    check('invalid_navigation_requests_do_not_mutate_world', errors=errors)

    command('unlock_levels', value=True)
    jumps = []
    for level in snapshot()['navigation']['levels']:
        index = level['index']
        definitions = snapshot()['navigation']['rooms']
        expected = next(r for r in definitions if r['checkpoint'] == index)
        queued = command('jump_level', index=index)
        state = save('13_checkpoint_' + str(index), ready())
        assert state['navigation']['current_checkpoint'] == index
        assert state['current_room']['index'] == expected['index']
        assert state['current_room']['name'] == expected['name']
        assert state['current_room']['static_shapes'] > 0 and state['current_room']['batches']
        assert near(state['player_world'], [0, 1, 0]) and not state['world_running']
        jumps.append({'checkpoint': index, 'name': level['name'], 'room': expected['name'],
                      'room_index': expected['index'], 'batches': len(state['current_room']['batches']),
                      'static_shapes': state['current_room']['static_shapes'], 'queued_loading': queued['navigation']['loading']})
        print('checkpoint_ready', jumps[-1], flush=True)
    check('all_13_checkpoints_build_their_actual_native_room', jumps=jumps)

    definitions = snapshot()['navigation']['rooms']
    continuations = [r for r in definitions if r['source_level_entry'] >= 13]
    assert continuations and all(r['checkpoint'] == 12 and r['available'] for r in continuations)
    target = continuations[-1]
    command('jump_room', index=target['index'])
    state = save('13_endless_continuation', ready())
    assert state['current_room']['index'] == target['index']
    assert state['navigation']['current_checkpoint'] == 12
    check('endless_continuations_remain_reachable_under_checkpoint_12', native_index=target['index'],
          source_level_entry=target['source_level_entry'], room=target['name'])

    definitions = snapshot()['navigation']['rooms']
    target = next(r['index'] for r in definitions if r['name'] == 'night/part2')
    command('jump_room', index=target)
    before = ready()
    # Make a real history entry; it must not retain destroyed room pointers.
    editable = next(o for o in before['objects'] if o.get('kind') == 'segment_mesh' and o.get('editable_boxes', 0))
    selection = command('select', id=editable['id'])['selection']
    ordinal = next(b['box'] for b in selection['box_choices'] if b['editable'])
    command('select', id=editable['id'], box=ordinal)
    command('move_selection', delta=[.1, 0, 0])
    assert snapshot()['selection_group']['undo_count'] > 0
    seam = before['current_room']['world_z_bounds'][1]
    command('teleport', target='player', position=[30, 20, seam+1])
    command('travel', direction=-1)
    before = snapshot()
    after = save('14_reverse_boundary_three_steps', paused_steps(3))
    assert after['current_room']['index'] == target-1
    assert after['navigation']['room_rebuilds'] == before['navigation']['room_rebuilds']+1
    assert abs(after['current_room']['world_z_bounds'][0]-seam) < .001
    assert abs(after['player_world'][2] - before['player_world'][2] -
               (after['navigation']['travel_delta_world_z']-before['navigation']['travel_delta_world_z'])) < .001
    assert after['selection_group']['count'] == 0 and after['selection_group']['undo_count'] == 0
    check('reverse_boundary_preserves_seam_pending_steps_and_editor_lifetimes', from_index=target,
          to_index=after['current_room']['index'], actual_level_updates=after['updates']-before['updates'], seam_world_z=seam)

    command('travel', enabled=False)
    command('jump_level', index=0)
    ready()
    command('teleport', target='player', position=[30, 20, 1])
    command('travel', direction=-1)
    state = save('15_campaign_start', paused_steps(2))
    assert state['current_room']['index'] == 0 and state['navigation']['direction'] == 0
    assert abs(state['player_world'][2]) < .001
    check('reverse_stops_at_campaign_start')

    # Selected-level reverse starts at the last real RoomDef and runs, while
    # a plain jump remains paused. This also tests asynchronous buffer setup.
    expected = [r for r in state['navigation']['rooms'] if r['checkpoint'] == 1][-1]
    command('reverse_level', index=1)
    state = ready()
    before = snapshot()
    wait_for(lambda s: s['updates'] >= before['updates']+3)
    state = save('16_reverse_selected_level_running', command('freeze', value=True))
    assert state['current_room']['index'] == expected['index']
    assert state['navigation']['direction'] == -1 and state['navigation']['follow_player_view']
    assert state['player_world'][2] > before['player_world'][2]
    assert abs(abs(state['camera_rotation_degrees'][1])-180) < .001
    check('reverse_selected_level_starts_at_its_end_and_runs', room=state['current_room']['name'])

    # Native normal-play input must use the same lens as the draw, and leaving
    # every option off must still produce a paid-for native projectile.
    shots = []
    for lens in [60, 110]:
        fresh()
        command('teleport', target='player', position=[30, 20, -10])
        command('fov', value=lens)
        command('mode', value='play')
        time.sleep(2)
        before = snapshot()
        balls = before['player_balls']; known = {b['id'] for b in before['balls_in_world']}
        send('tap', x=650, y=270, duration_ms=250)
        shot = wait_for(lambda s: s['player_balls'] < balls)
        shot = save('17_normal_shot_fov_' + str(lens), shot)
        new = next(b for b in shot['balls_in_world'] if b['id'] not in known)
        assert not shot['enabled'] and shot['player_balls'] == balls-1
        assert shot['navigation']['last_input_fov'] == lens
        assert shot['navigation']['last_draw_fov'] == lens
        assert new['velocity'][0] > 0 and new['velocity'][2] < 0
        shots.append({'fov': lens, 'projectile': new, 'ratio_x_over_negative_z': new['velocity'][0] / -new['velocity'][2]})
    # X/Z is unaffected by gravity; allow the native throwing origin/camera
    # effect while requiring the independently predicted wider angular aim.
    measured = shots[1]['ratio_x_over_negative_z'] / shots[0]['ratio_x_over_negative_z']
    expected = math.tan(math.radians(110)/2)/math.tan(math.radians(60)/2)
    assert abs(measured/expected - 1) < .08, (measured, expected)
    check('normal_play_input_and_projectile_aim_match_fov', shots=shots, measured_ratio=measured, geometric_ratio=expected)
    fresh()
    report.update(result='PASS', finish_utc=datetime.now(timezone.utc).isoformat())
    save('report', report)


if __name__ == '__main__':
    try:
        run()
    except Exception as error:
        save('failure', {'error': repr(error), 'snapshot': snapshot()})
        raise
