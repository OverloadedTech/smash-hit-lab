# Desktop level geometry editor

The desktop application reads the local APK. It renders the shipped baked meshes, exposes unambiguous source XML boxes, and saves editable projects. It is a geometry editor and research viewer; game scripts, collision simulation, glass fragmentation, native fog and scoring are not simulated in the browser.

## Launch

In this prepared workspace:

```bash
source tools/env.sh
python -m desktop.server
```

Open **http://127.0.0.1:8765**. The server listens only on loopback. No Node installation is needed. In a clean checkout, create a Python virtual environment, install `desktop/requirements.txt`, run `python tools/setup_desktop.py`, and supply your own APK with `--apk /path/to/game.apk`. See [repository setup](public_repository.md).

## Editing

The library lists all 643 segment sources. Adding a segment places it after the current sequence along negative Z. Click visible geometry to ray-select a source box, or choose a box in the inspector. Ambiguous, hidden or unmatched boxes remain inspect-only. Selected boxes are highlighted; groups also have one aggregate bound. Individual outlines are capped at 64 while all selected objects remain part of the operation.

For one object, use the draggable Move/Rotate/Scale controls or enter XYZ values and click **Apply transform**. Select World or Local axes for its gizmo. Box positions are in source segment coordinates; whole-segment placement is in project world coordinates. Rotation is Y×X×Z composition, with fields labeled in degrees. Scale must be positive. Reset restores the original source transform; for a whole segment this includes returning its placement to the origin. Undo/redo restores project state and the selected objects. The history retains 50 operations. Duplicate/remove require whole-segment selections and support several selected segments at once, preserving their relative placement when duplicated.

Right drag orbits, middle drag pans, and the wheel zooms. **Fly camera** changes right drag to free look and enables WASD plus Q/E vertical movement; Shift increases speed. **Focus** frames the selected geometry, including a small box or a group across multiple segments. Orange markers represent authored XML object anchors; they are not fabricated replacements for missing scripted objects.

The toolbar's **FOV** field accepts 20–140 vertical degrees. It changes the camera projection without modifying geometry, selection or project data. This view preference is not serialized into the project. Android's native FOV is horizontal, so the same numeric angle has a different meaning there.

**Save project** writes a local JSON project under `desktop/projects/` and downloads a copy. **Open** accepts a project or a GLB exported by this application, which embeds its editable project metadata. Reopening requires the matching input APK. The project records the APK SHA-256 so it cannot silently apply source indices to a different game build.

## Moving groups

Ctrl/Shift-click geometry or an instance in the project list to add/remove it, or enable **Multi-select**. The source-box picker also honors Multi-select. Selecting a whole segment and selecting one of its boxes are alternative levels: the latest choice replaces overlapping parent/child targets, so nothing moves twice.

**All editable boxes** selects boxes in the current segment or the whole project, according to **Box scope**. Ambiguous and inspect-only boxes are skipped with a count. **All segments** selects entire project instances, including their authored anchor markers.

Use the six move buttons and **World move step**, hold a button to repeat, or drag the Move gizmo. Arrows move in X/Z; Page Up/Down move in Y. Shift uses 10× the step and Alt uses 0.1×. A held key/button or a whole drag creates one undo action. **Snap handles** enables the Three.js translation grid at that step; the move buttons always use relative displacement. Group handles use world axes. Their Position fields specify the aggregate world center, and **Move group to position** translates the members to that center.

Group moves convert the shared world displacement through each member's parent transform, including nonuniform scale. They preserve each box's rotation/scale and relative world spacing. Selected groups translate; select one object for rotation or scaling. The editor does not support arbitrary group deformation across differently transformed parents. Validation runs before changing any target, and geometry bounds/GPU updates are batched per changed segment.

The desktop workspace edits baked boxes and whole segments. Orange Lua/object anchors are not individually simulated or treated as native bodies. A whole-segment move moves those authored markers with its geometry; Android remains the tool for editing real spawned scripted bodies.

## One-file geometry export

**Export GLB** creates one self-contained glTF binary with the edited geometry, per-segment transforms and an embedded tile atlas. The unlit material approximates the game's baked vertex lighting; it is not the complete native multi-pass renderer. Each mesh remains a node, making the single file useful in Blender and other glTF applications.

**Stitch** assembles the project's sequence end to end using each segment's actual length. **Import runtime snapshot / log** imports source meshes and offsets from captured native rooms, so the sequence can represent a real run. Use one run's log: rebuilds create different, potentially overlapping room instances. Layout import does not automatically recover all runtime body/box edits.

**Export all segments as one GLB** makes a catalogue in sorted source-path order. This is not a canonical campaign: room Lua makes weighted choices, some sources are variants/tests, and endless generation has no finite final segment. The equivalent command is:

```bash
python -m desktop.server --stitch-all artifacts/smash-hit-all-segments.glb
```

The verified catalogue export contains 643 mesh nodes, 3,475,048 vertices and 1,737,524 triangles in 105,203,532 bytes. Every mesh position and triangle index was compared with the supplied APK. The GLB contains game assets and belongs in the private local workspace, not the source-only research bundle.

## Sending edits to the running game

With Smash Hit Lab running on an Android device connected through adb, expand **Apply box edits to connected game**. Find matching loaded segments and choose the intended native instance. **Apply box edits · pause game** freezes the native world and sends the selected project's source-box edits through the existing native editor API. Rendering and colliders are changed together. Project placement of the whole segment is not applied.

With editor API revision 2, the native addon converts source positions through the actual loaded segment offset, room transform and world origin. All boxes are validated before any mutation, each mesh is uploaded once, and one Android Undo restores the entire apply operation. The bridge no longer temporarily resets a reference box. The native cap is 4,096 edits and the socket has a 1 MiB request limit; the old 128-box restriction does not apply to this API.

The bridge checks that the matching instance still exists after pausing and checks the expected process ID again inside the native apply command. On the Play/Edit addon, applied box transforms also become staged source overrides; use Save in the game to retain them for future runs, as described below. Earlier addons retain changes only in the live instance. This does not rebuild the APK. Applying a project containing several instances still requires choosing one explicit native target for each instance. Repeated source names are not automatically matched by guesswork.

For an older Lab APK without API revision 2, the bridge retains the earlier 128-box, per-object fallback. That fallback derives placement using a temporary reference reset and may leave partial edits on failure; use individual reset/reload there.

Live application requires the exact investigated input APK. It also checks the process identity recorded when targets were listed, so a restarted game cannot silently reuse a stale segment ID. Refresh the target list after restarting the game.

**CONFIRMED (earlier release):** `experiments/verify_desktop_runtime.py` pressed the actual browser Apply button, changed native mesh and collider checksums, and verified an original Level raycast hit the edited shape. A second application after world-origin rebasing preserved the requested world pose, and native Reset restored the original mesh. This passed on the expanded APK, PID 4696. Evidence is in `experiments/desktop/runtime/`; browser-only edit/save/export and actual gizmo-drag checks are in `experiments/desktop/result.json`.

The earlier bulk editor release is recorded in [editor_improvements.md](editor_improvements.md); current APK and desktop-to-game regression evidence is recorded in [simple_play.md](simple_play.md).

## Implementation

`desktop/assets.py` parses ZIP/XML/zlib meshes and MTX textures, resolves templates and validates projects. `desktop/export.py` writes GLB. `desktop/runtime.py` handles explicit live application through adb. `desktop/server.py` provides local endpoints and project saving. `desktop/web/` contains the Three.js viewer/editor; `selection.js` centralizes selection normalization, actual-geometry bounds and world-to-parent displacement conversion. Three.js is fetched at a pinned version with SHA-256 verification and its MIT license retained.

Changing a box transforms only its mapped original faces. Faces removed by baking, decals, reflections, UV generation and newly authored obstacles require further reconstruction. The editor does not invent missing geometry and is not a full source reconstruction.

## Keeping connected-game edits for later runs

On the Play/Edit addon, native box edits applied from the desktop also become staged source overrides. Open Edit/Tools in the game and use **Save edits for next run** or **Save & resume** to persist them. The desktop project and the on-device override file are separate saves. Segment placement in a desktop project still does not rewrite the game's procedural room generator. Applying saved source-box transforms preserves the original renderer and native colliders; a whole campaign rebaker remains outside this tool.
