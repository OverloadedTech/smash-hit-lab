import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {TransformControls} from 'three/addons/controls/TransformControls.js';

const $=id=>document.getElementById(id),host=$('viewport');
const scene=new THREE.Scene();scene.background=new THREE.Color(0x101722);
const camera=new THREE.PerspectiveCamera(65,1,.02,20000);camera.position.set(10,10,20);
const renderer=new THREE.WebGLRenderer({antialias:true});renderer.setPixelRatio(Math.min(devicePixelRatio,2));host.appendChild(renderer.domElement);
scene.add(new THREE.HemisphereLight(0xc7e9ff,0x39422d,2.3));const light=new THREE.DirectionalLight(0xffffff,2.5);light.position.set(5,12,20);scene.add(light);
const orbit=new OrbitControls(camera,renderer.domElement);orbit.mouseButtons.LEFT=null;orbit.mouseButtons.RIGHT=THREE.MOUSE.ROTATE;
const controls=new TransformControls(camera,renderer.domElement);scene.add(controls.getHelper());
const pivot=new THREE.Object3D();scene.add(pivot);controls.attach(pivot);controls.enabled=false;controls.getHelper().visible=false;
const world=new THREE.Group();scene.add(world);const selectionBoxes=new THREE.Group();scene.add(selectionBoxes);
let project=null,original=null,selected=new Set(),meshes=new Map(),history=[],future=[],dragStart=null,startPivot=null,gizmoBusy=false,busy=false;
const fields={};
for(const [key,label,initial] of [['position','Position',0],['rotation','Rotate °',0],['scale','Scale',1]]){
  const row=document.createElement('label'),name=document.createElement('span');name.textContent=label;row.append(name);fields[key]=[];
  for(const axis of ['X','Y','Z']){const input=document.createElement('input');input.type='number';input.step='.1';input.value=initial;input.setAttribute('aria-label',`${label} ${axis}`);row.append(input);fields[key].push(input);} $('transform').append(row);
}
const clone=value=>JSON.parse(JSON.stringify(value));
const status=(message,error=false)=>{$('status').textContent=message;$('status').classList.toggle('error',error);};
function object(key){return project?.objects.find(o=>o.key===key);}
function pose(o){return {position:[...o.position],quaternion:[...o.quaternion],scale:[...o.scale]};}
function capture(){return Object.fromEntries([...selected].map(key=>[key,pose(object(key))]));}
function remember(before){if(!Object.keys(before).length)return;history.push(before);if(history.length>50)history.shift();future=[];}
function restore(poses){for(const [key,p] of Object.entries(poses)){const o=object(key);if(o){Object.assign(o,clone(p));updateMesh(key);}}updateSelection();}
function updateMesh(key){const o=object(key),mesh=meshes.get(key);if(!mesh)return;mesh.position.fromArray(o.position);mesh.quaternion.fromArray(o.quaternion);mesh.scale.fromArray(o.scale);mesh.updateMatrixWorld(true);}
function bounds(){const b=new THREE.Box3();for(const key of selected){const m=meshes.get(key);if(m)b.expandByObject(m);}return b;}
function updateSelection(){
  while(selectionBoxes.children.length){const helper=selectionBoxes.children[0];helper.geometry.dispose();helper.material.dispose();selectionBoxes.remove(helper);}
  for(const key of selected){const mesh=meshes.get(key);if(mesh&&selectionBoxes.children.length<80)selectionBoxes.add(new THREE.BoxHelper(mesh,0x66ffd2));}
  const items=[...selected].map(object);$('selection').textContent=items.length?`${items.length} selected`:'No selection';
  const box=bounds();if(!gizmoBusy&&!box.isEmpty()){pivot.position.copy(box.getCenter(new THREE.Vector3()));pivot.quaternion.identity();pivot.scale.set(1,1,1);pivot.updateMatrixWorld(true);}
  controls.enabled=items.length>0;controls.getHelper().visible=items.length>0;
  const scaleOK=items.every(o=>o.detail?.scale_supported!==false);$('scale').disabled=!scaleOK;
  if(!scaleOK&&controls.mode==='scale')setMode('translate');
  $('selectionNote').textContent=items.length===1?`${items[0].type} · ${items[0].section}`:items.length?'Fields use the group center. Rotate and scale use the colored handles.':'';
  if(!scaleOK)$('selectionNote').textContent+=' · Scaling is unavailable for a body with native joints.';
  const p=items.length===1?new THREE.Vector3().fromArray(items[0].position):pivot.position;
  const q=items.length===1?new THREE.Quaternion().fromArray(items[0].quaternion):new THREE.Quaternion();
  const e=new THREE.Euler().setFromQuaternion(q,'YXZ'),s=items.length===1?items[0].scale:[1,1,1];
  for(const [key,values] of [['position',p.toArray()],['rotation',[e.x,e.y,e.z].map(THREE.MathUtils.radToDeg)],['scale',s]])fields[key].forEach((input,i)=>input.value=Number(values[i]).toFixed(3));
  $('detail').textContent=items.length===1?JSON.stringify({...items[0],geometry:items[0].geometry?{kind:items[0].geometry.kind,vertices:items[0].geometry.vertices.length,triangles:items[0].geometry.triangles.length}:null},null,2):items.map(o=>o.key).join('\n');
  for(const option of $('objects').options)option.selected=selected.has(option.value);
}
function setMode(mode){controls.setMode(mode);for(const name of ['translate','rotate','scale'])$(name).classList.toggle('active',name===mode);}
function list(){const q=$('filter').value.toLowerCase();$('objects').replaceChildren();for(const o of project?.objects||[]){if(!`${o.name} ${o.type} ${o.key} ${o.section}`.toLowerCase().includes(q))continue;const option=document.createElement('option');option.value=o.key;option.textContent=`${o.name||o.type} · ${o.key}`;$('objects').append(option);}}
function select(key,add=false){if(!add)selected.clear();if(key){if(add&&selected.has(key))selected.delete(key);else selected.add(key);}updateSelection();}
function load(data){
  if(data.format!=='mediocre-native-scene'||data.version!==1||!Array.isArray(data.objects))throw new Error('Choose a native scene exported by a current Lab APK.');
  const ids=new Set();for(const o of data.objects){if(ids.has(o.key))throw new Error('Duplicate object ID');ids.add(o.key);for(const [k,n] of [['position',3],['quaternion',4],['scale',3]])if(!Array.isArray(o[k])||o[k].length!==n||!o[k].every(Number.isFinite))throw new Error('Invalid object transform');}
  for(const m of world.children){m.geometry.dispose();m.material.dispose();}world.clear();meshes.clear();selected.clear();history=[];future=[];project=clone(data);original=clone(data);
  for(const o of project.objects){const data=o.geometry;if(!data?.triangles?.length)continue;const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(data.vertices.flat(),3));geometry.setIndex(data.triangles.flat());geometry.computeVertexNormals();
    const color=new THREE.Color().setHSL(o.type.includes('Static')?.53:.1,.3,.48);const mesh=new THREE.Mesh(geometry,new THREE.MeshStandardMaterial({color,roughness:.85,metalness:.1,side:THREE.DoubleSide}));mesh.userData.key=o.key;meshes.set(o.key,mesh);world.add(mesh);updateMesh(o.key);}
  camera.up.set(...(project.game==='pinout'?[0,0,1]:[0,1,0]));
  if(project.camera){camera.position.fromArray(project.camera.position);camera.quaternion.fromArray(project.camera.quaternion);orbit.target.copy(camera.position).add(new THREE.Vector3(0,0,-12).applyQuaternion(camera.quaternion));}else{const b=new THREE.Box3().setFromObject(world);orbit.target.copy(b.getCenter(new THREE.Vector3()));camera.position.copy(orbit.target).add(new THREE.Vector3(15,15,25));}
  orbit.update();list();updateSelection();$('sections').textContent=JSON.stringify(project.sections,null,2);
  const kind=project.objects.some(o=>o.geometry?.kind?.includes('collision triangles'))?'Native collision surfaces; game rendering is updated when edits are applied.':'Native rendered body triangles; textures and physics run in the game.';
  status(`${project.objects.length} native objects · ${meshes.size} triangle meshes\n${kind}`);
}
async function api(path,data){const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const value=await response.json();if(!response.ok)throw new Error(value.error||response.statusText);return value;}
async function task(fn){if(busy)return;busy=true;for(const id of ['connect','apply','saveGame'])$(id).disabled=true;try{await fn();}catch(e){status(e.message,true);}finally{busy=false;for(const id of ['connect','apply','saveGame'])$(id).disabled=false;}}
$('connect').onclick=()=>task(async()=>{status('Pausing and reading native geometry…');load(await api('/api/connect',{}));});
async function apply(save){if(!project||!selected.size)throw new Error('Select the objects to apply.');status('Applying native body and geometry changes…');const value=await api('/api/apply',{identity:{game:project.game,library_sha256:project.library_sha256,pid:project.pid,scene_epoch:project.scene_epoch},poses:capture(),save});status(`Applied ${selected.size} objects · world paused${save?' · saved for future runs':''}. Native undo count: ${value.undo_count}`);}
$('apply').onclick=()=>task(()=>apply(false));$('saveGame').onclick=()=>task(()=>apply(true));
$('open').onclick=()=>$('file').click();$('file').onchange=async()=>{try{load(JSON.parse(await $('file').files[0].text()));}catch(e){status(e.message,true);}$('file').value='';};
$('download').onclick=()=>{if(!project)return;const a=document.createElement('a'),url=URL.createObjectURL(new Blob([JSON.stringify(project)],{type:'application/json'}));a.href=url;a.download=`${project.game}-scene.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
$('all').onclick=()=>{selected=new Set((project?.objects||[]).filter(o=>o.editable).map(o=>o.key));updateSelection();};$('clear').onclick=()=>select(null);
$('filter').oninput=list;$('objects').onchange=()=>select($('objects').value,$('multi').checked);
for(const mode of ['translate','rotate','scale'])$(mode).onclick=()=>setMode(mode);
$('focus').onclick=()=>{const box=bounds();if(box.isEmpty())return;const c=box.getCenter(new THREE.Vector3()),size=box.getSize(new THREE.Vector3()).length();const direction=camera.position.clone().sub(orbit.target).normalize();orbit.target.copy(c);camera.position.copy(c).addScaledVector(direction,Math.max(size*1.3,1));orbit.update();};
function shift(axis,amount){if(!selected.size)return;const before=capture();for(const key of selected){object(key).position[axis]+=amount;updateMesh(key);}remember(before);updateSelection();}
for(let axis=0;axis<3;axis++)for(const sign of [-1,1]){const b=document.createElement('button');b.textContent=`${'XYZ'[axis]} ${sign<0?'−':'+'}`;b.onclick=()=>{const step=Number($('step').value);if(Number.isFinite(step)&&step>0)shift(axis,step*sign);};$('steps').append(b);}
$('applyFields').onclick=()=>{try{if(!selected.size)return;const values=Object.fromEntries(Object.entries(fields).map(([key,inputs])=>[key,inputs.map(i=>Number(i.value))]));if(!Object.values(values).flat().every(Number.isFinite)||Math.min(...values.scale)<.02)throw new Error('Use finite coordinates and positive scales of at least 0.02.');const before=capture();if(selected.size===1){const o=object([...selected][0]);if(o.detail?.scale_supported===false&&values.scale.some((v,i)=>Math.abs(v-o.scale[i])>.0001))throw new Error('Scaling this joined body requires a native rebuild.');o.position=values.position;o.quaternion=new THREE.Quaternion().setFromEuler(new THREE.Euler(...values.rotation.map(THREE.MathUtils.degToRad),'YXZ')).toArray();o.scale=values.scale;updateMesh(o.key);}else{const delta=new THREE.Vector3().fromArray(values.position).sub(pivot.position);for(const key of selected){object(key).position=new THREE.Vector3().fromArray(object(key).position).add(delta).toArray();updateMesh(key);}}remember(before);updateSelection();}catch(e){status(e.message,true);}};
$('reset').onclick=()=>{const before=capture();restore(Object.fromEntries([...selected].map(key=>[key,pose(original.objects.find(o=>o.key===key))])));remember(before);};
function undo(from,to){if(!from.length)return;const target=from.pop(),current={};for(const key of Object.keys(target))current[key]=pose(object(key));to.push(current);restore(target);}
$('undo').onclick=()=>undo(history,future);$('redo').onclick=()=>undo(future,history);
controls.addEventListener('dragging-changed',event=>{gizmoBusy=event.value;orbit.enabled=!event.value;if(event.value){dragStart=capture();startPivot={position:pivot.position.clone(),quaternion:pivot.quaternion.clone(),scale:pivot.scale.clone()};}else if(dragStart){remember(dragStart);dragStart=null;updateSelection();}});
controls.addEventListener('objectChange',()=>{if(!dragStart)return;const center=startPivot.position,delta=pivot.position.clone().sub(center),rotation=pivot.quaternion.clone().multiply(startPivot.quaternion.clone().invert()),scale=pivot.scale.clone().divide(startPivot.scale);
  for(const [key,p] of Object.entries(dragStart)){const o=object(key);o.position=new THREE.Vector3().fromArray(p.position).sub(center).multiply(scale).applyQuaternion(rotation).add(center).add(delta).toArray();o.quaternion=rotation.clone().multiply(new THREE.Quaternion().fromArray(p.quaternion)).normalize().toArray();o.scale=new THREE.Vector3().fromArray(p.scale).multiply(scale).toArray();if(Math.min(...o.scale)<.02)o.scale=o.scale.map(v=>Math.max(.02,v));updateMesh(key);}updateSelection();});
let down=null;renderer.domElement.addEventListener('pointerdown',event=>{if(event.button===0)down=[event.clientX,event.clientY];});renderer.domElement.addEventListener('pointerup',event=>{if(!down||event.button!==0)return;const start=down;down=null;if(gizmoBusy||controls.axis||Math.hypot(event.clientX-start[0],event.clientY-start[1])>4)return;const rect=renderer.domElement.getBoundingClientRect(),ray=new THREE.Raycaster();ray.setFromCamera(new THREE.Vector2((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1),camera);const hit=ray.intersectObjects(world.children)[0];select(hit?.object.userData.key,event.ctrlKey||event.shiftKey||$('multi').checked);});
$('fov').onchange=()=>{camera.fov=Math.max(20,Math.min(140,Number($('fov').value)||65));camera.updateProjectionMatrix();};
new ResizeObserver(()=>{const w=host.clientWidth,h=host.clientHeight;camera.aspect=w/h;camera.updateProjectionMatrix();renderer.setSize(w,h);}).observe(host);
renderer.setAnimationLoop(()=>{orbit.update();renderer.render(scene,camera);});setMode('translate');
fetch('/api/config').then(r=>r.json()).then(c=>$('title').textContent=`${c.game==='pinout'?'PinOut':'Granny Smith'} · native scene editor`);
window.mediocreEditor={get project(){return project;},get selected(){return [...selected];},meshes,camera,renderer,controls,load,select};
