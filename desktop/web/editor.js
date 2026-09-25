import * as THREE from 'three';
import {
  OrbitControls
} from 'three/addons/controls/OrbitControls.js';
import {
  TransformControls
} from 'three/addons/controls/TransformControls.js';
import {normalizeSelection, editable, sourcePose, selectedPose, translatedPoses, objectBounds, combinedBounds} from './selection.js';

const $ = s => document.querySelector(s),
  $$ = s => [...document.querySelectorAll(s)];
const canvas = $('#world'),
  viewport = $('#viewport'),
  status = $('#status');
const scene = new THREE.Scene();
scene.background = new THREE.Color('#25343d');
const camera = new THREE.PerspectiveCamera(65, 1, .03, 100000);
camera.position.set(0, 1, 4);
const renderer = new THREE.WebGLRenderer({
  canvas,
  antialias: true
});
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.outputColorSpace = THREE.LinearSRGBColorSpace;
const orbit = new OrbitControls(camera, canvas);
orbit.target.set(0, 1, -16);
orbit.enableDamping = true;
orbit.mouseButtons = {
  LEFT: null,
  MIDDLE: THREE.MOUSE.PAN,
  RIGHT: THREE.MOUSE.ROTATE
};
const gizmo = new TransformControls(camera, canvas);
gizmo.setSpace('world');
scene.add(gizmo.getHelper());
const world = new THREE.Group();
scene.add(world);
const selectionBounds = new THREE.Box3Helper(new THREE.Box3(), 0x73edce);
selectionBounds.visible = false;
scene.add(selectionBounds);
const proxy = new THREE.Object3D();
proxy.rotation.order = 'YXZ';
const groupProxy = new THREE.Object3D();
scene.add(groupProxy);
const memberBounds = [];
const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
const state = {
  catalog: null,
  instances: [],
  selection: null,
  selections: [],
  undo: [],
  redo: [],
  loading: false,
  dirty: false,
  tool: 'translate'
};
const assets = new Map(),
  keys = new Set();
let material, idCounter = 0,
  dragStart = null,
  groupDrag = null,
  movement = null,
  holdTimer = null,
  orbitRestore = true;
const clone = x => JSON.parse(JSON.stringify(x));

function tell(text) {
  status.textContent = text;
}

function dirty(value = true) {
  state.dirty = value;
  $('#saved-state').textContent = value ? 'Unsaved changes' : 'Saved';
}
async function request(path, data) {
  const response = await fetch(path, data === undefined ? {} : {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(data)
  });
  if (!response.ok) {
    let error;
    try {
      error = (await response.json()).error
    } catch {
      error = response.statusText
    }
    throw Error(error)
  }
  return response;
}

function guarded(fn) {
  return async (...args) => {
    try {
      await fn(...args)
    } catch (e) {
      console.error(e);
      tell(e.message);
    }
  }
}

function project() {
  return {
    format: 'smash-hit-lab-project-v1',
    apk_sha256: state.catalog.apk_sha256,
    name: $('#project-name').value,
    segments: state.instances.map(i => clone(i.item))
  };
}

function selectionRefs() {
  return state.selections.map(s => ({id: s.instance.item.id, ordinal: s.ordinal}));
}

function historyState() {
  return {project: project(), selection: selectionRefs()};
}

function remember(before = historyState()) {
  state.undo.push(before);
  if (state.undo.length > 50) state.undo.shift();
  state.redo = [];
  dirty();
  historyButtons();
}

function historyButtons() {
  $('#undo').disabled = !state.undo.length || state.loading;
  $('#redo').disabled = !state.redo.length || state.loading;
}

function uniqueId() {
  return 'segment-' + Date.now().toString(36) + '-' + (++idCounter);
}
async function source(path) {
  if (!assets.has(path)) assets.set(path, (async () => {
    const [meta, buffer] = await Promise.all([(await request('/api/segment?path=' +
      encodeURIComponent(path))).json(), (await request('/api/mesh?path=' +
      encodeURIComponent(path))).arrayBuffer()]);
    const view = new DataView(buffer),
      n = view.getUint32(0, true),
      p = new Float32Array(n * 3),
      uv = new Float32Array(n * 2),
      colors = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      const o = 4 + i * 24;
      for (let j = 0; j < 3; j++) p[i * 3 + j] = view.getFloat32(o + j * 4, true);
      uv[i * 2] = view.getFloat32(o + 12, true);
      uv[i * 2 + 1] = view.getFloat32(o + 16, true);
      const a = view.getUint8(o + 23) / 255,
        light = 2 * (1 - (1 - a) ** 2);
      for (let j = 0; j < 3; j++) colors[i * 3 + j] = Math.min(1, view.getUint8(o + 20 + j) / 255 *
        light);
    }
    const nt = view.getUint32(4 + n * 24, true),
      indices = new Uint32Array(buffer.slice(8 + n * 24, 8 + n * 24 + nt * 12));
    return {
      meta,
      p,
      uv,
      colors,
      indices
    };
  })());
  return assets.get(path);
}

function setPose(object, item) {
  object.position.fromArray(item.position);
  object.rotation.set(...item.rotation.map(THREE.MathUtils.degToRad), 'YXZ');
  object.scale.fromArray(item.scale);
  object.updateMatrixWorld(true);
}

function pose(object) {
  return {
    position: object.position.toArray(),
    rotation: [object.rotation.x, object.rotation.y, object.rotation.z].map(THREE.MathUtils.radToDeg),
    scale: object.scale.toArray()
  };
}

function editDefault(instance, ordinal) {
  return {
    position: instance.data.meta.mapping.boxes[ordinal].position.slice(),
    rotation: [0, 0, 0],
    scale: [1, 1, 1]
  };
}

function updateBox(instance, ordinal, flush = true) {
  const box = instance.data.meta.mapping.boxes[ordinal],
    edit = instance.item.edits[String(ordinal)] || editDefault(instance, ordinal);
  const transform = new THREE.Matrix4().compose(new THREE.Vector3().fromArray(edit.position), new THREE
    .Quaternion().setFromEuler(new THREE.Euler(...edit.rotation.map(THREE.MathUtils.degToRad), 'YXZ')),
    new THREE.Vector3().fromArray(edit.scale));
  const array = instance.mesh.geometry.attributes.position.array,
    original = instance.data.p,
    p = new THREE.Vector3(),
    center = new THREE.Vector3().fromArray(box.position);
  for (const q of box.quads)
    for (let j = 0; j < 4; j++) {
      const i = q * 4 + j;
      p.fromArray(original, i * 3).sub(center).applyMatrix4(transform);
      p.toArray(array, i * 3);
    }
  if (flush) flushMesh(instance);
}
function flushMesh(instance) {
  instance.mesh.geometry.attributes.position.needsUpdate = true;
  instance.mesh.geometry.computeBoundingSphere();
  instance.mesh.geometry.computeBoundingBox();
}
async function add(item, select = true) {
  const data = await source(item.source),
    geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(data.p.slice(), 3));
  geometry.setAttribute('uv', new THREE.BufferAttribute(data.uv, 2));
  geometry.setAttribute('color', new THREE.BufferAttribute(data.colors, 3));
  geometry.setIndex(new THREE.BufferAttribute(data.indices, 1));
  geometry.computeBoundingBox();
  geometry.computeBoundingSphere();
  const group = new THREE.Group(),
    mesh = new THREE.Mesh(geometry, material);
  group.name = item.source;
  group.rotation.order = 'YXZ';
  group.add(mesh);
  world.add(group);
  setPose(group, item);
  const anchorPositions = [];
  for (const r of data.meta.records) {
    const p = (r.attributes.pos || '0 0 0').split(/\s+/).map(Number);
    if (p.length === 3 && p.every(Number.isFinite)) anchorPositions.push(...p);
  }
  const anchorGeo = new THREE.BufferGeometry();
  anchorGeo.setAttribute('position', new THREE.Float32BufferAttribute(anchorPositions, 3));
  const anchors = new THREE.Points(anchorGeo, new THREE.PointsMaterial({
    color: 0xffb778,
    size: .2,
    sizeAttenuation: true,
    depthTest: false
  }));
  anchors.visible = $('#markers').checked;
  group.add(anchors);
  const instance = {
    item: clone(item),
    data,
    group,
    mesh,
    anchors
  };
  mesh.userData.instance = instance;
  state.instances.push(instance);
  for (const key of Object.keys(item.edits)) updateBox(instance, Number(key), false);
  if (Object.keys(item.edits).length) flushMesh(instance);
  outline();
  if (select) selectObject(instance, null);
  return instance;
}
async function addSource(path) {
  if (state.loading) return;
  state.loading = true;
  try {
    const before = historyState();
    tell('Loading ' + path + '…');
    const z = state.instances.reduce((v, i) => Math.min(v, i.item.position[2] - i.data.meta.length * i.item
      .scale[2]), 0);
    await add({
      id: uniqueId(),
      source: path,
      position: [0, 0, z],
      rotation: [0, 0, 0],
      scale: [1, 1, 1],
      edits: {}
    });
    remember(before);
    tell('Added actual segment ' + path);
  } finally {
    state.loading = false;
    refreshSelection();
  }
}

function clear() {
  selectObject(null, null);
  for (const i of state.instances) {
    i.mesh.geometry.dispose();
    i.anchors.geometry.dispose();
    i.anchors.material.dispose();
    world.remove(i.group);
  }
  state.instances = [];
  outline();
}
async function loadProject(data, validate = true, selection = null) {
  if (validate) data = await (await request('/api/validate', data)).json();
  state.loading = true;
  clear();
  $('#project-name').value = data.name;
  try {
    for (let n = 0; n < data.segments.length; n++) {
      tell(`Loading ${n+1}/${data.segments.length} segments…`);
      await add(data.segments[n], false);
    }
    if (selection) setSelection(selection.map(ref => ({instance: state.instances.find(i => i.item.id === ref.id), ordinal: ref.ordinal})).filter(s => s.instance));
    else if (state.instances.length) selectObject(state.instances[0], null);
    tell(`Loaded ${data.segments.length} segment instances`);
  } finally {
    state.loading = false;
    refreshSelection();
  }
}

function outline() {
  const container = $('#instances');
  container.replaceChildren();
  const selectedInstances = new Map();
  for (const s of state.selections) selectedInstances.set(s.instance, s.ordinal === null || selectedInstances.get(s.instance) === true);
  for (const i of state.instances) {
    const b = document.createElement('button');
    b.textContent = `${i.item.source} · Z ${i.item.position[2].toFixed(1)}`;
    b.dataset.instance = i.item.id;
    if (selectedInstances.has(i)) b.className = selectedInstances.get(i) ? 'selected' : 'partial';
    b.onclick = e => selectObject(i, null, e.ctrlKey || e.metaKey || e.shiftKey || $('#multi-select').checked);
    container.append(b);
  }
  $('#view-stats').textContent =
    `${state.instances.length} segments · ${state.instances.reduce((n,i)=>n+i.data.indices.length/3,0).toLocaleString()} triangles`;
}

function selectObject(instance, ordinal, additive = false) {
  if (!instance) { if (!additive) setSelection([]); return; }
  const target = {instance, ordinal};
  const exists = state.selections.some(s => s.instance === instance && s.ordinal === ordinal);
  setSelection(additive ? (exists ? state.selections.filter(s => s.instance !== instance || s.ordinal !== ordinal)
    : [...state.selections, target]) : [target]);
}

function setSelection(items) {
  finishMovement();
  state.selections = normalizeSelection(items);
  state.selection = state.selections.at(-1) || null;
  $('#runtime-target').replaceChildren();
  state.runtimePid = null;
  $('#apply-runtime').disabled = true;
  $('#runtime-result').textContent = '';
  refreshSelection();
}

function refreshBounds() {
  selectionBounds.visible = state.selections.length > 0;
  selectionBounds.box.copy(combinedBounds(state.selections));
  const count = state.selections.length > 1 ? Math.min(state.selections.length, 64) : 0;
  while (memberBounds.length < count) {
    const helper = new THREE.Box3Helper(new THREE.Box3(), 0xffd166);
    scene.add(helper);
    memberBounds.push(helper);
  }
  memberBounds.forEach((helper, i) => {
    helper.visible = i < count;
    if (helper.visible) objectBounds(state.selections[i], helper.box);
  });
}

function syncGizmo() {
  gizmo.detach();
  if (proxy.parent) proxy.parent.remove(proxy);
  if (!state.selection) return;
  const multiple = state.selections.length > 1;
  if (multiple) {
    groupProxy.position.copy(selectionBounds.box.getCenter(new THREE.Vector3()));
    groupProxy.quaternion.identity(); groupProxy.scale.set(1, 1, 1);
    groupProxy.updateMatrixWorld(true);
    if (state.tool !== 'translate') setTool('translate');
    if (state.selections.every(editable)) gizmo.attach(groupProxy);
  } else {
    const s = state.selection;
    if (s.ordinal === null) gizmo.attach(s.instance.group);
    else {
      setPose(proxy, selectedPose(s));
      s.instance.group.add(proxy);
      if (editable(s)) gizmo.attach(proxy);
    }
  }
  gizmo.setSpace(multiple ? 'world' : $('#move-space').value);
  updateSnap();
}

function refreshSelection() {
  const s = state.selection, multiple = state.selections.length > 1;
  const canEdit = !!s && state.selections.every(editable) && !state.loading;
  const select = $('#box-select');
  select.replaceChildren(new Option('Whole segment', ''));
  select.disabled = !s || state.loading;
  $('#select-boxes').disabled = !state.instances.length || state.loading;
  $('#select-segments').disabled = !state.instances.length || state.loading;
  $('#clear-selection').disabled = !s;
  $('#focus').disabled = !s;
  $('#apply').disabled = $('#reset').disabled = !canEdit;
  $('#duplicate').disabled = $('#delete').disabled = !canEdit || !state.selections.every(s => s.ordinal === null);
  $('#duplicate').title = $('#delete').title = 'Select whole segments for this action';
  for (const button of $$('[data-nudge]')) button.disabled = !canEdit;
  for (const button of $$('[data-tool]')) button.disabled = multiple && button.dataset.tool !== 'translate';
  $('#move-space').disabled = multiple;
  for (const input of $$('#transform-fields input'))
    input.disabled = !canEdit || (multiple && input.closest('[data-vector]').dataset.vector !== 'position');
  $('#apply').textContent = multiple ? 'Move group to position' : 'Apply transform';
  $('#position-label').textContent = multiple ? 'Group center in world · X / Y / Z'
    : s?.ordinal === null ? 'World position X / Y / Z' : 'Position in segment · X / Y / Z';
  $('#rotation-label').textContent = multiple ? 'Rotation · edit one object at a time' : 'Rotation X / Y / Z (degrees)';
  const n = state.selections.length, count = state.selections.filter(editable).length;
  $('#selection-count').textContent = n ? `${n} selected · ${count} editable · ${new Set(state.selections.map(s => s.instance)).size} segment(s)` : 'Nothing selected';
  if (!s) {
    $('#selection-name').textContent = 'Select a segment or click its geometry.';
    $('#properties').textContent = ''; $('#xml').value = '';
  } else {
    const {instance, ordinal} = s;
    for (const b of instance.data.meta.mapping.boxes) select.add(new Option(
      `Box ${b.ordinal} · XML child ${b.source_index}${b.editable ? '' : ' · inspect only'}`, String(b.ordinal)));
    select.value = ordinal === null ? '' : String(ordinal);
    const box = ordinal === null ? null : instance.data.meta.mapping.boxes[ordinal];
    $('#selection-name').textContent = (multiple ? `Primary of ${n}: ` : '') + instance.item.source +
      (box ? ` / box ${ordinal}` : ' / whole segment');
    $('#xml').value = instance.data.meta.xml;
    const details = box ? {
      source: instance.data.meta.mapping.source, xml_child: box.source_index,
      half_extents: box.half_extents, editable: box.editable, original_attributes: box.attributes
    } : {
      instance: instance.item.id, source: instance.data.meta.mapping.source,
      size: instance.data.meta.size, vertices: instance.data.p.length / 3,
      triangles: instance.data.indices.length / 3, authored_objects: instance.data.meta.records
    };
    if (multiple) details.selection = selectionRefs();
    $('#properties').textContent = JSON.stringify(details, null, 2);
  }
  refreshBounds(); syncGizmo(); fields(); outline(); historyButtons();
}

function selectBoxes() {
  const scope = $('#selection-scope').value;
  const instances = scope === 'project' ? state.instances : state.selection ? [state.selection.instance] : [];
  if (!instances.length) throw Error('Choose a segment or use Whole project scope');
  let skipped = 0;
  const items = [];
  for (const instance of instances) for (const box of instance.data.meta.mapping.boxes) {
    if (box.editable) items.push({instance, ordinal: box.ordinal}); else skipped++;
  }
  setSelection(items);
  tell(`Selected ${items.length} editable boxes in ${instances.length} segment(s) · ${skipped} inspect-only boxes skipped`);
}
$('#select-boxes').onclick = guarded(selectBoxes);
$('#select-segments').onclick = () => setSelection(state.instances.map(instance => ({instance, ordinal: null})));
$('#clear-selection').onclick = () => setSelection([]);

function selectionPose() {
  const s = state.selection;
  return s ? pose(state.selections.length > 1 ? groupProxy : s.ordinal === null ? s.instance.group : proxy) : null;
}

function fields() {
  const value = selectionPose();
  if (!value) return;
  for (const key of ['position', 'rotation', 'scale']) $$(`[data-vector="${key}"] input`).forEach((field,
    i) => field.value = value[key][i].toFixed(3));
}

function applyPoses(items, values, reset = false) {
  // Preflight the entire selection before changing any vertex or instance.
  if (state.loading) throw Error('Wait for the project to finish loading');
  values.forEach((value, i) => {
    if (!editable(items[i])) throw Error('Inspect-only boxes cannot be edited');
    for (const key of ['position', 'rotation', 'scale'])
      if (value[key].length !== 3 || !value[key].every(v => Number.isFinite(v) && Math.abs(v) <= 1e7))
        throw Error('Enter finite values within the supported coordinate range');
    if (value.scale.some(v => v < .01 || v > 100)) throw Error('Scale must be between 0.01 and 100');
  });
  const changed = new Set();
  items.forEach((s, i) => {
    if (s.ordinal === null) {
      Object.assign(s.instance.item, values[i]);
      setPose(s.instance.group, s.instance.item);
    } else {
      if (reset) delete s.instance.item.edits[String(s.ordinal)];
      else s.instance.item.edits[String(s.ordinal)] = values[i];
      updateBox(s.instance, s.ordinal, false);
      changed.add(s.instance);
    }
  });
  changed.forEach(flushMesh);
  refreshBounds(); dirty(); outline();
}

function commitSelection() {
  const s = state.selection;
  if (!s || state.selections.length !== 1) return;
  const object = s.ordinal === null ? s.instance.group : proxy;
  object.scale.clampScalar(.01, 100);
  object.updateMatrixWorld(true);
  applyPoses([s], [pose(object)]);
}

function moveStep() {
  const value = Number($('#move-step').value);
  if (!Number.isFinite(value) || value < .001 || value > 100000) throw Error('Move step must be between 0.001 and 100000');
  return value;
}

function updateSnap() {
  const value = Number($('#move-step').value);
  const valid = Number.isFinite(value) && value >= .001 && value <= 100000;
  gizmo.setTranslationSnap($('#move-snap').checked && valid ? value : null);
  if (!valid) tell('Move step must be between 0.001 and 100000');
}
$('#move-step').onchange = guarded(updateSnap);
$('#move-snap').onchange = guarded(updateSnap);
$('#move-space').onchange = () => gizmo.setSpace(state.selections.length > 1 ? 'world' : $('#move-space').value);

function beginMovement(key) {
  finishMovement();
  if (!state.selections.length) throw Error('Select an object first');
  if (state.loading || gizmo.dragging) throw Error('Finish the current operation first');
  if (!state.selections.every(editable)) throw Error('Select editable objects to move');
  movement = {key, before: historyState(), items: state.selections.slice(),
    poses: state.selections.map(selectedPose), delta: new THREE.Vector3()};
}
function advanceMovement(axis, amount) {
  if (!movement) return;
  const delta = movement.delta.clone();
  delta.setComponent(axis, delta.getComponent(axis) + amount);
  const values = translatedPoses(movement.items, delta, movement.poses);
  applyPoses(movement.items, values);
  movement.delta.copy(delta);
  syncGizmo(); fields();
  tell(`Moved ${movement.items.length} object(s) · world delta ${delta.toArray().map(v => v.toFixed(2)).join(', ')}`);
}
function finishMovement() {
  clearTimeout(holdTimer); holdTimer = null;
  if (!movement) return;
  const before = movement.before;
  movement = null;
  if (JSON.stringify(before.project) !== JSON.stringify(project())) remember(before);
}
function nudge(axis, sign, multiplier = 1) {
  const amount = sign * moveStep() * multiplier;
  beginMovement('click');
  try { advanceMovement(axis, amount); } finally { finishMovement(); }
}
for (const button of $$('[data-nudge]')) {
  const [axis, sign] = button.dataset.nudge.split(',').map(Number);
  let repeated = false;
  button.onpointerdown = e => {
    if (e.button !== 0 || button.disabled) return;
    repeated = false;
    button.setPointerCapture(e.pointerId);
    holdTimer = setTimeout(guarded(() => {
      const amount = sign * moveStep();
      beginMovement('button'); repeated = true;
      const repeat = () => {
        if (!movement || movement.key !== 'button') return;
        try { advanceMovement(axis, amount); holdTimer = setTimeout(repeat, 120); }
        catch (error) { finishMovement(); tell(error.message); }
      };
      repeat();
    }), 380);
  };
  button.onpointerup = () => finishMovement();
  button.onpointercancel = () => { repeated = true; finishMovement(); };
  button.onclick = guarded(e => {
    if (repeated && e.detail !== 0) { repeated = false; return; }
    nudge(axis, sign, e.shiftKey ? 10 : e.altKey ? .1 : 1);
  });
}

function applyFields() {
  const s = state.selection;
  if (!s) return;
  const value = {};
  for (const key of ['position', 'rotation', 'scale']) {
    const inputs = $$(`[data-vector="${key}"] input`);
    if (inputs.some(x => !x.value.trim())) throw Error('Complete all transform values');
    value[key] = inputs.map(x => Number(x.value));
    if (!value[key].every(Number.isFinite)) throw Error('Enter finite numbers');
  }
  const before = historyState();
  if (state.selections.length > 1) {
    const delta = new THREE.Vector3().fromArray(value.position).sub(groupProxy.position);
    applyPoses(state.selections, translatedPoses(state.selections, delta));
  } else applyPoses([s], [value]);
  if (JSON.stringify(before.project) !== JSON.stringify(project())) remember(before);
  syncGizmo(); fields();
  tell(`Updated ${state.selections.length} object(s) in actual mesh geometry`);
}
$('#apply').onclick = guarded(applyFields);
$('#box-select').onchange = () => {
  const s = state.selection;
  if (s) selectObject(s.instance, $('#box-select').value === '' ? null : Number($('#box-select').value), $('#multi-select').checked);
};
$('#reset').onclick = guarded(() => {
  if (!state.selections.length) return;
  const before = historyState();
  applyPoses(state.selections, state.selections.map(sourcePose), true);
  if (JSON.stringify(before.project) !== JSON.stringify(project())) remember(before);
  refreshSelection();
  tell('Reset selected transforms to original source coordinates');
});
$('#duplicate').onclick = guarded(async () => {
  if (state.loading || !state.selections.length || !state.selections.every(s => s.ordinal === null)) return;
  const before = historyState(), originals = state.selections.slice(), copies = [];
  state.loading = true;
  try {
    for (const s of originals) {
      const item = clone(s.instance.item);
      item.id = uniqueId(); item.position[0] += 2;
      copies.push({instance: await add(item, false), ordinal: null});
    }
    setSelection(copies);
    remember(before);
    tell(`Duplicated ${copies.length} segment(s), offset 2 units along world X`);
  } finally { state.loading = false; refreshSelection(); }
});
$('#delete').onclick = guarded(() => {
  if (state.loading || !state.selections.length || !state.selections.every(s => s.ordinal === null)) return;
  const before = historyState(), removed = new Set(state.selections.map(s => s.instance));
  setSelection([]);
  for (const instance of removed) {
    world.remove(instance.group);
    instance.mesh.geometry.dispose(); instance.anchors.geometry.dispose(); instance.anchors.material.dispose();
  }
  state.instances = state.instances.filter(i => !removed.has(i));
  remember(before); refreshSelection();
  tell(`Removed ${removed.size} segment(s); Undo restores them`);
});
$('#restitch').onclick = () => {
  if (state.loading) return;
  remember();
  let z = 0;
  for (const i of state.instances) {
    i.item.position = [0, 0, z];
    i.item.rotation = [0, 0, 0];
    setPose(i.group, i.item);
    z -= i.data.meta.length * i.item.scale[2];
  }
  refreshSelection();
  tell('Placed this sequence end to end along negative Z');
};
async function historyMove(from, to) {
  if (state.loading) return;
  finishMovement();
  if (!from.length) return;
  const next = from.pop();
  to.push(historyState());
  await loadProject(next.project, false, next.selection);
  dirty(); historyButtons();
}
$('#undo').onclick = guarded(() => historyMove(state.undo, state.redo));
$('#redo').onclick = guarded(() => historyMove(state.redo, state.undo));
function setTool(tool) {
  if (state.selections.length > 1 && tool !== 'translate') return;
  state.tool = tool;
  $$('[data-tool]').forEach(x => x.classList.toggle('active', x.dataset.tool === tool));
  gizmo.setMode(tool);
}
for (const b of $$('[data-tool]')) b.onclick = () => setTool(b.dataset.tool);
gizmo.addEventListener('dragging-changed', e => {
  if (e.value) {
    finishMovement();
    dragStart = historyState();
    groupDrag = state.selections.length > 1 ? {pivot: groupProxy.position.clone(), poses: state.selections.map(selectedPose)} : null;
    orbitRestore = orbit.enabled; orbit.enabled = false;
  } else {
    orbit.enabled = orbitRestore;
    if (dragStart && JSON.stringify(dragStart.project) !== JSON.stringify(project())) remember(dragStart);
    dragStart = groupDrag = null;
  }
});
gizmo.addEventListener('objectChange', () => {
  try {
    if (groupDrag) {
      const delta = groupProxy.position.clone().sub(groupDrag.pivot);
      applyPoses(state.selections, translatedPoses(state.selections, delta, groupDrag.poses));
    } else commitSelection();
    fields();
  } catch (error) {
    if (groupDrag) groupProxy.position.copy(combinedBounds(state.selections).getCenter(new THREE.Vector3()));
    else if (state.selection) setPose(state.selection.ordinal === null ? state.selection.instance.group : proxy, selectedPose(state.selection));
    fields(); tell(error.message);
  }
});

function focus() {
  const s = state.selection;
  if (!s) return;
  const box = combinedBounds(state.selections),
    center = box.getCenter(new THREE.Vector3()),
    size = box.getSize(new THREE.Vector3()).length();
  orbit.target.copy(center);
  camera.position.copy(center).add(new THREE.Vector3(.35, .25, 1).normalize().multiplyScalar(Math.max(3,
    size * .65)));
  camera.lookAt(center);
}
$('#focus').onclick = focus;
let pointerDown;
canvas.addEventListener('pointerdown', e => {
  if (e.button === 0) pointerDown = {
    x: e.clientX,
    y: e.clientY,
    axis: gizmo.axis
  };
});
canvas.addEventListener('pointerup', e => {
  if (e.button !== 0 || !pointerDown || pointerDown.axis || gizmo.dragging) return;
  const d = pointerDown;
  pointerDown = null;
  if (Math.hypot(d.x - e.clientX, d.y - e.clientY) > 5) return;
  const rect = canvas.getBoundingClientRect();
  pointer.set((e.clientX - rect.left) / rect.width * 2 - 1, -(e.clientY - rect.top) / rect.height * 2 +
  1);
  raycaster.setFromCamera(pointer, camera);
  const hit = raycaster.intersectObjects(state.instances.map(i => i.mesh), false)[0];
  const additive = e.ctrlKey || e.metaKey || e.shiftKey || $('#multi-select').checked;
  if (!hit) { if (!additive) setSelection([]); return; }
  const i = hit.object.userData.instance,
    vertex = i.data.indices[hit.faceIndex * 3],
    owner = i.data.meta.mapping.owners[Math.floor(vertex / 4)];
  selectObject(i, owner >= 0 ? owner : null, additive);
});
let looking = false,
  lastMouse;
canvas.addEventListener('contextmenu', e => e.preventDefault());
canvas.addEventListener('pointerdown', e => {
  if (e.button === 2 && $('#flight').checked) {
    looking = true;
    lastMouse = [e.clientX, e.clientY];
    canvas.setPointerCapture(e.pointerId);
  }
});
canvas.addEventListener('pointermove', e => {
  if (!looking || gizmo.dragging) return;
  const euler = new THREE.Euler().setFromQuaternion(camera.quaternion, 'YXZ');
  euler.y -= (e.clientX - lastMouse[0]) * .003;
  euler.x = Math.max(-Math.PI * .499, Math.min(Math.PI * .499, euler.x - (e.clientY - lastMouse[1]) *
    .003));
  camera.quaternion.setFromEuler(euler);
  lastMouse = [e.clientX, e.clientY];
});
canvas.addEventListener('pointerup', e => {
  if (e.button === 2) looking = false;
});
$('#flight').onchange = () => {
  orbit.enabled = !$('#flight').checked;
  if (orbit.enabled) orbit.target.copy(camera.position).add(camera.getWorldDirection(new THREE.Vector3())
    .multiplyScalar(10));
};
$('#markers').onchange = () => state.instances.forEach(i => i.anchors.visible = $('#markers').checked);
window.addEventListener('keydown', guarded(e => {
  if (e.target.matches('input,textarea,select,[contenteditable]')) return;
  if ((e.ctrlKey || e.metaKey) && ['KeyZ', 'KeyY', 'KeyA'].includes(e.code)) {
    e.preventDefault();
    if (e.repeat) return;
    if (e.code === 'KeyA') selectBoxes();
    else $(e.code === 'KeyY' || e.shiftKey ? '#redo' : '#undo').click();
    return;
  }
  if (e.code === 'Escape') { setSelection([]); return; }
  const direction = {ArrowLeft: [0, -1], ArrowRight: [0, 1], ArrowUp: [2, -1], ArrowDown: [2, 1], PageUp: [1, 1], PageDown: [1, -1]}[e.code];
  if (direction) {
    e.preventDefault();
    const amount = direction[1] * moveStep() * (e.shiftKey ? 10 : e.altKey ? .1 : 1);
    if (!movement || movement.key !== e.code) beginMovement(e.code);
    advanceMovement(direction[0], amount);
    return;
  }
  keys.add(e.code);
  if (e.code === 'KeyF') {
    focus();
    e.preventDefault();
  }
  if (!$('#flight').checked && ['KeyG', 'KeyR', 'KeyS'].includes(e.code)) $(
    `[data-tool="${{KeyG:'translate',KeyR:'rotate',KeyS:'scale'}[e.code]}"]`).click();
}));
window.addEventListener('keyup', e => {
  keys.delete(e.code);
  if (movement?.key === e.code) finishMovement();
});
window.addEventListener('blur', () => { keys.clear(); looking = false; finishMovement(); });

function download(blob, name) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 10000);
}
$('#save').onclick = guarded(async () => {
  const p = project(),
    name = (p.name.replace(/[^a-z0-9_-]+/gi, '-').replace(/^-+/, '') || 'project') + '.shlab.json';
  await request('/api/save', {
    filename: name,
    project: p
  });
  download(new Blob([JSON.stringify(p, null, 2)], {
    type: 'application/json'
  }), name);
  dirty(false);
  tell('Saved locally to desktop/projects/' + name + ' and downloaded a copy');
});
$('#project-name').oninput = () => dirty();
$('#open').onclick = () => $('#project-file').click();
$('#project-file').onchange = guarded(async () => {
  const file = $('#project-file').files[0];
  if (!file) return;
  let p;
  if (file.name.endsWith('.glb')) {
    const data = await file.arrayBuffer(),
      view = new DataView(data);
    if (view.getUint32(0, true) !== 0x46546c67) throw Error('Invalid GLB');
    p = JSON.parse(new TextDecoder().decode(data.slice(20, 20 + view.getUint32(12, true)))).extras
      ?.shlab_project;
    if (!p) throw Error('This GLB has no editable Smash Hit Lab project metadata');
  } else p = JSON.parse(await file.text());
  const before = historyState();
  await loadProject(p);
  remember(before);
  dirty(false);
  $('#project-file').value = '';
});
async function exportProject(p, filename) {
  tell('Building a single GLB with actual geometry and an embedded tile atlas…');
  const response = await request('/api/export', p),
    blob = await response.blob();
  download(blob, filename);
  tell(`Exported ${(blob.size/1048576).toFixed(1)} MiB GLB. Scripts and physics remain in the game.`);
}
$('#export').onclick = guarded(() => exportProject(project(), 'smash-hit-world.glb'));
$('#export-all').onclick = guarded(async () => {
  const p = await (await request('/api/stitch-catalog')).json();
  await exportProject(p, 'smash-hit-all-segments.glb');
});

$('#refresh-runtime').onclick = guarded(async () => {
  const s = state.selection;
  if (!s) throw Error('Select a project segment first');
  tell('Reading the connected game…');
  const data = await (await request('/api/runtime?path=' + encodeURIComponent(s.instance.item.source)))
    .json();
  if (state.selection?.instance !== s.instance) return;
  state.runtimePid = data.pid;
  const select = $('#runtime-target');
  select.replaceChildren();
  for (const item of data.segments) select.add(new Option(
    `Room ${item.room} · instance ${item.id} · Z ${item.world_z_bounds.map(v=>v.toFixed(1)).join(' to ')}`,
    String(item.id)));
  $('#apply-runtime').disabled = !data.segments.length;
  $('#runtime-result').textContent = data.segments.length ?
    `${data.segments.length} matching loaded segments in process ${data.pid}` :
    'No matching segment is currently loaded.';
  tell($('#runtime-result').textContent);
});
$('#apply-runtime').onclick = guarded(async () => {
  const s = state.selection;
  if (!s) throw Error('Select a project segment first');
  $('#apply-runtime').disabled = true;
  try {
    tell('Pausing the native world and applying source-box edits…');
    const data = await (await request('/api/runtime/apply', {
      project: project(),
      instance: s.instance.item.id,
      native_pid: state.runtimePid,
      native_id: Number($('#runtime-target').value)
    })).json();
    $('#runtime-result').textContent =
      `Applied ${data.applied_boxes} boxes to native segment ${data.native_id}. World paused. Last box position: ${data.selection.position.map(v=>v.toFixed(2)).join(', ')}`;
    tell(data.single_undo ? 'Applied geometry and colliders. Undo in Android restores the entire apply operation.' : 'Applied edits to game geometry and colliders. This older APK has individual reset controls.');
  } finally {
    $('#apply-runtime').disabled = !$('#runtime-target').options.length;
  }
});

$('#import-run').onclick = () => $('#run-file').click();
$('#run-file').onchange = guarded(async () => {
  const f = $('#run-file').files[0];
  if (!f) return;
  const text = await f.text();
  let records;
  try {
    const j = JSON.parse(text);
    records = Array.isArray(j) ? j : [j]
  } catch {
    records = text.trim().split(/\r?\n/).map(x => JSON.parse(x));
  }
  const rooms = new Map();
  for (const e of records) {
    if (e.event === 'instrumentation_installed') rooms.clear();
    const s = e.snapshot || e;
    for (const r of [s.current_room, s.next_room, e.event === 'room_construct_end' ? e.room : null])
      if (r?.batches?.length) rooms.set(r.id, r);
  }
  const items = [];
  for (const room of [...rooms.values()].sort((a, b) => b.world_z_bounds[1] - a.world_z_bounds[1]))
    for (const b of room.batches) {
      const source = b.path.replace(/^segments\//, '').replace(/\.mesh$/, '');
      if (!state.catalog.segments.some(s => s.path === source)) throw Error(
        'Captured source is not in this APK: ' + source);
      items.push({
        id: 'captured-' + room.id + '-' + b.id,
        source,
        position: [0, 0, room.world_z_bounds[1] + b.offset],
        rotation: [0, 0, 0],
        scale: [1, 1, 1],
        edits: {}
      });
    }
  if (!items.length) throw Error('No complete native room snapshots found');
  const p = {
    format: 'smash-hit-lab-project-v1',
    apk_sha256: state.catalog.apk_sha256,
    name: 'Captured layout: ' + f.name,
    segments: items
  };
  remember();
  await loadProject(p);
  dirty();
  tell(
    `Imported ${rooms.size} captured room instances. Use one run's log; rebuilds create separate overlapping instances.`
    );
});

function catalog() {
  const q = $('#search').value.toLowerCase(),
    items = state.catalog.segments.filter(s => s.path.toLowerCase().includes(q));
  $('#catalog-count').textContent = state.catalog.count;
  const node = $('#catalog');
  node.replaceChildren();
  for (const item of items.slice(0, 200)) {
    const b = document.createElement('button');
    b.textContent = item.path;
    b.title = `Add segment · length ${item.length} · ${item.boxes} source boxes`;
    b.dataset.source = item.path;
    b.onclick = guarded(() => addSource(item.path));
    node.append(b);
  }
  if (items.length > 200) {
    const p = document.createElement('p');
    p.textContent = `Showing 200 of ${items.length}; search to narrow the library.`;
    node.append(p);
  }
}
$('#search').oninput = catalog;
$('#view-fov').onchange = guarded(() => {
  const value = Number($('#view-fov').value);
  if (!Number.isFinite(value) || value < 20 || value > 140)
    throw Error('Field of view must be between 20 and 140 degrees');
  camera.fov = value;
  camera.updateProjectionMatrix();
  tell(`Camera field of view: ${value}° vertical`);
});
let previous = performance.now();

function render(now) {
  requestAnimationFrame(render);
  const dt = Math.min(.1, (now - previous) / 1000);
  previous = now;
  const width = viewport.clientWidth,
    height = viewport.clientHeight;
  if (canvas.width !== Math.round(width * renderer.getPixelRatio()) || canvas.height !== Math.round(height *
      renderer.getPixelRatio())) {
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  }
  if ($('#flight').checked && !gizmo.dragging) {
    const direction = new THREE.Vector3((keys.has('KeyD') ? 1 : 0) - (keys.has('KeyA') ? 1 : 0), 0, (keys.has(
      'KeyS') ? 1 : 0) - (keys.has('KeyW') ? 1 : 0)).applyQuaternion(camera.quaternion);
    direction.y += (keys.has('KeyE') ? 1 : 0) - (keys.has('KeyQ') ? 1 : 0);
    if (direction.lengthSq() > 0) camera.position.addScaledVector(direction.normalize(), dt * Number($(
      '#fly-speed').value) * (keys.has('ShiftLeft') ? 5 : 1));
  } else orbit.update();
  renderer.render(scene, camera);
}
requestAnimationFrame(render);
window.shlab = {
  state,
  project,
  selectObject,
  setSelection,
  loadProject,
  source,
  renderer,
  camera,
  gizmo,
  geometry: () => state.selection?.instance.mesh.geometry.attributes.position.array
};
await guarded(async () => {
  state.catalog = await (await request('/api/catalog')).json();
  const texture = await new THREE.TextureLoader().loadAsync('/api/texture');
  texture.flipY = false;
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
  texture.colorSpace = THREE.NoColorSpace;
  material = new THREE.MeshBasicMaterial({
    map: texture,
    vertexColors: true,
    side: THREE.DoubleSide,
    toneMapped: false
  });
  catalog();
  const initial = state.catalog.segments.find(s => s.path === 'basic/basic/start') || state.catalog
    .segments[0];
  await add({
    id: uniqueId(),
    source: initial.path,
    position: [0, 0, 0],
    rotation: [0, 0, 0],
    scale: [1, 1, 1],
    edits: {}
  });
  tell('Ready. Click real geometry or choose a source box in the inspector.');
  dirty(false);
})();
