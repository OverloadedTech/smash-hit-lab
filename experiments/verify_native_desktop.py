#!/usr/bin/env python3
"""Exercise browser gizmos and apply real body/group edits to a running Lab."""
import argparse, hashlib, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.verify_game_lab import Experiment, close, add
from playwright.sync_api import sync_playwright

class DesktopExperiment(Experiment):
    def run(self):
        initial=self.wait(lambda s:s.get('addon_source_sha256'),'identified build')
        self.check('running native source matches APK build',initial['addon_source_sha256']==self.report['build']['addon_source_sha256'])
        self.start()
        self.report['desktop_sources']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [ROOT/'desktop/game_server.py',*sorted((ROOT/'desktop/game_web').glob('*'))] if p.is_file()}
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader'])
            page=browser.new_page(viewport={'width':1400,'height':900});errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)));page.goto(self.args.url)
            page.locator('#connect').click()
            page.wait_for_function('window.mediocreEditor?.project?.objects.length > 20',timeout=180000)
            project=page.evaluate('mediocreEditor.project');key=next(o['key'] for o in project['objects'] if o['key'].endswith('@0/body/11' if self.pin else '/body/461'))
            before=next(o for o in project['objects'] if o['key']==key)
            self.check('desktop displays actual native triangles',all(o['geometry']['kind']=='native render triangles' for o in project['objects']))
            page.locator('#filter').fill(key);page.locator('#objects').select_option(key)
            self.check('object list selects the native body',page.evaluate('mediocreEditor.selected')==[key])
            page.locator('#focus').click();page.wait_for_timeout(700)
            # Inspect the real rendered handle positions, then drive actual mouse
            # events. No direct TransformControls or project mutation substitutes
            # for dragging the gizmo.
            handles=page.evaluate('''() => {
                const e=mediocreEditor,r=e.renderer.domElement.getBoundingClientRect(),out=[];
                e.controls._gizmo.gizmo.translate.traverse(m=>{
                    if(!m.isMesh||!m.visible||m.name!=='X')return;
                    m.geometry.computeBoundingSphere();const p=m.geometry.boundingSphere.center.clone().applyMatrix4(m.matrixWorld).project(e.camera);
                    out.push({x:r.x+(p.x+1)*r.width/2,y:r.y+(1-p.y)*r.height/2});
                });return out;
            }''')
            chosen=None
            for point in handles:
                if not 20<point['x']<1020 or not 115<point['y']<830:continue
                page.mouse.move(point['x'],point['y']);page.wait_for_timeout(150)
                if page.evaluate('mediocreEditor.controls.axis')=='X':chosen=point;break
            self.check('translation handle is actually pickable',chosen is not None,handles)
            page.mouse.down();page.mouse.move(chosen['x']+55,chosen['y'],steps=16);page.mouse.up();page.wait_for_timeout(250)
            position=page.evaluate('(key)=>mediocreEditor.project.objects.find(o=>o.key===key).position',key)
            self.check('mouse drag changes position along gizmo X',abs(position[0]-before['position'][0])>.005 and close(position[1:],before['position'][1:]))
            page.screenshot(path=str(self.out/'gizmo-dragged.png'))
            with page.expect_response('**/api/apply',timeout=180000) as response:page.locator('#apply').click()
            result=response.value.json();self.record('desktop_gizmo_apply',result)
            self.check('gizmo edit reaches actual native body',response.value.ok and close(result['selected'][0]['position'],position))
            page.locator('#undo').click()
            with page.expect_response('**/api/apply',timeout=180000) as response:page.locator('#apply').click()
            result=response.value.json();self.record('desktop_gizmo_undo',result)
            self.check('desktop undo can restore native pose',response.value.ok and close(result['selected'][0]['position'],before['position']))

            second=next(o for o in project['objects'] if o['editable'] and o['key']!=key)
            page.locator('#multi').check();page.locator('#filter').fill(second['key']);page.locator('#objects').select_option(second['key'])
            self.check('multiple native objects selected',set(page.evaluate('mediocreEditor.selected'))=={key,second['key']})
            page.locator('#step').fill('.25');page.locator('#steps').get_by_text('Y +',exact=True).click()
            with page.expect_response('**/api/apply',timeout=180000) as response:page.locator('#saveGame').click()
            result=response.value.json();self.record('desktop_group_save',result);positions={o['key']:o['position'] for o in result.get('selected',[])}
            self.check('bulk step applies and saves both native poses',response.value.ok and result['saved_edit_count']==2 and
                close(positions[key],add(before['position'],[0,.25,0])) and close(positions[second['key']],add(second['position'],[0,.25,0])))
            page.screenshot(path=str(self.out/'group-applied.png'))

            identity={k:project[k] for k in ('game','library_sha256','pid','scene_epoch')}
            poses={key:{k:before[k] for k in ('position','quaternion','scale')}}
            wrong=dict(identity,pid=identity['pid']+1)
            response=page.request.post(self.args.url+'/api/apply',data={'identity':wrong,'poses':poses})
            self.check('stale process edit is rejected',response.status==400 and 'restarted' in response.json().get('error',''))
            self.q('clear_saved_edits');self.q('reload_level')
            response=page.request.post(self.args.url+'/api/apply',data={'identity':identity,'poses':poses})
            self.check('reloaded scene edit is rejected',response.status==400 and 'scene changed' in response.json().get('error',''))
            self.check('browser has no JavaScript errors',not errors,errors)
            browser.close()
        self.report['final_snapshot']=self.q('mode',value='play');self.report['completed']=True;self.save()

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--game',choices=['pinout','granny-smith'],required=True);p.add_argument('--serial',required=True);p.add_argument('--port',type=int);p.add_argument('--url',required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--allow-reset',action='store_true');a=p.parse_args()
    if not a.allow_reset:raise SystemExit('Use a dedicated test installation and --allow-reset')
    e=DesktopExperiment(a)
    try:e.run()
    except Exception as error:e.report['error']=repr(error);e.save();raise
    finally:e.samples.close()
if __name__=='__main__':main()
