#!/usr/bin/env python3
"""Exercise real Android Play/Edit controls against native world observations.

Native commands establish reproducible scenes and read evidence; the controls
under test receive real Android InputManager touch/key events.
"""
from pathlib import Path
import math
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.simple_play_support import (
    Evidence, UI, command, snapshot, send, fresh, ready, play_paused, wait_for, near,
)


def settle_ui():
    time.sleep(.8)
    return command('snapshot')


def held(before, after):
    assert before['updates']==after['updates']
    assert before['game_updates']==after['game_updates']
    assert near(before['player_world'],after['player_world'])


def positions(state):
    return {(i['id'],i['box']):i['position'] for i in state['selection_group']['items']}


def group_moved(before, after):
    a,b=positions(before),positions(after)
    assert a.keys()==b.keys()
    key=next(iter(a));delta=[b[key][i]-a[key][i] for i in range(3)]
    assert math.dist(delta,[0,0,0])>.01
    for key,p in a.items(): assert near(b[key],[p[i]+delta[i] for i in range(3)],eps=.003)
    held(before,after)
    assert near(before['camera_world'],after['camera_world'])
    assert after['selection_group']['undo_count']==before['selection_group']['undo_count']+1
    return delta


def assert_under_pointer(before, after, dx, dy):
    # These fixtures use the identity view. Reproject the actual picked triangle
    # point after the group translation, rather than assuming box-center depth.
    hit=after['selection_group']['last_ray_hit_world'];camera=before['camera_world']
    assert near(before['camera_rotation_degrees'],[0,0,0])
    delta=group_moved(before,after)
    depth=camera[2]-hit[2];t=math.tan(math.radians(before['fov_horizontal']/2))
    pixel_delta=[delta[0]/(depth*t)*480,-delta[1]/(depth*t)*480]
    assert abs(pixel_delta[0]-dx)<.03 and abs(pixel_delta[1]-dy)<.03,(pixel_delta,[dx,dy])
    return pixel_delta


def visible_box():
    # Pick actual visible retained triangles; do not assume a named source box
    # still has a baked face in this view.
    for x,y in [(480,270),(400,250),(560,250),(350,190),(610,190),(480,330)]:
        s=command('pick',x=x/960,y=y/540,aspect=960/540)
        o=s.get('selection') or {}
        if o.get('kind')=='box' and o.get('editable') and o.get('can_save'):
            return (x,y),s
    raise AssertionError('No visible editable source box in the fixture')


def slide(ui, label, fraction):
    for _ in range(14):
        root=ui.hierarchy('slider-'+label.replace(' ','-'))
        title=''
        for node in root.iter('node'):
            if node.get('class')=='android.widget.TextView': title=node.get('text','')
            if node.get('class')=='android.widget.SeekBar' and title.startswith(label+' · '):
                found=ui.find(node,cls='android.widget.SeekBar')
                if found:
                    b=found[1]
                    if b[1]>=145 and b[3]<=480:
                        x=b[0]+16+(b[2]-b[0]-32)*fraction;y=(b[1]+b[3])/2
                        send('tap',x=x,y=y,duration_ms=300)
                        return settle_ui()
        scroll=ui.find(root,cls='android.widget.ScrollView')
        assert scroll
        b=scroll[1]
        send('drag',x=(b[0]+b[2])/2,y=b[3]-25,to_x=(b[0]+b[2])/2,to_y=b[1]+50,duration_ms=400)
    raise AssertionError('Slider not reachable: '+label)


def run(e):
    ui=UI(e)
    fresh();command('forget_level_edits');fresh()
    command('control_settings',automatic=True,move_speed=6,travel_speed=1,look_speed=1,custom_fov=False,play_fog=True,edit_fog=False)
    play_paused('rails',position=(100,100,-40))
    ui.resume_drawer();command('freeze',value=False);ui.visible('Rails');settle_ui()
    ui.tap('Stop');before=wait_for(lambda s:s['play_controls']['stopped']);time.sleep(2)
    after=e.save('01-stop',snapshot());assert near(before['player_world'],after['player_world']) and after['updates']>before['updates']
    ui.tap('Move');wait_for(lambda s:not s['play_controls']['stopped']);before=snapshot()
    ui.tap('Look back');after=e.save('01-look-back',wait_for(lambda s:not s['play_controls']['turning'] and abs(abs(s['camera_rotation_degrees'][1])-180)<.01))
    assert after['player_world'][2]<before['player_world'][2] and near(after['camera_world'],after['player_world'])
    ui.tap('Reverse');before=wait_for(lambda s:s['play_controls']['backward']);time.sleep(2)
    after=e.save('01-reverse',snapshot());assert after['player_world'][2]>before['player_world'][2]
    ui.tap('Forward');wait_for(lambda s:not s['play_controls']['backward'])
    e.check('visible_stop_look_back_and_reverse_controls_change_real_travel')

    ui.tap('Rails');wait_for(lambda s:not s['play_controls']['rails']);ui.visible('Free move')
    command('look',rotation_degrees=[0,0,0]);command('teleport',target='player',position=[100,100,-80]);settle_ui()
    measurements=[]
    for name,operation,axis,sign in [
        ('stick-right',lambda:send('drag',x=126,y=427,to_x=126,to_y=427,duration_ms=1500),0,1),
        ('up',lambda:send('tap',x=179,y=390,duration_ms=1200),1,1),
        ('down',lambda:send('tap',x=179,y=449,duration_ms=1200),1,-1),
        # Span native frames even while the software emulator loads a batch.
        # A down/up pair drained in one frame intentionally causes no catch-up.
        ('keyboard-forward',lambda:send('key',code=51,duration_ms=2500),2,-1),
        ('keyboard-backward',lambda:send('key',code=47,duration_ms=2500),2,1),
    ]:
        before=snapshot();operation();after=e.save('02-'+name,settle_ui())
        assert (after['player_world'][axis]-before['player_world'][axis])*sign>.1,(name,before['player_world'],after['player_world'])
        assert near(after['camera_world'],after['player_world'])
        time.sleep(1);released=snapshot();assert near(after['player_world'],released['player_world'])
        measurements.append({'control':name,'before':before['player_world'],'after':after['player_world']})
    e.check('actual_stick_vertical_buttons_and_keyboard_move_player_and_release',measurements=measurements)

    before=snapshot();send('drag',x=500,y=250,to_x=570,to_y=220,duration_ms=700);after=e.save('03-look-drag',settle_ui())
    assert near(before['player_world'],after['player_world'])
    assert math.dist(before['camera_rotation_degrees'],after['camera_rotation_degrees'])>5
    e.check('world_drag_changes_view_without_moving_free_player')

    ui.tap('Speed');ui.visible('Game paused');before=wait_for(lambda s:s['play_controls']['tools_paused'])
    ui.to_top();pace=slide(ui,'Forward speed',.12);move=slide(ui,'Move / strafe speed',.28)
    look=slide(ui,'Look speed',.45);lens=slide(ui,'Field of view',.55)
    assert pace['play_controls']['travel_speed']!=1 and move['play_controls']['move_speed']!=6
    assert look['play_controls']['look_speed']!=1 and lens['play_controls']['custom_fov']
    assert 20<lens['fov_horizontal']<140;held(before,lens)
    ui.tap('Reset field of view',scroll=True);restored=settle_ui();assert not restored['play_controls']['custom_fov']
    ui.tap('Fog during play',scroll=True);wait_for(lambda s:not s['play_controls']['play_fog'])
    ui.tap('Fog while editing / in tools',scroll=True);fog=e.save('04-tools-fog',wait_for(lambda s:s['play_controls']['edit_fog'] and s['graphics']['last_fog_uniform']==0))
    held(before,fog)
    ui.tap('Resume game');ui.visible('Free move');fog=e.save('04-play-fog',wait_for(lambda s:s['play_controls']['active'] and s['graphics']['last_fog_uniform']==1))
    assert near(before['player_world'],fog['player_world'])
    e.check('real_speed_fov_and_independent_fog_controls_pause_and_resume',forward=pace['play_controls']['travel_speed'],move=move['play_controls']['move_speed'],look=look['play_controls']['look_speed'],fov=lens['fov_horizontal'])

    command('control_settings',move_speed=6,look_speed=1,travel_speed=1,play_fog=True,edit_fog=False,custom_fov=False)
    fresh();play_paused('free',position=(0,1,0));command('freeze',value=False);settle_ui()
    ui.tap('Edit');ui.visible('Move objects');before=wait_for(lambda s:s['play_controls']['editing']);command('teleport',target='camera',position=[0,1,0]);command('look',rotation_degrees=[0,0,0])
    point,picked=visible_box();original=picked['selection'];target={'id':original['id'],'box':original['box']}
    command('clear_selection');settle_ui();before=snapshot();n=before['selection_group']['undo_count']
    send('drag',x=point[0],y=point[1],to_x=point[0]+40,to_y=point[1]-25,duration_ms=900)
    wait_for(lambda s:s['selection_group']['undo_count']==n+1);after=e.save('05-direct-drag',settle_ui());edited=after['selection']
    assert edited['id']==target['id'] and edited['box']==target['box']
    assert math.dist(original['position'],edited['position'])>.1
    assert original['mesh_position_checksum']!=edited['mesh_position_checksum']
    assert original['collider_position_checksum']!=edited['collider_position_checksum']
    assert after['saved_edits']['unsaved']==1 and after['selection_group']['count']==1
    held(before,after);assert near(before['camera_world'],after['camera_world'])
    ui.tap('Undo');undone=settle_ui();assert undone['selection']['mesh_position_checksum']==original['mesh_position_checksum']
    ui.tap('Redo');redone=settle_ui();assert redone['selection']['mesh_position_checksum']==edited['mesh_position_checksum']
    e.check('one_finger_drag_selects_real_geometry_moves_mesh_and_collider_and_has_one_undo',box=target,from_position=original['position'],to_position=edited['position'])
    e.screen('android-direct-editor')

    before=snapshot();ui.tap('Save & resume');saved=e.save('06-save-and-resume',wait_for(lambda s:s['saved_edits']['saved']==1 and s['saved_edits']['unsaved']==0 and s['play_controls']['active']))
    ui.visible('Free move');assert near(before['player_world'],saved['player_world'])
    ui.tap('Tools');ui.tap('Replay this level with saved edits',scroll=True);ready();wait_for(lambda s:s['play_controls']['active']);ui.visible('Free move')
    ui.tap('Edit');wait_for(lambda s:s['play_controls']['editing']);s=ready()
    batch=next(b for b in s['current_room']['batches'] if b['path']==original['mesh'])
    reapplied=e.save('06-replayed-edited-box',command('select',id=batch['id'],box=original['box']))['selection']
    assert near(reapplied['position'],edited['position']) and reapplied['mesh_position_checksum']==edited['mesh_position_checksum']
    assert reapplied['collider_position_checksum']==edited['collider_position_checksum']
    e.check('save_resume_and_replay_buttons_reapply_actual_geometry_for_future_run',saved=1)

    # The actual scope button selects the current room. Drag any member to move
    # the whole selection once, without collapsing it to the clicked object.
    ui.tap('More');ui.tap('Whole room',scroll=True);s=settle_ui();assert s['selection_group']['count']>128
    ui.tap('Editor');ui.visible('Move objects');command('teleport',target='camera',position=[0,1,0]);command('look',rotation_degrees=[0,0,0]);settle_ui()
    # Preserve the group's membership while finding a visible member by ray.
    point=(400,250);before=e.save('07-room-before');count=before['selection_group']['count']
    send('drag',x=point[0],y=point[1],to_x=point[0]+30,to_y=point[1]-20,duration_ms=900)
    wait_for(lambda s:s['selection_group']['undo_count']>before['selection_group']['undo_count']);after=e.save('07-room-after',settle_ui())
    assert after['selection_group']['count']==count
    delta=group_moved(before,after)
    pointer_delta=assert_under_pointer(before,after,30,-20)
    ui.tap('Undo');restored=settle_ui();assert positions(restored).keys()==positions(before).keys()
    for key,p in positions(before).items(): assert near(positions(restored)[key],p)
    e.check('whole_room_touch_selection_and_drag_preserve_spacing_and_single_undo',objects=count,delta=delta,pointer_pixels=pointer_delta)

    ui.tap('More');ui.tap('Clear',scroll=True);ui.tap('Editor');settle_ui()
    before=snapshot();ui.tap('Move objects');ui.visible('Look around')
    send('drag',x=500,y=240,to_x=580,to_y=240,duration_ms=700);send('tap',x=179,y=390,duration_ms=1100)
    after=e.save('08-inspect-camera',settle_ui());held(before,after)
    assert math.dist(before['camera_world'],after['camera_world'])>.1 and math.dist(before['camera_rotation_degrees'],after['camera_rotation_degrees'])>5
    ui.tap('Look around');ui.visible('Move objects')
    e.check('clearly_labeled_look_mode_flies_detached_camera_while_editing_holds_world')

    # Leave a clean source fixture; cold-persistence testing uses its own pair.
    command('forget_level_edits');fresh();command('workspace',value='edit')
    e.finish()


if __name__=='__main__':
    evidence=Evidence('ui',__file__)
    try:run(evidence)
    except Exception as error:
        evidence.failure(error)
        raise
