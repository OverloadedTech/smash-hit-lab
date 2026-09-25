#!/usr/bin/env python3
"""Verify actual player motion, original projectiles, saved geometry and pauses.

Use the prepared laboratory emulator. This rebuilds runs and replaces its Lab
edit sidecars after preserving copies in the evidence directory.
"""
from pathlib import Path
import math
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.simple_play_support import (
    Evidence, UI, command, snapshot, adb, PACKAGE, send, fresh, ready,
    play_paused, steps, wait_for, near,
)


def selected(target):
    return command('select', **target)['selection']


def starter(state):
    return next(b for b in state['current_room']['batches'] if b['path'].endswith('/start.mesh'))


def collision(record):
    bounds = record['bounds']
    center = [(a+b)/2 for a,b in zip(bounds['min'], bounds['max'])]
    start = [center[0], bounds['max'][1]+2, center[2]]
    end = [center[0], bounds['min'][1]-2, center[2]]
    result = command('raycast', start=start, end=end)['raycast']
    assert result['hit'], result
    assert (result['shape'] == record['collider'] if record['kind']=='box'
            else result['body'] == record['native_address']), result
    return result


def run(e):
    ui = UI(e)
    ui.hierarchy('initial-window')
    for name in ['controls.json', 'level-edits.json']:
        try: (e.out/('before-'+name)).write_bytes(adb('exec-out','run-as',PACKAGE,'cat','files/shdev/'+name))
        except Exception: pass
    fresh()
    command('control_settings', automatic=True, move_speed=6, travel_speed=1, look_speed=1,
            play_fog=True, edit_fog=False, use_saved_edits=True, custom_fov=False)
    command('forget_level_edits')
    fresh()

    paces = []
    play_paused('rails', rotation=(0,180,0))
    for multiplier in [.25,1,4]:
        command('control_settings', travel_speed=multiplier)
        before = snapshot(); after = e.save('01-pace-'+str(multiplier), steps(6))
        dt = after['navigation']['travel_seconds']-before['navigation']['travel_seconds']
        delta = after['player_world'][2]-before['player_world'][2]
        expected = -before['current_room']['length']/32*multiplier*dt
        assert abs(delta-expected)<.0005, (delta,expected)
        assert near(after['player_world'], after['camera_world'])
        assert abs(abs(after['camera_rotation_degrees'][1])-180)<.001
        paces.append({'speed':multiplier,'native_seconds':dt,'delta_z':delta,'expected_z':expected})
    e.check('rail_speed_uses_native_dt_while_view_looks_backward', paces=paces)

    command('play_stop',value=True)
    before=snapshot();after=e.save('02-stopped',steps(6))
    assert near(before['player_world'],after['player_world'])
    assert after['game_updates']>before['game_updates']
    e.check('stop_holds_player_without_stopping_simulation', updates=6)

    command('control_settings',travel_speed=1)
    play_paused('free')
    directions = [([1,0,0],[1,0,0]),([-1,0,0],[-1,0,0]),([0,1,0],[0,1,0]),
                  ([0,-1,0],[0,-1,0]),([0,0,1],[0,0,-1]),([0,0,-1],[0,0,1])]
    measured=[]
    for i,(input_axes,world_axes) in enumerate(directions):
        command('play_move',value=input_axes)
        before=snapshot();after=e.save('03-free-axis-'+str(i),steps(3))
        dt=after['play_controls']['movement_seconds']-before['play_controls']['movement_seconds']
        expected=[before['player_world'][j]+world_axes[j]*6*dt for j in range(3)]
        assert near(after['player_world'],expected), (after['player_world'],expected)
        assert near(after['player_world'],after['camera_world'])
        assert after['play_controls']['movement_updates']-before['play_controls']['movement_updates']==3
        measured.append({'input':input_axes,'native_seconds':dt,'position':after['player_world']})
    command('look',rotation_degrees=[0,180,0]);command('play_move',value=[0,0,1])
    before=snapshot();after=e.save('03-free-facing-backward',steps(3))
    assert after['player_world'][2]>before['player_world'][2]
    command('play_move',value=[0,0,0])
    e.check('six_axis_movement_moves_real_player_and_follows_view', axes=measured)

    speeds=[]
    for value in [3,12]:
        play_paused('free');command('control_settings',move_speed=value)
        command('play_move',value=[1,1,1]);before=snapshot();after=steps(4)
        dt=after['play_controls']['movement_seconds']-before['play_controls']['movement_seconds']
        expected=[before['player_world'][j]+[1,1,-1][j]*value*dt/math.sqrt(3) for j in range(3)]
        assert near(after['player_world'],expected), (after['player_world'],expected)
        speeds.append({'speed':value,'native_seconds':dt,'delta':[b-a for a,b in zip(before['player_world'],after['player_world'])]})
    command('play_move',value=[0,0,0]);command('control_settings',move_speed=6)
    e.check('move_speed_and_normalized_diagonal_motion', measurements=speeds)

    play_paused('rails',rotation=(12,180,0))
    before=e.save('04-edit-open',command('workspace',value='edit'))
    command('teleport',target='camera',position=[-50,45,-10]);command('look',rotation_degrees=[-30,40,0])
    start=time.monotonic();time.sleep(20)
    held=e.save('04-edit-held')
    assert held['updates']==before['updates'] and held['game_updates']==before['game_updates']
    assert near(before['player_world'],held['player_world'])
    resumed=e.save('04-resume-before-update',command('batch',commands=[{'op':'workspace','value':'resume'},{'op':'freeze','value':True}]))
    assert near(before['player_world'],resumed['player_world'])
    assert near(before['camera_rotation_degrees'],resumed['camera_rotation_degrees'])
    after=e.save('04-resume-six-updates',steps(6))
    dt=after['navigation']['travel_seconds']-resumed['navigation']['travel_seconds']
    delta=after['player_world'][2]-resumed['player_world'][2]
    assert abs(delta+before['current_room']['length']/32*dt)<.0005
    e.check('editing_holds_world_and_resume_has_no_music_catchup', held_wall_seconds=time.monotonic()-start,
            resumed_native_seconds=dt,resumed_delta_z=delta)

    # A native box supplies the wall for both obstruction and noclip tests.
    fresh();target={'id':starter(snapshot())['id'],'box':38};box=selected(target)
    wall=command('transform',position=[100,100,-30],rotation_degrees=[0,0,0],scale=[1,1,1])['selection']
    collision(wall)
    play_paused('free',position=(97,100,-30));command('control_settings',move_speed=10)
    command('noclip',value=False);command('play_move',value=[1,0,0])
    stopped=e.save('05-wall-stops-motion',steps(6))
    assert 97<stopped['player_world'][0]<wall['bounds']['min'][0]
    command('teleport',target='player',position=[97,100,-30]);command('noclip',value=True)
    before=snapshot();through=e.save('05-noclip-through-wall',steps(6))
    dt=through['play_controls']['movement_seconds']-before['play_controls']['movement_seconds']
    assert near(through['player_world'],[97+10*dt,100,-30])
    assert through['player_world'][0]>wall['bounds']['max'][0]
    command('play_move',value=[0,0,0]);command('control_settings',move_speed=6)
    e.check('noclip_crosses_a_real_collider_and_collision_mode_stops', collision_x=stopped['player_world'][0],noclip_x=through['player_world'][0])

    # Crossing a reconstructed seam must not charge two movement updates.
    command('workspace',value='edit');command('unlock_levels',value=True);command('jump_room',index=4);ready()
    play_paused('free',position=(30,20,0));command('play_move',value=[0,0,-1])
    before=snapshot();after=e.save('06-free-reverse-boundary',steps(3))
    assert after['current_room']['index']==3
    assert after['play_controls']['movement_updates']-before['play_controls']['movement_updates']==3
    dt=after['play_controls']['movement_seconds']-before['play_controls']['movement_seconds']
    assert abs(after['player_world'][2]-before['player_world'][2]-6*dt)<.003
    assert after['navigation']['follow_player_view'] and near(after['player_world'],after['camera_world'])
    command('play_move',value=[0,0,0])
    e.check('free_move_crosses_reverse_room_seam_once_per_update', from_room=4,to_room=3,native_seconds=dt)

    fresh();play_paused('free',position=(100,100,-80));command('play_stop',value=True)
    ui.resume_drawer()
    command('play_mode',value='free');command('play_stop',value=True);command('freeze',value=False)
    ui.visible('Free move');time.sleep(.6)
    turns=[]
    for speed in [.5,2]:
        command('control_settings',look_speed=speed);command('look',rotation_degrees=[0,0,0])
        before=snapshot();command('play_face',yaw=180)
        after=e.save('07-turn-'+str(speed),wait_for(lambda s:not s['play_controls']['turning'],timeout=45))
        elapsed=after['play_controls']['turn_seconds']-before['play_controls']['turn_seconds']
        assert 1/speed-.02<=elapsed<=1/speed+.31,elapsed
        assert near(before['player_world'],after['player_world'])
        turns.append({'look_speed':speed,'turn_seconds':elapsed})
    command('control_settings',look_speed=1)
    e.check('look_back_turn_speed_is_configurable_and_does_not_move_player', turns=turns)

    shots=[]
    for heading,fov,pixel in [(180,60,480),(0,60,650),(0,110,650)]:
        command('teleport',target='player',position=[100,100,-80]);command('look',rotation_degrees=[0,heading,0]);command('control_settings',fov=fov)
        command('freeze',value=False);ui.visible('Free move');time.sleep(.6)
        before=snapshot();send('tap',x=pixel,y=270,duration_ms=60)
        shot=wait_for(lambda s:s['play_controls']['shot_spawns']>before['play_controls']['shot_spawns'],timeout=30)
        frozen=e.save('08-shot-'+str(heading)+'-'+str(fov),command('freeze',value=True))
        assert frozen['player_balls']==before['player_balls']-1
        birth=frozen['play_controls']['last_shot'];ball=next(b for b in frozen['balls_in_world'] if b['id']==birth['id'])
        offset=[b-a for a,b in zip(birth['player_world'],birth['position'])]
        assert near(offset,[0,-.1,.5 if heading==180 else -.5])
        assert ball['velocity'][2]>10 if heading==180 else ball['velocity'][2]<-10
        if heading==180:
            after=e.save('08-backward-shot-flight',steps(6));later=next(b for b in after['balls_in_world'] if b['id']==birth['id'])
            assert later['active'] and later['position'][2]>ball['position'][2]+5
            assert after['projectiles']['physics_culls_avoided']>0 and after['projectiles']['entity_culls_avoided']>0
            assert after['projectiles']['bounds_pending_restore']==0
        shots.append({'heading':heading,'fov':fov,'id':birth['id'],'spawn_offset':offset,'velocity':ball['velocity']})
        command('teleport',target='player',position=[300,100,-80]);retired=e.save('08-retired-'+str(fov),steps(1))
        assert not any(b['id']==birth['id'] for b in retired['balls_in_world'])
    ratio=abs(shots[2]['velocity'][0]/shots[2]['velocity'][2])/abs(shots[1]['velocity'][0]/shots[1]['velocity'][2])
    expected=math.tan(math.radians(55))/math.tan(math.radians(30))
    assert abs(ratio-expected)<.001,(ratio,expected)
    e.check('short_taps_original_inventory_backward_flight_fov_and_bounded_retirement',shots=shots,angle_ratio=ratio,expected_ratio=expected)

    command('teleport',target='player',position=[100,-20,-80]);command('look',rotation_degrees=[0,180,0]);command('freeze',value=False)
    time.sleep(.6);before=snapshot();send('tap',x=905,y=460,duration_ms=60)
    shot=wait_for(lambda s:s['play_controls']['shot_spawns']>before['play_controls']['shot_spawns'],timeout=30)
    command('freeze',value=True);after=e.save('09-below-world-shot',steps(3));ball=next(b for b in after['balls_in_world'] if b['id']==shot['play_controls']['last_shot']['id'])
    assert ball['active'] and ball['position'][1]<-10 and after['projectiles']['bounds_pending_restore']==0
    e.check('fire_control_works_below_original_world_cutoff',projectile=ball)

    # Independent fog states are read back from the actual bound GLSL program.
    fog=[]
    for context in ['edit','play']:
        command('batch',commands=[{'op':'workspace','value':context},{'op':'freeze','value':True}])
        for value in [True,False]:
            before=snapshot()['frame'];command('control_settings',**{context+'_fog':value})
            state=e.save('10-fog-'+context+'-'+str(value),wait_for(lambda s:s['graphics']['last_fog_frame']>before))
            assert state['graphics']['last_fog_uniform']==(0 if value else 1)
            fog.append({'context':context,'fog':value,'uniform':state['graphics']['last_fog_uniform']})
    command('control_settings',play_fog=True,edit_fog=False)
    e.check('separate_play_edit_fog_settings_reach_original_shaders',states=fog)

    # Reject invalid settings without changing their persisted sidecar.
    original=adb('exec-out','run-as',PACKAGE,'cat','files/shdev/controls.json')
    before=snapshot()['play_controls'];errors=[]
    for fields in [{'move_speed':0},{'fov':141},{'move_speed':7,'play_fog':3}]:
        try:command('control_settings',**fields)
        except RuntimeError as error:errors.append(str(error))
        else:raise AssertionError('Invalid setting accepted')
        assert adb('exec-out','run-as',PACKAGE,'cat','files/shdev/controls.json')==original
        assert snapshot()['play_controls']['move_speed']==before['move_speed']
    command('snapshot')
    e.check('invalid_settings_are_rejected_without_partial_save',errors=errors)

    command('workspace',value='edit');command('forget_level_edits');s=fresh()
    target={'id':starter(s)['id'],'box':38};original_box=selected(target)
    edited_box=e.save('11-box-edited',command('transform',position=[12.5,4.5,-15.5],rotation_degrees=[10,25,0],scale=[1.2,.8,1.1]))['selection']
    assert edited_box['can_save'];collision(edited_box)
    obstacle=s['current_room']['obstacles'][0]
    command('teleport',target='player',position=[30,20,obstacle['position_in_room'][2]+5]);s=steps(1)
    body=next(o for o in s['objects'] if o['kind']=='body' and o['name']=='scoretop' and o.get('editable'))
    original_body=selected({'id':body['id']});assert original_body['can_save']
    # Put the native body clear of the room roof before probing its collider.
    # A ray through the original room can legitimately hit another shape first.
    wanted=[original_body['position'][0]+30,original_body['position'][1]+20,original_body['position'][2]]
    edited_body=e.save('11-body-edited',command('transform',position=wanted,rotation_degrees=[0,20,0],scale=[1.1,.9,1.2]))['selection']
    collision(edited_body)
    saved=e.save('11-saved',command('save_level_edits'));assert saved['saved_edits']['saved']==2 and saved['saved_edits']['unsaved']==0
    (e.out/'saved-two-objects.json').write_bytes(adb('exec-out','run-as',PACKAGE,'cat','files/shdev/level-edits.json'))
    s=fresh();new_box=selected({'id':starter(s)['id'],'box':38})
    assert near(new_box['position'],edited_box['position']) and near(new_box['rotation_degrees'],edited_box['rotation_degrees'])
    assert new_box['mesh_position_checksum']==edited_box['mesh_position_checksum']
    assert new_box['collider_position_checksum']==edited_box['collider_position_checksum'];collision(new_box)
    obstacle=s['current_room']['obstacles'][0];command('teleport',target='player',position=[30,20,obstacle['position_in_room'][2]+5]);s=steps(1)
    body=next(o for o in s['objects'] if o['kind']=='body' and near(o['position'],edited_body['position']))
    new_body=e.save('11-body-rebuilt',command('select',id=body['id']))['selection']
    assert new_body['id']!=edited_body['id'] and new_body['geometry_checksum']==edited_body['geometry_checksum']
    assert near(new_body['rotation_degrees'],edited_body['rotation_degrees']) and near(new_body['scale_factor'],edited_body['scale_factor'])
    collision(new_body)
    e.check('saved_box_and_authored_body_restore_mesh_transform_and_collider_on_new_run',saved_objects=2,old_body_id=edited_body['id'],new_body_id=new_body['id'])

    command('control_settings',use_saved_edits=False);s=fresh();unchanged=selected({'id':starter(s)['id'],'box':38})
    assert near(unchanged['position'],original_box['position']) and unchanged['mesh_position_checksum']==original_box['mesh_position_checksum']
    assert snapshot()['saved_edits']['saved']==2
    command('control_settings',use_saved_edits=True);s=fresh();target={'id':starter(s)['id'],'box':38};selected(target)
    command('reset_selection');command('save_level_edits');assert snapshot()['saved_edits']['saved']==1
    command('edit_undo');command('save_level_edits');assert snapshot()['saved_edits']['saved']==2
    s=fresh();again=selected({'id':starter(s)['id'],'box':38});assert again['mesh_position_checksum']==edited_box['mesh_position_checksum']
    e.check('saved_edits_can_be_disabled_and_individually_reset_or_undone')

    command('forget_level_edits');s=fresh();target={'id':starter(s)['id'],'box':38};original_box=selected(target)
    group=command('select_all',scope='segment',kind='boxes');count=group['selection_group']['count'];assert count>128
    moved=command('move_selection',delta=[.25,.5,-.75]);expected=selected(target)
    command('save_level_edits');assert snapshot()['saved_edits']['saved']==count
    s=fresh();actual=e.save('12-bulk-rebuilt',command('select',id=starter(s)['id'],box=38))['selection']
    assert near(actual['position'],expected['position']) and actual['mesh_position_checksum']==expected['mesh_position_checksum']
    assert actual['collider_position_checksum']==expected['collider_position_checksum'];collision(actual)
    assert snapshot()['saved_edits']['skipped']==0
    command('forget_level_edits');s=fresh();restored=selected({'id':starter(s)['id'],'box':38})
    assert restored['mesh_position_checksum']==original_box['mesh_position_checksum']
    e.check('bulk_save_reapplies_source_boxes_and_clear_restores_original_run',saved_boxes=count)

    command('control_settings',play_fog=True,edit_fog=False,move_speed=6,travel_speed=1,look_speed=1,custom_fov=False)
    command('workspace',value='edit')
    e.finish()


if __name__=='__main__':
    evidence=Evidence('native',__file__)
    try:run(evidence)
    except Exception as error:
        evidence.failure(error)
        raise
