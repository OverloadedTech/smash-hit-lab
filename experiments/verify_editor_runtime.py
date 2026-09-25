#!/usr/bin/env python3
"""Move a desktop selection, apply its edits to Android, then verify native physics."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import os
import sys

from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.lab import command,snapshot,step
from experiments.phase2_controls import reset,near

BASE = ROOT / os.environ.get('SHLAB_EDITOR_EVIDENCE', 'experiments/editor_improvements')
OUT = BASE / 'runtime'
OUT.mkdir(parents=True,exist_ok=True)


def save(name,data):
    (OUT/(name+'.json')).write_text(json.dumps(data,indent=2)+'\n')
    return data


def run():
    device=json.loads((BASE / 'device.json').read_text())
    assert snapshot()['pid']==device['native_pid']
    report={**device,'start_utc':datetime.now(timezone.utc).isoformat(),
        'harness_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'checks':[],'result':'RUNNING'}
    save('report',report)
    s=reset();batch=next(b for b in s['current_room']['batches'] if b['path'].endswith('/start.mesh'))
    original=save('00_original',command('select',id=batch['id'],box=38))['selection']
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader'])
        page=browser.new_page(viewport={'width':1600,'height':1100})
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto('http://127.0.0.1:8765/')
        page.wait_for_function('window.shlab?.state.instances.length===1')
        page.locator('#box-select').select_option('38')
        for key,values in {'position':[30,20,-10],'rotation':[15,30,10],'scale':[2,.5,2]}.items():
            for i,value in enumerate(values): page.locator(f'[data-vector="{key}"] input').nth(i).fill(str(value))
        page.locator('#apply').click()
        page.locator('#select-boxes').click()
        page.locator('#move-step').fill('5')
        page.locator('[data-nudge="0,1"]').click();page.locator('[data-nudge="1,1"]').click()
        project=page.evaluate('shlab.project()');item=project['segments'][0]
        assert len(item['edits'])==182 and item['edits']['38']['position']==[35,25,-10]
        page.locator('#runtime summary').click()
        with page.expect_response('**/api/runtime?*',timeout=120000) as lookup:
            page.locator('#refresh-runtime').click()
        found=lookup.value.json();assert found['editor_api_version']==2
        page.locator('#runtime-target').select_option(str(batch['id']))
        before=snapshot()
        rejected=page.request.post('http://127.0.0.1:8765/api/runtime/apply',data={
            'project':project,'instance':item['id'],'native_id':batch['id'],'native_pid':device['native_pid']+1})
        assert rejected.status==400 and 'process changed' in rejected.json()['error']
        assert snapshot()['last_command']==before['last_command']
        save('01_stale_process_rejected',rejected.json())
        n=snapshot()['selection_group']['undo_count']
        with page.expect_response('**/api/runtime/apply',timeout=180000) as response:
            page.locator('#apply-runtime').click()
        applied=save('02_bulk_applied',response.value.json())
        assert response.value.ok,applied
        assert applied['applied_boxes']==182 and applied['single_undo'] and applied['world_paused']
        assert applied['selection_group']['count']==182 and applied['selection_group']['undo_count']==n+1
        target=save('03_edited_box',command('select',id=batch['id'],box=38))['selection']
        assert near(target['position'],[35,25,-10]) and near(target['rotation_degrees'],[15,30,10]) and near(target['scale_factor'],[2,.5,2])
        assert target['mesh_position_checksum']!=original['mesh_position_checksum']
        assert target['collider_position_checksum']!=original['collider_position_checksum']
        bounds=target['bounds'];center=[(bounds['min'][i]+bounds['max'][i])/2 for i in range(3)]
        hit=save('04_native_collision',command('raycast',start=[center[0],bounds['max'][1]+2,center[2]],end=[center[0],bounds['min'][1]-2,center[2]]))
        assert hit['raycast']['hit'] and hit['raycast']['shape']==target['collider']
        undone=command('edit_undo');assert undone['selection_group']['count']==182
        restored=command('select',id=batch['id'],box=38)['selection']
        assert restored['mesh_position_checksum']==original['mesh_position_checksum'] and restored['collider_position_checksum']==original['collider_position_checksum']
        command('edit_redo')
        command('teleport',target='player',position=[0,1,-55]);rebased=step(1)
        assert rebased['world_origin_z']!=0
        with page.expect_response('**/api/runtime/apply',timeout=180000) as response:
            page.locator('#apply-runtime').click()
        repeated=save('05_reapplied_after_rebase',response.value.json())
        assert response.value.ok and repeated['applied_boxes']==182 and repeated['single_undo'],repeated
        now=command('select',id=batch['id'],box=38)['selection']
        assert near(now['position'],target['position']) and near(now['rotation_degrees'],target['rotation_degrees'])
        hit=command('raycast',start=[center[0],bounds['max'][1]+2,center[2]],end=[center[0],bounds['min'][1]-2,center[2]])
        assert hit['raycast']['hit'] and hit['raycast']['shape']==target['collider']
        command('edit_undo');command('edit_undo')
        final=save('06_all_applies_undone',command('select',id=batch['id'],box=38))['selection']
        assert final['mesh_position_checksum']==original['mesh_position_checksum'] and near(final['position'],original['position'])
        page.screenshot(path=str(OUT/'desktop-bulk-to-android.png'))
        assert not errors,errors
        report['checks']=[
            'Real desktop numeric transform plus group nudges edit 182 source boxes',
            'Explicit native segment target and stale PID rejection before mutation',
            'One native bulk operation changes all mapped meshes and colliders',
            'Native raycast hits a moved, rotated and scaled box',
            'One Android Undo restores all 182 boxes, Redo reapplies them',
            'Repeat application after native origin rebase preserves world coordinates and collision',
            'Undo both apply operations restores original world pose and mesh',
            'No browser script errors',
        ]
        browser.close()
    reset()
    report.update(result='PASS',finish_utc=datetime.now(timezone.utc).isoformat())
    save('report',report);print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':
    try:run()
    except Exception as error:
        save('failure',{'error':repr(error),'snapshot':snapshot()});raise
