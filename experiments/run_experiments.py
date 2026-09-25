#!/usr/bin/env python3
"""Controlled experiments against the actual modified APK in an Android runtime.

All inputs go through the in-game command queue. Snapshots retain the full
native inventory, and assertions compare independent observations of changes.
Run from the workspace root: python -u experiments/run_experiments.py PHASE
"""
from pathlib import Path
import hashlib
import json
import sys
import time
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.lab import command, snapshot, step, capture
from tools.android_input import send as android_input

OUT=ROOT/'experiments/controlled'
OUT.mkdir(exist_ok=True)

def save(name,s=None):
    s=snapshot() if s is None else s
    (OUT/(name+'.json')).write_text(json.dumps(s,indent=2)+'\n')
    r=s.get('current_room') or {};n=s.get('next_room') or {}
    print(name, json.dumps(dict(player=s.get('player_world'),camera=s.get('camera_world'),updates=s.get('updates'),room=r.get('index'),next=n.get('index'),bodies=s.get('bodies'),music=s.get('music_location'),error=s.get('error'))),flush=True)
    return s

def batch(*commands):return command('batch',commands=list(commands))

def settled(timeout=30):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        s=snapshot();rooms=[s.get('current_room'),s.get('next_room')]
        if all(b['loaded'] for r in rooms if r for b in r['batches']):return s
        time.sleep(.2)
    raise TimeoutError('Retained render batches did not finish loading')

def reset():
    s=snapshot()
    if not s.get('enabled'):command('enable',value=True)
    batch({'op':'freeze','value':True},{'op':'camera','value':True},{'op':'reload_level','from_start':True},{'op':'bounds','value':False},{'op':'no_fog','value':True},{'op':'noclip','value':True},{'op':'look','rotation_degrees':[0,0,0]})
    # Native level start constructs room geometry, but its first update enters
    # the room, starts its music and creates eligible obstacle instances.
    step(1)
    ready=settled();assert ready['current_room']['index']==0,'Controlled run did not begin at checkpoint zero';return ready

def inventory(s):
    return [(r['id'],r['index'],tuple((b['id'],b['loaded']) for b in r['batches']),tuple((o['index'],o['created_once'],o['live'],o['instance']) for o in r['obstacles']),r['static_shapes']) for r in [s.get('current_room'),s.get('next_room')] if r],s['entities'],s['bodies']

def unchanged(a,b):
    assert a['player_world']==b['player_world'],(a['player_world'],b['player_world'])
    assert a['updates']==b['updates']
    assert inventory(a)==inventory(b),'Native inventory changed'

def near(a,b,eps=1e-3):return len(a)==len(b) and all(abs(x-y)<eps for x,y in zip(a,b))

def tap(x,y):
    return android_input('tap',x=x,y=y,duration_ms=350)

def replace_numeric(x,y,value):
    """Real focused EditText/key input; every key carries a fresh event time."""
    tap(x,y);time.sleep(1)
    for code in [123]+[67]*12:  # End, then clear the short numeric field.
        android_input('key',code=code,duration_ms=1)
    codes={str(i):7+i for i in range(10)};codes.update({'.':56,'-':69})
    for char in value:
        android_input('key',code=codes[char],duration_ms=1)
    android_input('key',code=4,duration_ms=100)  # Dismiss the numeric IME.
    # Dispatch completion precedes the IME hide animation/window removal.
    # A subsequent field tap otherwise lands on the disappearing keyboard.
    time.sleep(1.5)

def wait_for(predicate,timeout=20):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        s=snapshot()
        if predicate(s):return s
        time.sleep(.25)
    raise TimeoutError('Runtime state did not satisfy the input check')

def phase_camera():
    base=save('D0_camera_baseline',reset())
    command('save_position',target='camera')
    s=save('D1_camera_forward',batch({'op':'teleport','target':'camera','position':[0,3,-100]},{'op':'look','rotation_degrees':[0,0,0]}));unchanged(base,s)
    s=save('E1_look_behind',command('look',rotation_degrees=[0,180,0]));unchanged(base,s);capture('experiment-E-look-behind.png')
    s=save('F1_outside',batch({'op':'teleport','target':'camera','position':[20,15,-60]},{'op':'look','rotation_degrees':[-30,90,0]}));unchanged(base,s);capture('experiment-F-outside.png')
    s=save('F2_above_looking_down',batch({'op':'teleport','target':'camera','position':[0,35,-60]},{'op':'look','rotation_degrees':[-90,0,0]}));unchanged(base,s);capture('experiment-F-above.png')
    s=save('F3_below_looking_up',batch({'op':'teleport','target':'camera','position':[0,-25,-60]},{'op':'look','rotation_degrees':[90,0,0]}));unchanged(base,s)
    s=save('D2_camera_restored',command('restore_position',target='camera'));unchanged(base,s);assert near(base['camera_world'],s['camera_world'])
    command('speed',value=10);command('move',value=[1,1,1]);time.sleep(2)
    s=save('F4_continuous_flight',command('move',value=[0,0,0]));unchanged(base,s)
    assert s['camera_world'][0]>base['camera_world'][0]+1 and s['camera_world'][1]>base['camera_world'][1]+1 and s['camera_world'][2]<base['camera_world'][2]-1
    command('restore_position',target='camera')

def phase_editor():
    base=reset();before=None
    for x,y in [(.5,.75),(.4,.72),(.56,.67),(.5,.6),(.3,.6)]:
        s=command('pick',x=x,y=y,aspect=16/9);selected=s.get('selection') or {}
        if selected.get('kind')=='box' and selected.get('editable'):before=save('H0_box_selected',s);break
    assert before,'Could not select an editable visible box'
    box=before['selection'];new_position=[.5,0,-10]
    after=save('H1_box_transformed',command('transform',position=new_position,rotation_degrees=[15,30,10],scale=[2,.5,2]))
    a=after['selection'];assert near(a['position'],new_position);assert near(a['rotation_degrees'],[15,30,10]);assert a['scale_factor']==[2,.5,2]
    assert a['mesh_position_checksum']!=box['mesh_position_checksum'];assert a['collider_position_checksum']!=box['collider_position_checksum']
    capture('experiment-H-box-transform.png')
    hit=save('H2_transformed_collider_raycast',command('raycast',start=[.5,4,-10],end=[.5,-4,-10]))
    assert hit['raycast']['hit'] and hit['raycast']['shape']==a['collider'],hit['raycast']
    command('export')
    restored=save('H3_box_reset',command('reset_object'))['selection'];assert restored['mesh_position_checksum']==box['mesh_position_checksum'];assert restored['collider_position_checksum']==box['collider_position_checksum']
    command('transform',position=new_position,rotation_degrees=[0,45,0],scale=[1,1,1])
    reloaded=save('H4_segment_reloaded',command('reload_section'))['selection'];assert reloaded['mesh_position_checksum']==box['mesh_position_checksum'];assert reloaded['collider_position_checksum']==box['collider_position_checksum']
    current=snapshot();body=next(o for o in current['objects'] if o['kind']=='body' and o.get('shapes',0)>0)
    bounds=body['bounds'];p=[(bounds['min'][i]+bounds['max'][i])/2 for i in range(3)]
    batch({'op':'teleport','target':'camera','position':[p[0],p[1],bounds['max'][2]+5]},{'op':'look','rotation_degrees':[0,0,0]})
    selected=save('H5_body_raycast_selection',command('pick',x=.5,y=.5,aspect=16/9))
    assert (selected.get('selection') or {}).get('kind')=='body','Visible body ray selection failed'
    b=selected['selection'];target=[b['position'][0]+1,b['position'][1]+1,b['position'][2]]
    after=save('H6_body_transformed',command('transform',position=target,rotation_degrees=[20,35,-15],scale=[1.5,.7,1.2]))
    assert near(after['selection']['position'],target);assert after['selection']['geometry_checksum']!=b['geometry_checksum']
    bounds=after['selection']['bounds'];center=[(bounds['min'][i]+bounds['max'][i])/2 for i in range(3)]
    batch({'op':'teleport','target':'camera','position':[center[0],center[1],bounds['max'][2]+5]},{'op':'look','rotation_degrees':[0,0,0]})
    capture('experiment-H-body-transform.png')
    hit=save('H7_body_collider_raycast',command('raycast',start=[center[0],center[1],bounds['max'][2]+4],end=[center[0],center[1],bounds['min'][2]-4]));assert hit['raycast']['hit'] and hit['raycast']['body']==after['selection']['native_address']
    restored=save('H8_body_reset',command('reset_object'));assert restored['selection']['geometry_checksum']==b['geometry_checksum'];assert near(restored['selection']['position'],b['position'])
    before=save('H9_level_before_rebuild',snapshot());after=save('H10_level_rebuilt',command('reload_level'));assert after['current_room']['id']!=before['current_room']['id'];assert after['current_room']['name']==before['current_room']['name']

def phase_teleport():
    base=save('B0_teleport_baseline',reset());p=base['player_world'];cam=base['camera_world']
    command('save_position',target='player')
    s=save('B1_forward_100_frozen',command('teleport',target='player',position=[0,1,p[2]-100]));assert inventory(base)==inventory(s)
    forward100=save('B2_forward_100_step',step());assert near(forward100['camera_world'],cam);assert near(forward100['player_world'],[0,1,p[2]-100]),'Player teleport was not held through native movement'
    backward100=save('C1_backward_100_frozen',command('restore_position',target='player'));assert near(backward100['player_world'],p);backward100=save('C2_backward_100_step',step())
    assert backward100['current_room']['id']==base['current_room']['id']
    old={d['index']:d for d in forward100['current_room']['obstacles'] if d['created_once'] and not d['live']}
    new={d['index']:d for d in backward100['current_room']['obstacles']};assert old,'Forward run did not expire any obstacle definitions';assert all(new[i]['created_once'] and not new[i]['live'] for i in old),'Expired obstacles were recreated'
    base=save('B3_large_jump_baseline',reset());cam=base['camera_world'];command('teleport',target='player',position=[0,1,-1000]);previous=base['current_room']['index']
    for i in range(16):
        s=save('B4_large_jump_step_%02d'%i,step());current=s['current_room']['index'];assert current-previous in [0,1],(current,previous);assert near(s['camera_world'],cam);previous=current
        if s['current_room']['path_distance']<=s['current_room']['length']:break
    else:raise AssertionError('Large jump did not catch up in 16 updates')
    assert len(s['unloaded_rooms'])>=2,'Intermediate rooms were not destroyed'
    far=s;old_ids={r['id'] for r in s['unloaded_rooms']};command('teleport',target='player',position=[0,1,0]);back=save('C3_return_to_unloaded_origin',step())
    assert back['current_room']['id']==far['current_room']['id'];assert back['current_room']['id'] not in old_ids
    capture('experiment-C-unloaded-origin.png')

def phase_music():
    base=save('G0_frozen_begin',reset());deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        time.sleep(3);s=snapshot();unchanged(base,s)
        if s['music_location']>28:break
    else:raise TimeoutError('Music did not reach its native preparation threshold')
    before=save('G1_frozen_music_over_28',s);assert before['next_room'] is None;assert before['current_room']['path_distance']<before['current_room']['length']-30
    after=save('G2_one_step_after_music_threshold',step());assert after['next_room'] is not None;assert after['current_room']['id']==before['current_room']['id'];assert after['current_room']['path_distance']<after['current_room']['length']-30
    save('G3_next_meshes_preloaded_while_frozen',settled())

def phase_normal():
    reset();batch({'op':'camera','value':False},{'op':'freeze','value':False});start=time.monotonic();samples=[]
    while time.monotonic()-start<45:
        samples.append(save('A_normal_%03d'%len(samples)));time.sleep(2)
    end=save('A_normal_end',command('freeze',value=True));assert end['player_world'][2]<samples[0]['player_world'][2]-5
    assert end['tutorial_checks_skipped']>samples[0]['tutorial_checks_skipped']
    assert end['updates']>samples[0]['updates'];capture('experiment-A-normal.png')
    base=reset();previous=0
    for i in range(1,11):
        command('teleport',target='player',position=[0,1,-50*i]);s=save('J_fast_progression_%02d'%i,step());assert s['current_room']['index']>=previous;previous=s['current_room']['index']

def phase_boundary():
    base=reset();length=base['current_room']['length']
    command('teleport',target='player',position=[0,1,-(length-31)]);before=save('K0_one_unit_before_prepare',step());assert before['next_room'] is None and before['music_location']<28
    command('teleport',target='player',position=[0,1,-(length-29)]);after=save('K1_one_unit_after_prepare',step());assert after['next_room'] is not None;assert after['current_room']['id']==base['current_room']['id']
    command('teleport',target='player',position=[0,1,-(length+1)]);changed=save('K2_one_unit_after_room_end',step());assert changed['current_room']['id']!=base['current_room']['id'];assert any(r['id']==base['current_room']['id'] for r in changed['unloaded_rooms'])

def phase_regression():
    base=reset();before=save('I0_before_disable',base);after=save('I1_normal_mode_restored',command('enable',value=False));assert not after['enabled'] and not after['free_camera']
    time.sleep(4);moving=save('I2_normal_mode_moving');assert moving['player_world'][2]<after['player_world'][2];assert near(moving['camera_world'],moving['player_world'],.5)
    balls=moving['player_balls'];tap(480,270)
    shot=save('I3_normal_touch_shot',wait_for(lambda s:s['player_balls']<balls))
    assert shot['player_balls']==balls-1,'Normal touch did not spend exactly one ball'
    capture('experiment-I-normal-gameplay.png')
    command('enable',value=True)
    layouts=[]
    for i in range(3):
        s=save('L_repeated_reload_%d'%i,reset());r=s['current_room'];layouts.append(([(b['path'],b['offset']) for b in r['batches']],[(o['name'],o['position_in_room']) for o in r['obstacles']]))
        assert r['name']=='basic/basic' and r['length']>0 and all(b['loaded'] for b in r['batches'])
    # Determinism is a measured question, not a required property of the game.
    # Earlier independent resets already showed native segment variation.
    hashes=[hashlib.sha256(json.dumps(layout,sort_keys=True).encode()).hexdigest() for layout in layouts]
    observed=dict(repetitions=len(layouts),identical_layouts=len(set(hashes))==1,
                  distinct_layouts=len(set(hashes)),layout_sha256=hashes,
                  note='Original generator and RNG remain unchanged; no fixed seed is imposed.')
    (OUT/'L_layout_comparison.json').write_text(json.dumps(observed,indent=2)+'\n');print('L_layout_comparison',json.dumps(observed),flush=True)

def phase_raw_pose():
    base=save('R0_raw_pose_baseline',reset())
    raw=save('R1_raw_position_write',command('teleport',target='player',position=[0,1,-100],raw=True));assert not raw['progression_held']
    after=save('R2_native_rail_restores_pose',step());assert after['player_world'][2]>-10,'Native path did not restore the raw pose in this starter-room state'
    assert after['current_room']['id']==base['current_room']['id'] and after['current_room']['created_once']==base['current_room']['created_once']

def phase_lateral():
    base=save('M0_player_lateral_baseline',reset())
    for i,p in enumerate(([100,1,0],[0,100,0],[0,-100,0])):
        command('teleport',target='player',position=p);s=save('M1_player_lateral_%d'%i,step())
        assert near(s['player_world'],p);assert s['current_room']['id']==base['current_room']['id'];assert s['next_room'] is None
        assert s['current_room']['created_once']==base['current_room']['created_once'];assert near(s['camera_world'],base['camera_world'])

def phase_idle():
    base=save('N0_stationary_player',reset());batch({'op':'progression_hold','value':True},{'op':'freeze','value':False});deadline=time.monotonic()+100
    while time.monotonic()<deadline:
        time.sleep(3);s=snapshot();assert near(s['player_world'],base['player_world']);assert s['current_room']['id']==base['current_room']['id']
        if s['next_room'] and all(b['loaded'] for b in s['next_room']['batches']):break
    else:raise TimeoutError('Stationary simulation did not prepare/preload its next room')
    end=save('N1_stationary_next_room_loaded',command('freeze',value=True));assert not end['unloaded_rooms'];assert end['updates']>base['updates']

def phase_noclip():
    base=reset();s=command('pick',x=.5,y=.75,aspect=16/9);assert s['selection']['editable'] and s['selection']['kind']=='box'
    wall=command('transform',position=[0,1,-5],rotation_degrees=[0,0,0],scale=[2,2,2])['selection']
    batch({'op':'teleport','target':'camera','position':[0,1,0]},{'op':'look','rotation_degrees':[0,0,0]},{'op':'speed','value':1},{'op':'noclip','value':False})
    command('move',value=[0,0,1]);time.sleep(3);blocked=save('O0_camera_collision_enabled',command('move',value=[0,0,0]));unchanged(base,blocked)
    assert blocked['camera_world'][2]>=wall['bounds']['max'][2]-.02,'Collision-enabled camera crossed the edited obstacle'
    command('noclip',value=True);command('move',value=[0,0,1]);time.sleep(3)
    passed=save('O1_noclip_passes_geometry',command('move',value=[0,0,0]));unchanged(base,passed);assert passed['camera_world'][2]<wall['bounds']['min'][2]-.2
    command('reset_object')

def phase_touch():
    reset();command('enable',value=False);time.sleep(1);tap(921,20)
    entered=save('P0_touch_enters_developer',wait_for(lambda s:s.get('enabled')))
    # Visible world tap, away from the panel and flight controls.
    selected=None
    # The rail advances briefly while the tools are closed. Use several visible
    # lower-world locations rather than assuming a former edge pixel still hits.
    for x,y in [(520,405),(480,425),(540,380)]:
        tap(x,y);time.sleep(.7);state=snapshot()
        if state.get('selection') is not None:selected=save('P1_touch_selects_geometry',state);break
    assert selected and selected['selection']['kind'] in ('box','body','segment_mesh'),'Touch did not select any tested visible surface'
    base=snapshot();android_input('tap',x=195,y=410,duration_ms=2000)
    moved=save('P2_touch_flies_up',wait_for(lambda s:s['camera_world'][1]>base['camera_world'][1]+.2));unchanged(base,moved)
    start=snapshot();android_input('drag',x=350,y=240,to_x=500,to_y=240,duration_ms=500)
    turned=save('P3_touch_drag_rotates',wait_for(lambda s:not near(s['camera_quaternion_xyzw'],start['camera_quaternion_xyzw'])));unchanged(start,turned)
    # Injected key events enter through Android's real input stack.
    before=snapshot();android_input('key',code=51,duration_ms=2000)
    moved=save('P4_keyboard_W_moves',wait_for(lambda s:not near(s['camera_world'],before['camera_world'],.2)));unchanged(before,moved)
    # Select the Streaming tab and capture its actual room/mesh inventory.
    tap(900,159);capture('experiment-P-streaming-ui.png')

def phase_ui_editor():
    reset();before=save('U0_ui_box_selected',command('pick',x=.5,y=.75,aspect=16/9))
    assert before['selection']['kind']=='box' and before['selection']['editable']
    # This phase targets the documented 960x540 Android view layout. Bring the
    # shared panel scroll to its beginning before focusing the position field.
    for _ in range(2):android_input('drag',x=930,y=230,to_x=930,to_y=480,duration_ms=600)
    capture('experiment-U-fields-before.png')
    replace_numeric(711,407,'1.500')
    assert snapshot()['selection']['position']==before['selection']['position'],'Typing changed native geometry before Apply'
    android_input('drag',x=920,y=466,to_x=920,to_y=250,duration_ms=700)
    replace_numeric(804,273,'30.000')
    replace_numeric(902,335,'2.000')
    capture('experiment-U-fields-entered.png')
    tap(806,375)
    after=save('U1_ui_apply_changes_native_world',wait_for(lambda s:near((s.get('selection') or {}).get('position',[]),[1.5,-3.5,-14.5]) and (s.get('selection') or {}).get('scale_factor')==[1,1,2]))
    selection=after['selection'];assert near(selection['rotation_degrees'],[0,30,0]);unchanged(before,after)
    assert selection['mesh_position_checksum']!=before['selection']['mesh_position_checksum']
    assert selection['collider_position_checksum']!=before['selection']['collider_position_checksum']
    capture('experiment-U-ui-transform.png')
    tap(873,413)
    restored=save('U2_ui_reset_restores_geometry',wait_for(lambda s:(s.get('selection') or {}).get('mesh_position_checksum')==before['selection']['mesh_position_checksum']))
    assert restored['selection']['collider_position_checksum']==before['selection']['collider_position_checksum']

def phase_camera_streaming():
    reset();base=save('Q0_camera_with_live_streaming_baseline',command('progression_hold',value=True))
    poses=[([0,1,-1000],[0,0,0]),([0,1,1000],[0,180,0]),
           ([100,1,0],[0,90,0]),([0,100,0],[-90,0,0]),
           ([0,-100,0],[90,0,0]),([0,1,0],[0,180,0])]
    for i,(position,rotation) in enumerate(poses):
        batch({'op':'teleport','target':'camera','position':position},{'op':'look','rotation_degrees':rotation})
        s=save('Q1_camera_streaming_step_%d'%i,step())
        assert s['updates']==base['updates']+i+1,'The streaming update did not run'
        assert near(s['player_world'],base['player_world']) and near(s['camera_world'],position)
        assert s['music_location']<28,'Music would confound this short camera isolation run'
        assert inventory(s)==inventory(base),'Camera affected the native inventory during a real update'

def phase_editor_rebased():
    reset();command('teleport',target='player',position=[0,1,-200]);step();settled()
    base=command('teleport',target='camera',position=[0,1,-200]);assert base['world_origin_z']!=0 and base['current_room']['index']==1
    before=None
    for x,y in [(.52,.75),(.35,.7),(.7,.7),(.3,.5),(.7,.5),(.5,.85)]:
        s=command('pick',x=x,y=y,aspect=16/9)
        if (s.get('selection') or {}).get('kind')=='box' and s['selection'].get('editable'):
            before=save('V0_rebased_box_selected',s);break
    assert before,'No mapped box selected in the streamed room'
    after=save('V1_rebased_box_moved_outside_corridor',command('transform',position=[50,50,-205],rotation_degrees=[0,20,0],scale=[1.1,.9,1.2]))
    box=after['selection'];assert near(box['position'],[50,50,-205]);assert box['mesh_position_checksum']!=before['selection']['mesh_position_checksum']
    bounds=box['bounds'];center=[(bounds['min'][i]+bounds['max'][i])/2 for i in range(3)]
    hit=save('V2_rebased_native_collider_hit',command('raycast',start=[center[0],bounds['max'][1]+2,center[2]],end=[center[0],bounds['min'][1]-2,center[2]]))
    assert hit['raycast']['hit'] and hit['raycast']['shape']==box['collider']
    restored=save('V3_rebased_edit_reset',command('reset_object'))['selection']
    assert restored['mesh_position_checksum']==before['selection']['mesh_position_checksum']
    assert restored['collider_position_checksum']==before['selection']['collider_position_checksum']
    assert near(restored['position'],before['selection']['position'])

PHASES={'camera':phase_camera,'editor':phase_editor,'teleport':phase_teleport,'music':phase_music,'normal':phase_normal,'boundary':phase_boundary,'regression':phase_regression,'raw_pose':phase_raw_pose,'lateral':phase_lateral,'idle':phase_idle,'noclip':phase_noclip,'touch':phase_touch,'ui_editor':phase_ui_editor,'camera_streaming':phase_camera_streaming,'editor_rebased':phase_editor_rebased}
if __name__=='__main__':
    phase=sys.argv[1]
    device=json.loads((ROOT/'experiments/device.json').read_text())
    meta={'phase':phase,'start_utc':datetime.now(timezone.utc).isoformat(),'apk_sha256':device['apk_sha256'],'native_pid':device['native_pid'],'harness_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    versions=ROOT/'experiments/harnesses';versions.mkdir(exist_ok=True)
    (versions/(meta['harness_sha256']+'.py')).write_bytes(Path(__file__).read_bytes())
    try:
        initial=snapshot();meta['native_start_time']=initial.get('time');meta['native_start_frame']=initial.get('frame')
        assert initial.get('pid')==device['native_pid'],'Run prepare_device.py to verify this runtime before experiments'
        if initial.get('enabled'):command('marker',name='experiment_begin_'+phase)
        PHASES[phase]();meta['result']='PASS'
    except Exception as e:
        meta['result']='FAIL';meta['error']=str(e);save('failure_'+phase);raise
    finally:
        final=snapshot();meta['native_end_time']=final.get('time');meta['native_end_frame']=final.get('frame')
        if final.get('enabled'):command('marker',name='experiment_end_'+phase+'_'+meta['result'])
        meta['end_utc']=datetime.now(timezone.utc).isoformat();(OUT/('result_'+phase+'.json')).write_text(json.dumps(meta,indent=2)+'\n');print(json.dumps(meta),flush=True)
