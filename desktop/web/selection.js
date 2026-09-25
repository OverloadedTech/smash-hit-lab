import * as THREE from 'three';

// A segment and one of its boxes are alternative targets: never move a box
// twice by also moving its parent. The last explicitly chosen target wins.
export function normalizeSelection(items) {
  const result = new Map(), instances = new Map();
  for (const item of items) {
    const {instance, ordinal} = item;
    const id = instance.item.id, key = id + ':' + (ordinal ?? 'segment');
    if (!instances.has(id)) instances.set(id, new Set());
    const siblings = instances.get(id);
    if (ordinal === null) {
      for (const sibling of siblings) result.delete(sibling);
      siblings.clear();
    } else {
      result.delete(id + ':segment');
      siblings.delete(id + ':segment');
    }
    result.delete(key);
    result.set(key, item);
    siblings.add(key);
  }
  return [...result.values()];
}

export function editable(s) {
  return s.ordinal === null || !!s.instance.data.meta.mapping.boxes[s.ordinal]?.editable;
}

export function sourcePose(s) {
  return s.ordinal === null ? {position: [0, 0, 0], rotation: [0, 0, 0], scale: [1, 1, 1]} : {
    position: s.instance.data.meta.mapping.boxes[s.ordinal].position.slice(),
    rotation: [0, 0, 0], scale: [1, 1, 1]
  };
}

export function selectedPose(s) {
  const p = s.ordinal === null ? s.instance.item :
    s.instance.item.edits[String(s.ordinal)] || sourcePose(s);
  return {position: p.position.slice(), rotation: p.rotation.slice(), scale: p.scale.slice()};
}

// Convert one world displacement to each target's parent coordinates. Inverse
// rotation alone is insufficient when the parent segment is scaled.
export function translatedPoses(items, delta, initial = items.map(selectedPose)) {
  if (!delta.toArray().every(Number.isFinite)) throw Error('Enter a finite movement');
  return items.map((s, i) => {
    if (!editable(s)) throw Error('The selection contains an inspect-only box; select editable boxes to move');
    const parent = s.ordinal === null ? s.instance.group.parent : s.instance.group;
    parent.updateWorldMatrix(true, false);
    if (Math.abs(parent.matrixWorld.determinant()) < 1e-12) throw Error('The parent transform cannot be inverted');
    const inverse = new THREE.Matrix3().setFromMatrix4(parent.matrixWorld.clone().invert());
    const position = new THREE.Vector3().fromArray(initial[i].position).add(delta.clone().applyMatrix3(inverse)).toArray();
    if (!position.every(v => Number.isFinite(v) && Math.abs(v) <= 1e7))
      throw Error('Movement exceeds the supported coordinate range');
    return {...initial[i], position};
  });
}

export function objectBounds(s, result = new THREE.Box3()) {
  const {instance, ordinal} = s;
  instance.group.updateWorldMatrix(true, true);
  if (ordinal === null) return result.setFromObject(instance.mesh);
  // Use mapped, edited vertices, including source-baked rotations. This also
  // gives useful bounds for inspect-only boxes with some known faces.
  result.makeEmpty();
  const p = new THREE.Vector3(), box = instance.data.meta.mapping.boxes[ordinal];
  const vertices = instance.mesh.geometry.attributes.position.array;
  for (const quad of box.quads) for (let j = 0; j < 4; j++)
    result.expandByPoint(p.fromArray(vertices, (quad * 4 + j) * 3).applyMatrix4(instance.group.matrixWorld));
  if (result.isEmpty()) {
    const pose = selectedPose(s), half = new THREE.Vector3().fromArray(box.half_extents);
    const matrix = new THREE.Matrix4().compose(new THREE.Vector3().fromArray(pose.position),
      new THREE.Quaternion().setFromEuler(new THREE.Euler(...pose.rotation.map(THREE.MathUtils.degToRad), 'YXZ')),
      new THREE.Vector3().fromArray(pose.scale));
    result.set(half.clone().negate(), half).applyMatrix4(matrix.premultiply(instance.group.matrixWorld));
  }
  return result;
}

export function combinedBounds(items) {
  const result = new THREE.Box3();
  for (const s of items) result.union(objectBounds(s));
  return result;
}
