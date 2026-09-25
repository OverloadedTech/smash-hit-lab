/* Instrument the original APK through Frida. Offsets are for the verified
 * 1.5.14 x86_64 build only. Commands execute on Game::frame, never the RPC thread.
 * This laboratory probe is separate from the packaged developer implementation.
 */
'use strict';
const m = Process.getModuleByName('libsmashhit.so');
const sym = n => m.getExportByName(n);
const gameGlobal = sym('gGame');
const pending = [];
let tick = 0, frame = 0, originZ = 0, frozen = false;
let lastSample = 0;
const vec = (p, n=3) => Array.from({length:n}, (_, i) => p.add(4*i).readFloat());
function qiString(p) {
    const heap = p.readPointer();
    return (heap.isNull() ? p.add(16) : heap).readUtf8String();
}
function room(p) {
    if (p.isNull()) return null;
    const batches = [];
    const n = p.add(0x3ff8).readS32();
    const data = p.add(0x4000).readPointer();
    for (let i=0; i<n && i<1000; ++i) {
        const b = data.add(i*8).readPointer();
        batches.push({address:b.toString(),mesh:qiString(b.add(0x90)),offset:b.add(0x88).readFloat(),loaded:b.add(0x8c).readU8()!==0,z:vec(b,2)});
    }
    const defs = [];
    const nd = p.add(0x98).readS32();
    const dd = p.add(0xa0).readPointer();
    for (let i=0; i<nd && i<2000; ++i) {
        const d=dd.add(i*0xb0);
        defs.push({index:i,type:qiString(d),position:vec(d.add(0x30)),instance:d.add(0x60).readPointer().toString(),created:d.add(0xa8).readU8()!==0});
    }
    return {address:p.toString(),name:qiString(p.add(8)),index:p.add(0x47d4).readS32(),length:p.add(0x38).readFloat(),offset:p.add(0x3c).readFloat(),obstacles:p.add(0x2ca8).readS32(),batches,definitions:defs};
}
function snapshot() {
    const g=gameGlobal.readPointer();
    if(g.isNull()) return {game:null};
    const l=g.add(0x58).readPointer();
    const display=g.add(0x10).readPointer();
    return {time:Date.now(),frame,tick,frozen,originZ,game:g.toString(),state:g.add(0x180).readS32(),level:l.toString(),active:l.add(0x118).readU8(),position:vec(l.add(0x11c)),rotation:vec(l.add(0x128),4),camera:vec(display.add(0x8c4)),cameraRotation:vec(display.add(0x8d0),4),entities:l.add(0x148).readS32(),bodies:l.add(0x158).readS32(),distance:l.add(0x188).readFloat(),current:room(l.add(0xf8).readPointer()),next:room(l.add(0x100).readPointer())};
}
function emit(event, data={}) {send({event,time:Date.now(),frame,tick,...data});}
Interceptor.attach(sym('_ZN4Game5frameEv'), {
    onEnter(args) {
        ++frame;
        for(const cmd of pending.splice(0)) {
            try {
                const g=args[0], l=g.add(0x58).readPointer();
                if(cmd.op==='freeze') frozen=!!cmd.value;
                else if(cmd.op==='position') cmd.value.forEach((v,i)=>l.add(0x11c+i*4).writeFloat(v));
                else if(cmd.op==='snapshot') emit('snapshot',{id:cmd.id,snapshot:snapshot()});
                else throw new Error('Unknown command '+cmd.op);
                emit('command',{command:cmd});
            } catch(e) {emit('command_error',{command:cmd,error:String(e)});}
        }
        const now=Date.now();
        if(now-lastSample>1000) {lastSample=now;try {emit('sample',{snapshot:snapshot()});}catch(e){emit('sample_error',{error:String(e)});}}
    }
});
const updateAddress=sym('_ZN5Level6updateEv');
const originalUpdate=new NativeFunction(updateAddress,'void',['pointer']);
Interceptor.replace(updateAddress,new NativeCallback(function(l){
    if(frozen) return;
    ++tick;
    originalUpdate(l);
},'void',['pointer']));
Interceptor.attach(sym('_ZN5Level12centerCameraEv'),{
    onEnter(args){this.oldZ=args[0].add(0x124).readFloat();},
    onLeave(){originZ+=this.oldZ;emit('rebase',{oldZ:this.oldZ,originZ});}
});
Interceptor.attach(sym('_ZN4RoomC2EP5LevelRK8QiStringRK7QiArrayI9ParameterEf'),{
    onEnter(args){this.r=args[0];this.name=qiString(args[2]);},
    onLeave(){emit('room_create',{name:this.name,room:room(this.r)});}
});
Interceptor.attach(sym('_ZN4RoomD2Ev'),{
    onEnter(args){emit('room_destroy',{room:room(args[0])});}
});
Interceptor.attach(sym('_ZN4Room14createObstacleERK8QiStringRK12QiTransform3RK7QiArrayI9ParameterE'),{
    onEnter(args){this.r=args[0];this.name=qiString(args[1]);this.pos=vec(args[2]);},
    onLeave(ret){emit('obstacle_create',{room:this.r.toString(),type:this.name,position:this.pos,instance:ret.toString()});}
});
Interceptor.attach(sym('_ZN8ObstacleD2Ev'),{
    onEnter(args){emit('obstacle_destroy',{instance:args[0].toString(),room:args[0].readPointer().toString()});}
});
Interceptor.attach(sym('_ZN11RenderBatch4loadEv'),{
    onEnter(args){this.b=args[0];this.name=qiString(args[0].add(0x90));},
    onLeave(){emit('batch_load',{address:this.b.toString(),mesh:this.name,vertices:this.b.add(0x28).readS32(),indexCount:this.b.add(0x70).readS32()});}
});
rpc.exports={
    snapshot,
    command(cmd){pending.push(cmd);return {queued:true};},
    body(index){const g=gameGlobal.readPointer(),l=g.add(0x58).readPointer();const count=l.add(0x158).readS32();if(index<0||index>=count)throw new Error('index');const b=l.add(0x160).readPointer().add(index*8).readPointer();return {address:b.toString(),position:vec(b.add(0x20)),rotation:vec(b.add(0x2c),4),bounds:vec(b.add(0x3c),6),shapes:b.add(0x110).readS32(),obstacle:b.add(0x18).readPointer().toString()};}
};
emit('probe_ready',{module:m.name,base:m.base.toString(),arch:Process.arch});
