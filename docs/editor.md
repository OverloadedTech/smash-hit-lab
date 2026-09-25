# In-game editor

For a desktop workspace with a draggable gizmo, undo/redo, project saving, GLB assembly and application of box edits to a connected game, see [desktop_editor.md](desktop_editor.md). The native editor described here continues to operate on real loaded game objects; runtime changes are not automatically saved in the original game's quick-save.

The editor manipulates live native data in the original game. There is no substitute scene or hardcoded corridor. Selection traces a ray through the current camera using the engine's horizontal field of view. For baked room geometry, it tests actual retained indexed triangles. For native bodies, it walks real polyhedron face/edge loops and tests the resulting triangles. Body selection bounds are computed from actual transformed polyhedron vertices; native stored bounds are exposed separately because they do not reliably enclose every shape maximum in this build. Selection bounds and interactive world-axis handles are projected into the Android overlay. Up to 64 individual bounds are drawn for a large selection, alongside one aggregate bound and the full selection count.

## Moving one object or a group

Tap **Edit** during play. This freezes the world and detaches the inspection camera. Drag a visible object to select and move it in the view plane; its mesh and real collider move together. One gesture is one Undo. The hit point on the actual triangle anchors direct dragging, including when dragging a member of a large selection. Rendering and detached-camera flight continue while simulation is frozen.

**Move objects / Look around** switches between object dragging and camera looking. Use the stick and UP/DOWN to fly. **More** contains multi-select, **This piece** (mapped boxes in the selected segment), **Whole room** (loaded editable boxes and active ordinary bodies associated with the current room), Clear, optional axis handles, snapping, depth movement, Focus, Reset and exact Position/Rotation/Size for one object.

A group receives one common world displacement, preserving relative spacing and each member's rotation/scale. World-axis handles constrain displacement; the center handle uses the view plane through the aggregate pivot. Native scopes exclude room static bodies as individual editable targets, ball/model-rendered bodies, inactive bodies and inspect-only boxes. They never load more content. The native limit is 4,096 selected objects. The `loaded` scope remains available through the research API.

The precise fields support individual rotation/scale; bulk operations translate. Real object/source/room/mesh/collider information is available under **Position, rooms & research details**. Some objects have no dependable authored identity and are explicitly marked **current run only**.

In Move objects mode, arrows nudge X/Z and Page Up/Down nudge Y. Shift multiplies the step by 10; Alt uses one tenth. Ctrl+Z/Y undo/redo, Ctrl+A selects the current room, and Ctrl+S saves. Numeric fields keep normal text input. In Look around mode, arrows look instead.

## Static boxes

`tools/map_geometry.py` resolves source XML templates and tests each baked quad against oriented box faces. It records unambiguous ownership, ambiguous ownership and unmatched faces separately. Runtime `Room::createSegment` wrappers capture the actual newly created shapes and render batch, then verify collider and vertex counts against the metadata. Individual box editing is disabled if those checks fail or the face ownership is ambiguous.

A selected box shows its source segment, XML child index, box ordinal, session/room ID, real shape address, source attributes, world position, rotation and editor scale factors. Its position/rotation/scale controls transform both its mapped retained mesh vertices and its native collider polyhedron. Native normal, mass/collision-point and bound recomputation follows, then the real VBO is uploaded again.

The native source boxes do not have independent transform components. The editor's rotation/scale factors describe its operation on baked geometry; they are explicitly not presented as recovered native fields. Original XML positions use segment-local coordinates and sizes are half extents.

Some internal/occluded faces were removed during original baking. Moving a box cannot reveal a face that was not shipped. UVs and baked colors move with the vertices. Decals, water, reflection masks and independently scripted obstacles are not automatically moved with a static box. These limits are visible in the tooling and distinguish a runtime geometry editor from a complete offline level compiler.

## Native bodies

Scripted obstacle bodies expose their actual transform, shape/material information, collider count, native enum type, parent obstacle and associated room where these exist. Movement/rotation uses native `Body::setTransform`. Bodies flagged for the separate ball/model renderer are inspect-only, because their collider vertices are not their rendered mesh. Scaling changes native shape polyhedron vertices and recomputes normals, collision points, bounds and mass properties. There is no fake native scale property.

Editing is allowed while simulation is frozen. Lua scripts, joints, physics and fragmentation may change a body after updates resume. The editor invalidates tracked instances when their native lifetime ends and refuses to scale a shape whose topology no longer matches the captured original geometry.

## Reset, reload and persistence

**Save & resume** writes supported source edits and restores gameplay at the held player position. **Resume** alone does not write them to disk. Staged changes remain available during the process, including matching rebuilt instances, until saved/cleared or the process closes.

`files/shdev/level-edits.json` is a versioned sidecar tied to the original APK hash. Static boxes identify room, source segment, occurrence and XML/box indices. Authored obstacle bodies add definition identity and initial native entity ordinal. Segment-relative transforms survive world-origin rebasing. Baseline geometry signatures prevent applying a record to incompatible geometry. Unsupported transient objects remain runtime-only and are reported separately.

**Replay this level with saved edits** reconstructs the current checkpoint using the original game lifecycle, then reapplies matching edits. **Use saved edits on new runs** changes future application without reverting already loaded geometry. **Clear saved edits** clears future overrides; reload/rebuild restores original geometry. **Reset selected** restores source/captured baseline transforms as an undoable operation. Save after Reset removes that object's persistent record; Undo followed by Save reinstates it.

The original quick-save is unchanged and does not contain these edits. This is a separate transform-override format, not a full physics/script save or offline mesh rebaker. A moved authored body still spawns at its original obstacle definition's streaming threshold. Script/joint motion can change it after resuming. Procedural source occurrences may differ between generated runs.

Legacy reload/export commands remain available through the API. Reloading a segment invokes the original mesh loader, then reapplies enabled saved/staged overrides; it does not respawn expired scripts. The editor retains up to 32 undoable operations. History stores stable world positions, invalidates unloaded/reloaded native targets and refuses stale drag revisions. One gesture, group reset or desktop bulk apply is one operation.

The native group implementation preflights every member before editing. It checks identity, finite/ranged transforms, shape identity/counts and mapped vertex topology. Box edits then recompute each affected room body's mass/bounds once and upload each changed segment once. This is much cheaper than uploading an entire segment separately for every selected box. Baseline undo/reset writes the originally captured vertex bytes back exactly.

Undo restores editor transforms and geometry, not velocities, script variables, joints, fracture history or a full simulation snapshot. Resuming the world may move scripted/physical bodies again. In-game duplication/deletion, new asset authoring and a full offline rebaker remain unimplemented. Inspect-only segment selection exposes the real source and batch when no box can be identified safely.

**CONFIRMED runtime:** native box/body editing, actual Android field entry and Apply/Reset, native collider raycasts, segment reload and checkpoint rebuild all passed. A separate test moved a box to `(50,50,-205)` after a native origin shift of -200; the original level raycast hit the edited shape there, and reset restored both render/collider checksums. [experiments.md](experiments.md) links the measurements and screenshots.

## Automation API, revision 2

Snapshots include `editor_api_version: 2`, a primary `selection`, `selection_group` (revision, members, world positions, pivot, editable count and history sizes), and projected `move_handles`. Existing single-object commands remain available. Group operations are implemented in `dev/native/editor_group.cpp`; Android controls live in `EditorControls.java` and `WorldView.java`.

```json
{"op":"select","id":123,"box":38,"additive":true}
{"op":"select_all","scope":"segment","kind":"boxes"}
{"op":"move_selection","delta":[1,0,0]}
{"op":"edit_undo"}
{"op":"edit_redo"}
{"op":"reset_selection"}
{"op":"focus_selection"}
```

Use a current session ID obtained from a snapshot. Native edit commands require a paused world; the Android controls supply that pause explicitly. Optional `revision` rejects an outdated selection. A nonempty `gesture` merges consecutive moves of the same revision, with each `delta` interpreted relative to the beginning of that gesture. Drag commands use `axis` (0/1/2 or −1 for the view plane), normalized `screen_start`/`screen`, `aspect`, and a gesture token. `apply_box_edits` accepts one native segment ID, optional `expected_pid`, and an array of source-segment positions, rotation degrees and scale factors; it validates the entire operation and records one undo.

**CONFIRMED runtime:** group translation of static boxes and a scripted `scoretop` body, collider raycasts, reset/undo/redo, a 505-object scope, origin rebasing, reload/unload guards and normal shooting passed on the editor-release x86_64 APK. See [editor improvement experiments](editor_improvements.md) for exact release identity, UI/desktop checks and limitations.
