# FOV, independent viewing and campaign travel

This page records the archived release named below. The current Android interface and saved editing are documented in [Play/Edit](simple_play.md) and [the editor](editor.md).

Open **DEV → Travel**. These controls work with the original native game. They separate the view, the player's travel direction and world simulation. The desktop editor also has a numeric FOV control in its view toolbar.

## Using the controls

| Control | Behavior |
| --- | --- |
| Apply FOV / slider | Set horizontal field of view to 20–140 degrees. The setting also applies to normal play after leaving tools. |
| Original FOV | Restore the original native lens and stop overriding it. |
| Watch ahead · run | Attach the view to the player's position, face forward and run the world. |
| Watch back · run | Attach the view to the player's position, face backward and run the world. This changes where you look, not the travel direction. |
| Drag on the game view | Look in any direction. In an attached view, the movement stick and UP/DOWN adjust your view offset without moving the player. |
| Free camera · pause | Pause physics/progression and detach the view for inspection. |
| Forward / Reverse | Move the actual player along world Z while running original simulation. Reverse initially faces backward. |
| Hold player | Keep the player's position still while physics and scripts continue. Use Free camera · pause to stop the world too. |
| Apply travel speed | Apply the selected progression rate; start forward travel if no manual travel is active. A paused world remains paused. |
| Original camera and music path | Release manual travel and restore the original camera and audio-driven path. |
| Unlock all levels · this session | Make all 13 campaign checkpoints available until disabled or the process restarts. |
| Jump to level · pause | Rebuild the selected checkpoint's first room and pause there. Arrive at the end selects its last native room near the exit. |
| Previous level / Next level | Jump relative to the actual current checkpoint. |
| Choose native room / Jump to room · pause | Choose an actual RoomDef from the selected checkpoint and reconstruct it. |
| Reverse selected level · run | Start near the selected checkpoint's end, face backward and travel back through its rooms. |

Travel speed and **Explore → camera flight speed** are separate. The former changes actual player progression; the latter controls the stick/keyboard's movement of the chosen control target. Travel uses negative Z for forward and positive Z for backward, independently of where the view points. With player noclip enabled, manual travel also suppresses collision hit penalties. Immortality remains a separate practice option.

The status reads **WORLD RUNNING**, **WORLD PAUSED** or **LOADING ROOM**. Geometry rebuilding needs original draw frames to prepare native buffers. During that preparation Level simulation is stopped; Menu/Display updates can finish an existing transition. A requested simulation step is retained until the rebuilt room is ready. Audio keeps running during a developer pause, as in the previous tools.

Settings are local to this Lab process. Leaving tools restores the original control path; FOV, immortality, unlimited balls and session unlock retain their explicit settings. Their badges remain visible. A new process starts with the defaults. Ordinary native gameplay and room entry can still update the Lab's own save files; a session-only unlock does not imply that playing after a jump writes no save.

To watch behind during normal forward progression, select **Watch back · run** and leave manual travel off. To change the progression speed, select a speed and apply it; **Forward** resumes a paused world. To explore backward from a distant point without first playing there, enable session unlock, choose a level and press **Reverse selected level · run**. Developer viewing/travel uses the tool input layer; normal throwing controls return when leaving tools.

## Native implementation

**CONFIRMED (static analysis):** the original viewport stores horizontal FOV at `+0x20`, near plane at `+0x24` and far plane at `+0x28` on both inspected 64-bit ABIs. The addon calls the original projection builder, draws with the temporary lens and restores the native viewport. Normal-play input receives the same lens around the original `Level::handleInput`; `Display::pixelToWorldDir` unprojects through that viewport. The detached developer view remains a separate temporary draw pose. Desktop Three.js uses vertical FOV, labeled explicitly; its numeric value is not directly interchangeable with native horizontal FOV at a given aspect ratio.

**CONFIRMED (static analysis and pilot):** the ordinary native rail uses a smoothed room length and a 32-second music phase. Manual travel uses the current physical room length divided by 32, multiplied by the chosen rate and the actual native update timestep. It is a separate nominal progression clock: physics, scripts, music and camera-flight speed are not globally accelerated or reversed. Snapshot counters expose elapsed travel dt, actual permitted travel updates and accumulated requested world-Z displacement, so frame count is not mistaken for elapsed time.

**CONFIRMED (static analysis):** original streaming discards previous rooms and does not load them by looking backward. Manual reverse detects crossing the current room entrance, selects the preceding native RoomDef and invokes the original `Level::reset`. The reconstructed previous room's exit is aligned to the old entrance in the addon's stable world coordinates, preserving the crossing pose. Native editor history/selection is invalidated as old room objects are destroyed. At campaign room zero, reverse stops and holds the player at the entrance.

On changing travel direction, expired authored obstacle definitions in the current room are rearmed for native creation. This also restores objects when turning forward again after a reverse pass. Owned obstacles still execute their original script tick; reverse expiry compares the opposite Z bound. Hold retains the last nonzero travel direction's cleanup sense. Room/entity ownership and native destruction remain intact. The code does not veto a destruction loop that expects its collection to shrink.

**LIMITATION:** this reconstructs original source content, not earlier runtime state. Broken glass, solved obstacle state, runtime edits and prior random choices are not restored. Procedural layouts can change. Unowned fragments/projectiles retain the original cleanup rules; physics, audio and particles do not run backward. The complete catalogue GLB is not used as a replacement world or a hidden room cache.

## Real levels and unlock behavior

`tools/map_navigation.py` reads the supplied APK's game/level XML to make local navigation metadata. `Player::getCheckpointCount()` limits the exposed campaign checkpoints to the native count of 13, including endless. The game XML has 15 entries because endless is repeated. The native RoomDef list also retains source-level indices 13 and 14 for those continuations. Navigation groups entries with the same final level name under checkpoint 12 and preserves each original value as `source_level_entry` in telemetry. They remain accessible in Endless's room chooser; they are not presented as additional menu checkpoints. Room jumps use the live native RoomDef indices, names and ordering. For Endless, arriving at the end means the last currently generated RoomDef, not a claim that the endless game has a final ending.

The original function named `Player::getHighScore(index)` reads checkpoint ball inventory for this menu path. The menu stops offering checkpoints when the next value is zero. The unlock wrapper supplies a minimum starting inventory to the original read/load paths while enabled, and direct navigation invokes original room construction. It does not set a premium entitlement or fill the stored checkpoint record arrays. Snapshots show original recorded ball counts separately from current availability. The normal game package and input APK remain separate and untouched.

**CONFIRMED (static):** profile serialization reads the stored checkpoint arrays directly, without consulting the overridden availability getter. Displaying all levels does not itself manufacture permanent checkpoint records. Playing after a jump can still update the Lab profile through the original reporting and save paths; see [save behavior](saves_and_integrity.md).

## Automation

The same native queue accepts these commands through `tools/lab.py`; UI controls do not maintain a substitute world:

```bash
python tools/lab.py command '{"op":"enable","value":true}'
python tools/lab.py command '{"op":"fov","value":100}'
python tools/lab.py command '{"op":"mode","value":"ride"}'
python tools/lab.py command '{"op":"look","rotation_degrees":[0,180,0]}'
python tools/lab.py command '{"op":"travel_speed","value":2}'
python tools/lab.py command '{"op":"travel","direction":-1}'
python tools/lab.py command '{"op":"freeze","value":false}'
python tools/lab.py command '{"op":"unlock_levels","value":true}'
python tools/lab.py command '{"op":"freeze","value":true}'
python tools/lab.py command '{"op":"jump_level","index":3}'
```

Inspect `snapshot.navigation.rooms` to obtain a real `jump_room` index. `reverse_level` accepts the same checkpoint index as `jump_level`. `fov_original` removes the lens override; `mode: follow` restores original camera/progression. Travel commands require a loaded checkpoint game and enabled developer tools. Speed accepts finite values from 0.1 to 100 in automation; touch presets span 0.25×–25×. Very large jumps/rates still run the original ordered forward loader, so they are not a guarantee of uninterrupted high-speed rendering in every room.

Snapshots report availability and original recorded ball counts separately, plus loading state, cleanup direction, view offset, last draw/input FOV, projection diagonals, actual travel dt/seconds and native update counters. `velocity_world_z` is the last computed manual travel rate; a frozen world does not move even if that rate remains nonzero. Explicit jumps reset the world-coordinate origin. During reconstruction, internal callbacks observe the temporary reset origin; use `room_reconstructed` and the ready snapshot for the resulting room placement.

## Evidence and current verification

**PASS (55 behavior checks):** delivered APK `1cfe846a63d3a46daf577d045ece235267a822b26ab882a2ce80822c6af31f62`, native PID 14443. The release aggregate, `artifacts/travel-validation-report.json`, binds the reports, executed harnesses, build sources and installed APK identity. Files under `artifacts/` are produced locally by the build and are not part of the source release. All 2,433 retained original asset/library entries remain byte-identical to the supplied APK. Android runtime checks used the actual shipped x86_64 engine on the documented API 30 software emulator.

| Area | Passing checks | Observed behavior |
| --- | --- | --- |
| Native Travel | 15 | Original projection/input, independent attached view, measured travel dt/rates, forward/hold/reverse, object recreation, reversible unlock, invalid requests, every checkpoint, Endless continuation and reverse boundaries |
| Android Travel UI | 6 | Real numeric keys, sliders, touch look, speed chooser, unlock, level/room jumps and a completed homepage transition into a paused destination |
| Native editor | 8 | Mixed box/body transforms, actual meshes/colliders, group history, validation, loaded scopes, rebasing, unload invalidation and original shooting |
| Android editor UI | 7 | World selection, multi-select, held movement, axis/view-plane handles, keyboard, source picker, bulk move and undo |
| Desktop editor | 11 | Numeric FOV/projection, selection, single transforms, group movement/history, handles, save/export/reopen and whole-segment operations |
| Desktop → Android | 8 | Actual browser edits applied to 182 source boxes in an explicit native instance, collider/raycast checks, one group undo and repeat application after rebasing |

The continuation jump entered native RoomDef 146 (`endless/narrow0`, original source-level entry 14) under menu checkpoint 12. A reverse room crossing executed exactly three requested Level updates while preserving the seam and invalidating old editor history. With normal controls, the projectile-angle ratio at FOV 110 versus 60 was 2.47374494, against the independent projection prediction 2.47362491. Native bulk selection moved 505 editable objects; the separately generated Android UI room contained 463. Those are measured run counts, not fixed limits.

Travel evidence is in `experiments/travel_tools/native/` and `experiments/travel_tools/ui/`; editor regression reports are in `experiments/travel_tools/editor_regression/`. The APK, build record and aggregates are archived together under `artifacts/releases/travel-tools/`. Procedures record device/APK/PID identity, executed harness hashes, actual projection/poses, checkpoint jumps and real control interactions. Both x86_64 and arm64-v8a compiled. Physical ARM runtime, every boss interaction and complete campaign/mode playthroughs remain **UNKNOWN**.

Preliminary attempts remain separately recorded. Candidate `ee17e24c…` exposed a consumed-step defect at a reverse boundary. Candidate `945d8351…` exposed the moving speed dropdown, independent native pause and missing objects on a forward return. Candidate `fb67d0e5…` passed five UI checks and a separate homepage pilot; its final automated choice was offscreen. The first final-APK UI attempt also missed that offscreen choice because it scrolled before the modal window was ready. Waiting for the real dialog and scrolling its actual list completed the six-check retry without changing the APK. These attempts are not counted as successful release checks; their paths and corrections are in the aggregate and notebook.

Reproduce on the prepared laboratory emulator with the desktop server running:

```bash
source tools/env.sh
export SHLAB_TRAVEL_EVIDENCE=experiments/local_travel_check
export SHLAB_EDITOR_EVIDENCE=experiments/local_travel_check/editor_regression
python experiments/summarize_travel.py --record-build
python experiments/prepare_device.py --install --record experiments/local_travel_check/device.json
python experiments/verify_travel.py
python experiments/verify_travel_ui.py
mkdir -p experiments/local_travel_check/editor_regression
cp experiments/local_travel_check/device.json experiments/local_travel_check/editor_regression/device.json
python experiments/verify_editor_android.py
python experiments/verify_editor_ui.py
python experiments/verify_editor_desktop.py
python experiments/verify_editor_runtime.py
python experiments/summarize_editors.py
python experiments/summarize_travel.py
```

The separate output directory preserves recorded release measurements; aggregation writes new current reports under `artifacts/`. The release aggregate also checks the retained `build-sources.json` record of the delivered native/Java/build sources. The record command compares packaged libraries, DEX and navigation metadata with local build products; aggregation rejects a subsequent source change. Device-mutating checks run sequentially. These experiments rebuild, teleport and edit the separate Lab run. They do not clear or modify the original app. Recorded startup ANRs were explicitly recovered with **Wait** before controlled UI input; the exact cause and physical-device startup behavior remain unknown.

## Stitching result

**CONFIRMED:** the existing all-segments GLB at `artifacts/smash-hit-all-segments.glb` contains all 643 shipped segment meshes in one self-contained file, with an embedded tile atlas and editable project metadata. It is 105,203,532 bytes, with 3,475,048 vertices and 1,737,524 triangles. Every exported catalogue mesh/index array was compared with the input APK. SHA-256: `6bcf064b478699556fcc1b0dd56f638facfd13eed7092559d2ce4e3becee7eba`.

That experiment succeeded as a static catalogue assembly. It is an artificial sequence, not a canonical game route: the real game chooses and repeats segments through Lua room generation. Import a captured native layout when the arrangement of one specific run matters. The GLB does not contain a working Lua/physics simulation.
