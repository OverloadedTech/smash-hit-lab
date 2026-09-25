#!/usr/bin/env python3
"""Behavior checks against an isolated, running embedded Lab (changes its run).

Use --allow-reset only on a dedicated test installation. This clears Lab saved
geometry overrides, loads levels, moves the player and restores normal settings.
Every assertion uses native state or the game's original collision query.
"""
import argparse, datetime, hashlib, json, math, subprocess, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.game_lab import Client

def close(a,b,tolerance=1e-3):return len(a)==len(b) and max(abs(x-y) for x,y in zip(a,b))<tolerance
def add(a,b):return [x+y for x,y in zip(a,b)]
def sub(a,b):return [x-y for x,y in zip(a,b)]
def mul(a,s):return [x*s for x in a]
def length(a):return math.sqrt(sum(x*x for x in a))
def rotate(q,p):
    x,y,z,w=q;u=[x,y,z];cross=[y*p[2]-z*p[1],z*p[0]-x*p[2],x*p[1]-y*p[0]]
    dot=sum(a*b for a,b in zip(u,p));return [2*dot*u[i]+(w*w-sum(v*v for v in u))*p[i]+2*w*cross[i] for i in range(3)]

class Experiment:
    def __init__(self,args):
        self.args=args;self.pin=args.game=='pinout';self.c=Client(args.port or (18767 if self.pin else 18768),timeout=30)
        self.package='com.mediocre.'+('pinout' if self.pin else 'grannysmith')+'.dev'
        self.adb=[str(ROOT/'tools/sdk/platform-tools/adb'),'-s',args.serial]
        self.out=args.out;self.out.mkdir(parents=True,exist_ok=True)
        self.samples=(self.out/'samples.jsonl').open('w')
        self.report={'date':datetime.datetime.now(datetime.timezone.utc).isoformat(),'game':args.game,'checks':[],
            'completed':False,'serial':args.serial,
            'experiment_sources':{str(p.resolve().relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                for p in {Path(__file__),Path(sys.argv[0])} if p.is_file() and p.resolve().is_relative_to(ROOT)},
            'build':json.loads((ROOT/'artifacts'/f'{args.game}-build-report.json').read_text())}
    def device(self,*args):return subprocess.run(self.adb+list(args),check=True,capture_output=True,timeout=120).stdout
    def record(self,label,s):self.samples.write(json.dumps({'label':label,'host_time':time.time(),'snapshot':s})+'\n');self.samples.flush();return s
    def q(self,op,**values):return self.record(op,self.c.command(dict(op=op,**values),timeout=90))
    def check(self,name,condition,detail=None):
        self.report['checks'].append({'name':name,'passed':bool(condition),'detail':detail});self.save()
        print(('PASS ' if condition else 'FAIL ')+name,flush=True)
        if not condition:raise AssertionError(name)
    def save(self):
        self.report['passed']=self.report.get('completed',False) and bool(self.report['checks']) and all(x['passed'] for x in self.report['checks']) and not self.report.get('error')
        (self.out/'report.json').write_text(json.dumps(self.report,indent=2)+'\n')
    def wait(self,predicate,label,timeout=60):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            try:
                s=self.c.snapshot()
                if predicate(s):return self.record(label,s)
            except (RuntimeError,OSError):pass
            time.sleep(.15)
        raise TimeoutError(label)
    def frames(self,count=12):
        start=self.c.snapshot()['frame'];return self.wait(lambda s:s.get('frame',0)>=start+count,'wait_frames')
    def scene(self):
        self.q('export_scene')
        data=self.device('exec-out','run-as',self.package,'cat','files/mediocre-lab/scene.json')
        scene=json.loads(data);(self.out/'scene.json').write_bytes(data);return scene
    def start(self):
        self.wait(lambda s:s.get('game_state',0)>=1 and s.get('camera_ready'),'ready')
        self.q('clear_saved_edits');self.q('settings',simulation_speed=1,look_speed=1,move_speed=3,immortal=False,noclip=True,fov_override=False,fog=True)
        if self.pin:
            self.q('start_run');self.wait(lambda s:s.get('game_state')==2 and s.get('mesh_records',0)>20,'run loaded',timeout=180)
        else:self.q('goto_level',path='levels/farm/1.xml')
        self.q('mode',value='play');self.q('mode',value='edit');self.frames(4)
    def run(self):
        initial=self.wait(lambda s:s.get('addon_source_sha256'),'identified build')
        self.check('running native source matches APK build',initial['addon_source_sha256']==self.report['build']['addon_source_sha256'])
        self.start();s=self.c.snapshot();self.report['initial_pid']=s['pid']
        self.check('real objects captured',s['object_count']>20,s['object_count'])
        a=self.c.snapshot();b=self.frames(20)
        self.check('pause stops player and physics',close(a['player']['position'],b['player']['position']) and a['updates']==b['updates'])
        self.check('render frames continue while paused',b['frame']>a['frame'] and b['skipped_updates']>a['skipped_updates'])
        player=b['player']['position'];active=[t['index'] for t in b['sections'] if t['active']]
        self.q('mode',value='camera');self.q('bookmark_save')
        for axis in ([1,0,0],[-1,0,0],[0,1,0],[0,-1,0],[0,0,1],[0,0,-1]):
            a=self.c.snapshot()['camera']['position'];self.q('move',value=axis);self.frames(5);b=self.q('move',value=[0,0,0])
            self.check('camera movement '+str(axis),length(sub(b['camera']['position'],a))>.005)
        self.q('bookmark_restore');a=self.c.snapshot()['camera'];b=self.q('look_back')['camera']
        self.check('look behind is a half turn',abs(sum(x*y for x,y in zip(a['rotation'],b['rotation'])))<.001)
        self.q('look_back');b=self.q('teleport_camera',position=add(a['position'],[100,-100,100]))
        self.check('camera teleport leaves player and active sections fixed',close(player,b['player']['position']) and active==[t['index'] for t in b['sections'] if t['active']])
        self.q('bookmark_restore');s=self.q('settings',fov=105)
        self.check('FOV control accepted',s['fov_override'] and abs(s['fov']-105)<.001)
        self.q('settings',fov_override=False)
        self.geometry()
        self.persistence()
        self.player()
        if self.pin:self.streaming()
        else:self.catalogue()
        self.q('settings',immortal=False,simulation_speed=1,move_speed=6,look_speed=1,fov_override=False,fog=True,noclip=True)
        self.q('clear_saved_edits');self.q('reload_level');self.q('mode',value='play');a=self.c.snapshot();b=self.frames(16)
        self.check('original simulation resumes',b['updates']>a['updates'])
        self.report['final_snapshot']=b;self.report['completed']=True;self.save()
    def geometry(self):
        self.q('mode',value='edit');scene=self.scene()
        self.check('export uses native triangle geometry',all(o['geometry']['kind']=='native render triangles' for o in scene['objects']) and sum(len(o['geometry']['triangles']) for o in scene['objects'])>100)
        pick=self.q('pick',x=.8 if self.pin else .5,y=.5 if self.pin else .7)
        self.check('screen ray selects a real rendered body',bool(pick['selected']))
        if self.pin:
            body=next(o for o in scene['objects'] if o['key'].endswith('@0/body/11'))
            self.key=body['key'];self.q('select',key=self.key);before=self.c.snapshot()['selected'][0]
            self.q('transform',move=[50,0,0]);moved=self.c.snapshot()['selected'][0]
            self.check('translation updates actual shared render bytes',before['detail']['native_render_fnv1a32']!=moved['detail']['native_render_fnv1a32'])
            chosen=None
            for face in body['geometry']['collision']['triangles']:
                v=[body['geometry']['collision']['vertices'][i] for i in face]
                u=sub(v[1],v[0]);w=sub(v[2],v[0]);n=[u[1]*w[2]-u[2]*w[1],u[2]*w[0]-u[0]*w[2],u[0]*w[1]-u[1]*w[0]]
                if length(n)<1e-7:continue
                n=rotate(body['quaternion'],mul(n,1/length(n)))
                center=[sum(p[k] for p in v)/3 for k in range(3)];world=add(add(body['position'],[50,0,0]),rotate(body['quaternion'],center))
                table=scene['sections'][0]
                # Use a real vertical side face, above the implicit Z=0 floor.
                # This body is only 0.0347 units tall; its side-face centroids
                # are 0.0116/0.0231, so a guessed 0.025 cutoff finds no face.
                if abs(n[0])<.8 or abs(n[2])>.01 or world[2]<.005 or not table['start']+.1<world[1]<table['start']+table['length']-.1:continue
                probe=self.q('physics_ray',**{'from':add(world,mul(n,.015)),'to':sub(world,mul(n,.015))})['native_probe']
                if probe['hit'] and close(probe['position'],world,.003):chosen=(center,n,world);break
            self.check('original native collision query sees moved body',chosen is not None)
            center,n,world=chosen;self.q('transform',move=mul(n,.08));world=add(world,mul(n,.08))
            probe=self.q('physics_ray',**{'from':add(world,mul(n,.015)),'to':sub(world,mul(n,.015))})['native_probe']
            self.check('native collision follows a second translation',probe['hit'] and close(probe['position'],world,.003))
            old=self.c.snapshot()['selected'][0]['detail']['native_render_fnv1a32'];s=self.q('transform',scale_by=[1.1,1.05,1.2]);current=s['selected'][0]
            world=add(current['position'],rotate(current['quaternion'],[center[i]*current['scale'][i] for i in range(3)]))
            probe=self.q('physics_ray',**{'from':add(world,mul(n,.03)),'to':sub(world,mul(n,.03))})['native_probe']
            self.check('scale updates render buffer and native collision tree',old!=current['detail']['native_render_fnv1a32'] and probe['hit'] and close(probe['position'],world,.003))
            for _ in range(3):self.q('undo')
        else:
            probe=self.q('physics_ray',**{'from':[0,-60,0],'to':[0,-95,0],'category_mask':252})['native_probe']
            self.check('original Box2D query identifies editable terrain',probe['hit'] and bool(probe['key']),probe)
            self.key=probe['key'];self.q('select',key=self.key);before=self.c.snapshot()['selected'][0]
            self.q('transform',move=[0,1,0]);after=self.q('physics_ray',**{'from':[0,-60,0],'to':[0,-95,0],'category_mask':252})['native_probe']
            self.check('Box2D fixture moves with rendered terrain',after['key']==self.key and abs(after['position'][1]-probe['position'][1]-1)<.003)
            old=self.c.snapshot()['selected'][0]['detail']['native_render_fnv1a32'];s=self.q('transform',scale_by=[1.05,1.05,1.1])
            scaled=self.q('physics_ray',**{'from':[0,-60,0],'to':[0,-95,0],'category_mask':252})['native_probe']
            self.check('scaling rebuilds native vertices and Box2D geometry',s['selected'][0]['detail']['native_render_fnv1a32']!=old and scaled['hit'] and abs(scaled['position'][1]-after['position'][1])>.01)
            self.q('undo');self.q('undo')
            dynamic=next((o for o in scene['objects'] if not o['detail'].get('scale_supported',True)),None)
            if dynamic:
                self.q('select',key=dynamic['key'],add=True);a=self.c.snapshot()['selected']
                try:self.q('transform',move=[2,0,0],scale_by=[1.1,1.1,1.1]);rejected=False
                except RuntimeError:rejected=True
                b=self.c.snapshot()['selected'];self.check('unsupported bulk scale leaves every body unchanged',rejected and all(close(x['position'],y['position']) for x,y in zip(a,b)))
            self.q('select',key=self.key)
        restored=self.c.snapshot()['selected'][0]
        self.check('native undo restores object pose and scale',close(before['position'],restored['position']) and close(before['scale'],restored['scale']))
        self.q('transform',rotate=[5,7,9]);turned=self.c.snapshot()['selected'][0]
        self.check('rotation changes the actual body quaternion',not close(before['quaternion'],turned['quaternion']))
        self.q('undo')
        self.q('select_all');a={o['key']:o['position'] for o in self.c.snapshot()['selected']};s=self.q('transform',move=[.1,.2,0]);b={o['key']:o['position'] for o in s['selected']}
        self.check('bulk move preserves group spacing',len(a)>20 and all(close(add(p,[.1,.2,0]),b[k]) for k,p in a.items()));self.q('undo');self.q('select',key=self.key)
    def persistence(self):
        self.q('select',key=self.key);s=self.q('transform',move=[.025 if self.pin else .25,0,0]);expected=s['selected'][0]['position'];self.q('save_edits');pid=s['pid']
        self.q('reload_level');self.q('mode',value='edit');s=self.q('select',key=self.key)
        self.check('saved edit reappears after native level reload',bool(s['selected']) and close(s['selected'][0]['position'],expected),{'expected':expected,'selected':s['selected']})
        self.device('shell','am','force-stop',self.package)
        main='com.mediocre.pinout.MainActivity' if self.pin else 'com.mediocre.grannysmith.Main'
        self.device('shell','am','start','-n',self.package+'/'+main)
        self.wait(lambda s:s.get('pid')!=pid and s.get('game_state',0)>=1 and s.get('camera_ready'),'fresh process',timeout=180)
        if self.pin:
            self.q('start_run');self.wait(lambda s:s.get('game_state')==2 and s.get('mesh_records',0)>20,'new run')
        else:self.q('goto_level',path='levels/farm/1.xml')
        self.q('mode',value='edit');s=self.q('select',key=self.key)
        self.check('saved edit survives process death',bool(s['selected']) and close(s['selected'][0]['position'],expected) and s['pid']!=pid)
        self.q('clear_saved_edits');self.q('reload_level');self.q('mode',value='edit')
    def player(self):
        self.q('settings',immortal=True,noclip=True);s=self.q('mode',value='player');p=s['player']['position']
        target=add(p,[3,0,2]) if self.pin else add(p,[-10,8,0]);self.q('teleport_player',position=target);a=self.frames(12)
        self.check('noclip holds the actual player outside normal geometry',close(a['player']['position'],target,.02))
        if not self.pin:self.check('character native collider is inactive during noclip',not a['player']['collision_active'])
        else:self.check('ball collision callbacks are suppressed',a['noclip_blocked_contacts']>0)
        self.q('move',value=[1,1,0]);self.frames(8);s=self.q('move',value=[0,0,0]);self.check('player movement controls change native coordinates',length(sub(s['player']['position'],target))>.01)
        self.q('mode',value='camera');s=self.c.snapshot()
        if not self.pin:self.check('leaving player mode restores collision',s['player']['collision_active'])
        else:
            a=s['time_remaining'];self.q('pause',value=False);self.frames(25);b=self.q('pause',value=True)
            self.check('unlimited time prevents countdown',b['time_remaining']>=a-.001)
        self.q('settings',immortal=False);self.q('reload_level')
    def streaming(self):
        self.q('mode',value='camera');self.q('settings',immortal=True);a=self.c.snapshot();cam=a['camera']['position']
        self.q('goto_section',index=10,recenter=False);s=self.c.snapshot()
        self.check('forward teleport activates tables 9–12',s['current_section']==10 and [t['index'] for t in s['sections'] if t['active']]==[9,10,11,12])
        self.check('teleport finishes active geometry while paused',all(t['stage']==100 for t in s['sections'] if t['active']))
        self.check('section teleport can leave camera fixed',close(cam,s['camera']['position']))
        s=self.q('goto_section',index=1,recenter=False)
        self.check('backward teleport reactivates tables 0–3',s['current_section']==1 and [t['index'] for t in s['sections'] if t['active']]==[0,1,2,3])
        s=self.q('goto_section',index=124)
        self.check('last campaign table is reachable',s['current_section']==124)
        self.q('goto_section',index=0);self.q('reload_level')
    def catalogue(self):
        s=self.c.snapshot();levels=s['levels'];self.check('all campaign level entries exposed',len(levels)==57)
        target=levels[-1];s=self.q('goto_level',path=target['path']);self.check('last campaign level loads through native loader',s['current_section']==target['id'] and s['native_entities']>0)
        self.q('goto_level',path='levels/farm/1.xml')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--game',choices=['pinout','granny-smith'],required=True);p.add_argument('--serial',required=True);p.add_argument('--port',type=int);p.add_argument('--out',type=Path,required=True);p.add_argument('--allow-reset',action='store_true');args=p.parse_args()
    if not args.allow_reset:raise SystemExit('Use a dedicated test installation and explicitly pass --allow-reset')
    experiment=Experiment(args)
    try:experiment.run()
    except Exception as error:
        experiment.report['error']=repr(error);experiment.save();raise
    finally:experiment.samples.close()

if __name__=='__main__':main()
