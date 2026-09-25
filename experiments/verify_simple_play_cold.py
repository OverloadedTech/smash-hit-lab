#!/usr/bin/env python3
"""Kill the process and verify persisted preferences and real edited geometry."""
from pathlib import Path
import json
import re
import sys
import time
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from experiments.simple_play_support import Evidence,BASE,command,snapshot,fast_request,adb,PACKAGE,send,fresh,steps,near
from experiments.verify_simple_play import collision,starter,selected


def run(e):
    fresh();command('forget_level_edits');s=fresh()
    old_pid=s['pid']
    box=command('select',id=starter(s)['id'],box=38)['selection']
    box=command('transform',position=[15.25,7.5,-12.5],rotation_degrees=[10,25,5],scale=[1.3,.7,1.1])['selection']
    obstacle=s['current_room']['obstacles'][0]
    command('teleport',target='player',position=[30,20,obstacle['position_in_room'][2]+5]);s=steps(1)
    obj=next(o for o in s['objects'] if o.get('kind')=='body' and o.get('name')=='scoretop' and o.get('editable'))
    body=selected({'id':obj['id']})
    target=[body['position'][0]+30,body['position'][1]+20,body['position'][2]]
    body=command('transform',position=target,rotation_degrees=[0,20,0],scale=[1.1,.9,1.2])['selection']
    command('save_level_edits')
    expected={'automatic':True,'move_speed':13,'travel_speed':2.5,'look_speed':1.75,'fov':97,
              'play_fog':False,'edit_fog':True,'use_saved_edits':True}
    command('control_settings',**expected)
    before=e.save('01-before-process-death');assert before['saved_edits']['saved']==2
    files={}
    for name in ['controls.json','level-edits.json']:
        files[name]=adb('exec-out','run-as',PACKAGE,'cat','files/shdev/'+name)
        (e.out/('before-'+name)).write_bytes(files[name])
    adb('shell','am','force-stop',PACKAGE)
    adb('shell','am','start','-n',PACKAGE+'/com.mediocre.smashhit.MainActivity')
    deadline=time.monotonic()+300;cold=None;recoveries=[];last_ui=0;window_ready=False
    while time.monotonic()<deadline:
        try:
            state=fast_request('GET')
            if state.get('pid')!=old_pid and state.get('installed') and state.get('native_loaded') and state.get('frame',0)>20:
                cold=state
            if time.monotonic()-last_ui>3:
                last_ui=time.monotonic();xml=send('hierarchy')['xml'];(e.out/'restart-window.xml').write_text(xml)
                root=ET.fromstring(xml)
                if any("isn't responding" in n.get('text','') for n in root.iter('node')):
                    wait=next(n for n in root.iter('node') if n.get('text')=='Wait')
                    bounds=list(map(int,re.findall(r'-?\d+',wait.get('bounds',''))))
                    (e.out/('restart-anr-'+str(len(recoveries))+'.xml')).write_text(xml)
                    send('tap',x=(bounds[0]+bounds[2])/2,y=(bounds[1]+bounds[3])/2,duration_ms=300)
                    recoveries.append({'action':'Tapped actual Wait button during cold startup','bounds':bounds})
                    cold=None
                elif cold is not None:window_ready=True;break
        except (OSError,ValueError,RuntimeError):pass
        time.sleep(.4)
    assert cold is not None and window_ready,'Fresh process did not finish startup'
    assert cold['pid']!=old_pid and cold['build_id']==e.device['game_build_id']
    new_device={**e.device,'native_pid':cold['pid']}
    # Earlier reports keep their own original PID. Later checks use this one.
    e.device=new_device;e.report['cold_device']=new_device;e.report['startup_recoveries']=recoveries
    (BASE/'device.json').write_text(json.dumps(new_device,indent=2)+'\n')
    e.save('02-cold-start',cold)
    for key,value in expected.items():assert cold['play_controls'][key]==value,(key,cold['play_controls'])
    assert cold['play_controls']['custom_fov'] and not cold['play_controls']['settings_error']
    assert cold['saved_edits']['saved']==2 and not cold['saved_edits']['error']
    for name,original in files.items():
        actual=adb('exec-out','run-as',PACKAGE,'cat','files/shdev/'+name)
        (e.out/('after-'+name)).write_bytes(actual);assert actual==original
    e.check('actual_process_death_retains_validated_view_fog_speed_preferences_and_saved_records',warm_pid=old_pid,cold_pid=cold['pid'])

    s=fresh();new_box=selected({'id':starter(s)['id'],'box':38})
    assert new_box['mesh_position_checksum']==box['mesh_position_checksum']
    assert new_box['collider_position_checksum']==box['collider_position_checksum'];collision(new_box)
    obstacle=s['current_room']['obstacles'][0]
    command('teleport',target='player',position=[30,20,obstacle['position_in_room'][2]+5]);s=steps(1)
    new_obj=next(o for o in s['objects'] if o.get('kind')=='body' and near(o['position'],body['position']))
    restored=e.save('03-cold-body',command('select',id=new_obj['id']))['selection']
    assert restored['geometry_checksum']==body['geometry_checksum']
    assert near(restored['rotation_degrees'],body['rotation_degrees']) and near(restored['scale_factor'],body['scale_factor'])
    collision(restored)
    e.check('new_process_rebuild_reapplies_real_box_and_authored_body_meshes_transforms_and_colliders')

    info=snapshot()['diagnostic_log'];assert info['file_limit_bytes']==8388608 and info['dropped']==0 and not info['error']
    sizes={}
    for suffix in ['', '.1', '.2']:
        try:size=int(adb('shell','run-as',PACKAGE,'stat','-c','%s','files/shdev/events.jsonl'+suffix))
        except Exception:continue
        sizes[suffix or 'current']=size;assert size<=8388608
    assert sum(sizes.values())<=3*8388608
    e.check('device_diagnostic_log_remains_bounded_across_restart',sizes=sizes)
    command('forget_level_edits');command('control_settings',automatic=True,move_speed=6,travel_speed=1,look_speed=1,
        play_fog=True,edit_fog=False,custom_fov=False)
    fresh();command('workspace',value='edit');e.finish()


if __name__=='__main__':
    evidence=Evidence('cold',__file__)
    try:run(evidence)
    except Exception as error:evidence.failure(error);raise
