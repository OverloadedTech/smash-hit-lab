#!/usr/bin/env python3
"""Actual Android touch, native edit/undo/save and rendered-FOV checks.

Requires the separate shell/root input helper and a dedicated 160 dpi test
device (960x540 Granny Smith, 540x960 PinOut). It changes the test run.
"""
import argparse, io, json, re, socket, sys, time
import xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.verify_game_lab import Experiment, close, sub

class TouchExperiment(Experiment):
    def input(self,op,**fields):
        with socket.create_connection(('127.0.0.1',self.args.input_port),timeout=5) as s:
            s.settimeout(90);s.sendall((json.dumps(dict(op=op,**fields))+'\n').encode())
            with s.makefile('rb') as f:result=json.loads(f.readline())
        if not result.get('ok'):raise RuntimeError('Android input failed: '+str(result))
        return result
    def tap(self,x,y):
        result=self.input('tap',x=x,y=y,duration_ms=600);time.sleep(.6);return result
    def ui(self):
        return list(ET.fromstring(self.input('hierarchy')['xml']).iter('node'))
    def wait_ui(self,predicate,label):
        end=time.monotonic()+90
        while time.monotonic()<end:
            try:nodes=self.ui()
            except RuntimeError as error:
                # Android can temporarily replace the accessibility root while
                # a panel is being laid out. Wait for the new tree, preserving
                # all other injection/connection failures as real failures.
                if 'No active accessibility window' not in str(error):raise
                time.sleep(.25);continue
            if any("isn't responding" in n.get('text','') for n in nodes):
                raise RuntimeError('Android has an ANR dialog over the game: '+label)
            result=predicate(nodes)
            if result:return result
            time.sleep(.25)
        raise TimeoutError('Android layout: '+label)
    def button(self,label):
        def target(nodes):
            for node in nodes:
                if node.get('text')!=label or node.get('clickable')!='true' or node.get('visible')!='true' or node.get('enabled')!='true':continue
                bounds=list(map(int,re.findall(r'-?\d+',node.get('bounds',''))))
                if len(bounds)==4 and bounds[2]>bounds[0] and bounds[3]>bounds[1]:return bounds
        bounds=self.wait_ui(target,label)
        self.report.setdefault('touch_targets',[]).append(dict(label=label,bounds=bounds))
        self.tap((bounds[0]+bounds[2])/2,(bounds[1]+bounds[3])/2)
    def screenshot(self,name):
        path=(self.out/(name+'.png')).resolve()
        if self.args.emulator_capture:
            # The emulator console reads the real compositor framebuffer without
            # starting another guest process. Useful on slow software emulators.
            raw=(self.out/(name+'-physical.png')).resolve()
            self.device('emu','screenrecord','screenshot',str(raw))
            im=Image.open(raw).convert('RGB')
            if self.pin and im.width>im.height:im=im.rotate(-90,expand=True)
            im.save(path)
            self.report['screenshot_method']='Android emulator compositor; portrait rotation recorded in source'
        else:
            data=self.device('exec-out','screencap','-p');path.write_bytes(data)
            im=Image.open(io.BytesIO(data)).convert('RGB')
            self.report['screenshot_method']='Android screencap'
        return np.asarray(im).astype(float)
    def run(self):
        initial=self.wait(lambda s:s.get('camera_ready'),'ready')
        self.check('current native source matches build',initial['addon_source_sha256']==self.report['build']['addon_source_sha256'])
        self.report['input_helper']=self.input('info');self.start()
        image=self.screenshot('start');h,w=image.shape[:2]
        if (w,h)!=((540,960) if self.pin else (960,540)):raise ValueError('This touch fixture requires the documented emulator resolution')
        self.button('Play');self.wait(lambda s:s['mode']=='play','Play button')
        self.button('Edit');s=self.wait(lambda s:s['mode']=='edit' and s['paused'],'Edit button')
        self.check('actual Edit touch pauses and enters editor',s['mode']=='edit' and s['paused'])
        self.button('Close');self.wait_ui(lambda nodes:not any(n.get('text')=='Close' and n.get('visible')=='true' for n in nodes),'panel closed')
        x,y=(.8,.5) if self.pin else (.5,.7)
        before=self.q('pick',x=x,y=y);self.check('visible body selected for touch drag',bool(before['selected']))
        obj=before['selected'][0];self.screenshot('selected')
        if not self.pin:probe=self.q('physics_ray',**{'from':[0,-60,0],'to':[0,-95,0],'category_mask':252})['native_probe']
        self.input('drag',x=x*w,y=y*h,to_x=x*w+25,to_y=y*h-18,duration_ms=1400)
        after=self.wait(lambda s:s.get('undo_count',0)==before['undo_count']+1,'native drag completed')
        moved=next(o for o in after['selected'] if o['key']==obj['key'])
        self.check('touch drag moves the native body',not close(obj['position'],moved['position']))
        self.check('one Android drag creates one undo step',after['undo_count']==before['undo_count']+1)
        if self.pin and obj['detail'].get('buffer')=='shared table VBO':
            self.check('drag updates baked native render bytes',obj['detail']['native_render_fnv1a32']!=moved['detail']['native_render_fnv1a32'])
        elif not self.pin:
            next_probe=self.q('physics_ray',**{'from':[0,-60,0],'to':[0,-95,0],'category_mask':252})['native_probe']
            delta=sub(moved['position'],obj['position']);normal=probe['normal_native']
            expected=delta[1]+normal[0]/normal[1]*delta[0]
            self.check('Android drag moves the actual Box2D fixture',probe['key']==obj['key']==next_probe['key'] and abs(next_probe['position'][1]-probe['position'][1]-expected)<.005)
        self.screenshot('dragged')
        self.button('Edit');self.button('Undo')
        restored=self.wait(lambda s:s.get('undo_count')==before['undo_count'],'Undo button')
        self.check('actual Undo button restores native pose',close(restored['selected'][0]['position'],obj['position']))
        self.button('Redo');self.wait(lambda s:s.get('undo_count')==before['undo_count']+1,'Redo button')
        self.button('Save selection');saved=self.wait(lambda s:s.get('saved_edit_count',0)>0,'Save selection button')
        self.check('actual Save selection writes native overrides',saved['saved_edit_count']>0)
        self.button('Camera');self.wait(lambda s:s['mode']=='camera','Camera button')
        a=self.c.snapshot();self.input('drag',x=w*.65,y=h*.35,to_x=w*.75,to_y=h*.30,duration_ms=1000)
        s=self.wait(lambda s:not close(a['camera']['rotation'],s['camera']['rotation']),'look drag')
        self.check('actual look drag turns camera without moving player',close(a['player']['position'],s['player']['position']) and not close(a['camera']['rotation'],s['camera']['rotation']))
        self.q('clear_saved_edits');self.q('reload_level');self.q('mode',value='play');self.q('mode',value='camera');self.q('clear_selection')
        images=[]
        for name,fov in [('fov60',60),('fov110',110),('fov60-restored',60)]:
            self.q('settings',fov=fov);self.frames(5);images.append(self.screenshot(name))
        # Original UI/scene fades can change overall brightness even with world
        # physics paused. Remove each channel's mean before comparing spatial
        # image content; retain all three original screenshots as evidence.
        def crop(im):
            region=im[80:h-70,180:w-20]
            return region-region.mean(axis=(0,1),keepdims=True)
        changed=float(np.abs(crop(images[1])-crop(images[0])).mean());restored=float(np.abs(crop(images[2])-crop(images[0])).mean())
        self.check('FOV visibly changes native game rendering',changed>5 and changed>restored*2,dict(brightness_normalized_pixel_change=changed,restored_difference=restored))
        self.q('settings',fov_override=False);self.button('Play');s=self.wait(lambda s:s['mode']=='play','normal play restored')
        self.check('actual Play button releases the Lab pause',not s['paused']);self.screenshot('normal-play');self.report['final_snapshot']=s;self.report['completed']=True;self.save()

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--game',choices=['pinout','granny-smith'],required=True);p.add_argument('--serial',required=True);p.add_argument('--port',type=int);p.add_argument('--input-port',type=int,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--allow-reset',action='store_true');p.add_argument('--emulator-capture',action='store_true');a=p.parse_args()
    if not a.allow_reset:raise SystemExit('Use a dedicated test installation and --allow-reset')
    e=TouchExperiment(a)
    try:e.run()
    except Exception as error:e.report['error']=repr(error);e.save();raise
    finally:e.samples.close()
if __name__=='__main__':main()
