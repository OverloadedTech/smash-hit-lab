#!/usr/bin/env python3
"""Actual menu/transition exploration controls and original-play regression."""
from pathlib import Path
import math
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from experiments.simple_play_support import Evidence,UI,command,snapshot,send,fresh,play_paused,wait_for,near


def run(e):
    ui=UI(e)
    if ui.find(ui.hierarchy('initial-window'),'World details'):ui.tap('Close')
    fresh();command('forget_level_edits');fresh()
    command('control_settings',automatic=True,move_speed=6,look_speed=1,travel_speed=1,custom_fov=False,play_fog=True,edit_fog=False)
    play_paused('free',position=(0,1,0));ui.resume_drawer();command('freeze',value=False);ui.visible('Free move')
    ui.tap('Tools');ui.tap('Position, rooms & research details',scroll=True)
    ui.visible('World details')
    root=ui.hierarchy('world-details')
    assert any(n.get('text','').startswith('Current: ') and 'meshes loaded' in n.get('text','') for n in root.iter('node'))
    ui.tap('Capture transition to menu',scroll=True)
    before=e.save('01-return-captured',wait_for(lambda s:s['play_controls']['exploring'] and s['context']=='transition',timeout=90))
    assert .35<before['menu_transition']<.7 and before['frozen']
    ui.visible('Resume');send('drag',x=500,y=245,to_x=580,to_y=220,duration_ms=800)
    send('tap',x=179,y=390,duration_ms=1700);time.sleep(.8)
    after=e.save('01-return-explored',command('snapshot'))
    assert after['game_updates']==before['game_updates'] and after['updates']==before['updates']
    assert abs(after['menu_transition']-before['menu_transition'])<1e-6
    assert math.dist(after['camera_world'],before['camera_world'])>.2
    assert math.dist(after['camera_rotation_degrees'],before['camera_rotation_degrees'])>5
    ui.tap('Resume');after=e.save('01-return-resumed',wait_for(lambda s:s['context']=='menu' and not s['enabled'],timeout=90))
    assert after['menu_transition']>.999
    assert near(after['native_camera_world'],after['camera_world'])
    e.check('actual_transition_capture_freezes_native_rotation_and_resume_finishes_original_animation',captured_amount=before['menu_transition'])

    ui.tap('Tools');ui.tap('Explore menu');before=wait_for(lambda s:s['play_controls']['exploring']);ui.visible('Resume')
    send('drag',x=500,y=245,to_x=560,to_y=245,duration_ms=700)
    send('tap',x=179,y=390,duration_ms=1700);time.sleep(.8)
    after=e.save('02-menu-outside',command('snapshot'))
    assert after['game_updates']==before['game_updates'] and not after['playing']
    assert after['camera_world'][1]>before['camera_world'][1]+.2
    assert not near(after['camera_world'],after['native_camera_world'])
    e.screen('android-menu-free-camera')
    e.check('homepage_explore_button_flies_outside_native_menu_view_without_running_scene')

    ui.tap('Tools');ui.tap('Position, rooms & research details',scroll=True)
    ui.visible('World details')
    ui.tap('Capture transition into game',scroll=True)
    before=e.save('03-intro-captured',wait_for(lambda s:s['play_controls']['exploring'] and s['context']=='transition',timeout=90))
    assert .3<before['menu_transition']<.65 and before['frozen']
    ui.visible('Resume');ui.tap('Resume')
    after=e.save('03-intro-completed',wait_for(lambda s:s['context']=='game' and s['play_controls']['active'],timeout=120))
    assert after['menu_transition']<=.001 and near(after['player_world'],after['camera_world'])
    e.check('resume_captured_intro_finishes_original_camera_then_attaches_play_controls',captured_amount=before['menu_transition'])

    ui.tap('Tools');old=e.save('04-before-restart',snapshot())
    ui.tap('Original game controls · new run',scroll=True);ui.visible('Start new run');ui.tap('Start new run')
    before=e.save('04-original-start',wait_for(lambda s:s['playing'] and s['context']=='game' and not s['enabled'] and not s['play_controls']['active'] and s['current_room']['id']!=old['current_room']['id'],timeout=120))
    assert before['current_room']['index']==0 and before['current_room']['name']=='basic/basic'
    assert not before['play_controls']['automatic'] and not before['projectiles']['enabled']
    inventory=before['player_balls'];shots=[]
    for attempt in range(3):
        send('tap',x=770,y=125,duration_ms=800);time.sleep(.8);s=snapshot()
        shots.append({k:s[k] for k in ['frame','updates','player_balls','active_tutorial_id','native_paused','balls_in_world']})
        if s['player_balls']<inventory:break
    after=e.save('04-original-shot',snapshot());e.save('04-original-taps',shots)
    assert after['player_balls']<inventory,shots
    assert not after['enabled'] and not after['projectiles']['enabled']
    assert after['updates']>before['updates'] and after['player_world'][2]<before['player_world'][2]
    e.check('original_controls_restart_keeps_native_camera_input_inventory_and_progression',before_balls=inventory,after_balls=after['player_balls'],old_room=old['current_room']['id'],new_room=before['current_room']['id'])
    command('enable',value=True);command('control_settings',automatic=True)
    fresh();command('workspace',value='edit');e.finish()


if __name__=='__main__':
    evidence=Evidence('contexts',__file__)
    try:run(evidence)
    except Exception as error:evidence.failure(error);raise
