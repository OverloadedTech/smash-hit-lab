# Play, Edit and saved changes

This version replaces the Android Explore/Travel/Editor tabs with a small play
bar, an editing bar and a paused Tools drawer. The older API commands remain
available for reproducible research. They are no longer the primary phone UI.

## Playing

New runs show the Play controls by default. **Rails** follows the normal forward
direction; tap it to choose **Free move**, where the stick controls movement.
Both modes move the actual native Level player position and attach the view to
it. Drag anywhere outside the controls to look; tap to shoot, or use **FIRE**.
Looking backward does not change the direction of automatic rail travel.

| Control | Effect |
| --- | --- |
| Stick | Move forward/backward and sideways relative to the view |
| UP / DOWN | Move along world vertical |
| Stop / Move | Hold/release all player movement; physics and shooting continue |
| Reverse / Forward | Change the automatic rail direction |
| Look back / Look ahead | Smoothly turn toward world +Z / −Z |
| Speed | Pause and open movement, look-speed and horizontal-FOV settings |
| Edit | Freeze simulation and detach the inspection camera |
| Tools | Freeze simulation and open the optional settings/details drawer |

Keyboard: WASD move, Q/E up/down, arrows look, Space/Enter fire, and F1/Tab/Escape
open or close Tools. A short tap is held in the original input queue until the
native shot constructor acknowledges it, with a 1.5-second fallback. This avoids
discarding a tap between two slow emulator frames. Releasing movement uses the
latest input state; it does not accumulate a delayed movement burst during a stall.

**Forward speed** changes native path travel rate; **Move / strafe speed** changes
manual flight speed; **Look speed** changes drag sensitivity and the Look back
turn duration. **Field of view** is horizontal degrees. Reset field of view
restores the original projection. Settings are remembered in the Lab app.

**Fly through walls** enables noclip. Without it, manual movement tests the
original native raycast; this is a point obstruction test, not a new character
capsule/ground-walking controller. **Immortal** and **Unlimited balls** are separate
practice switches, including when using original controls. They reset on a new
process. The other movement/view preferences persist.

Backward travel reconstructs discarded rooms using original definitions. It
does not rewind physical time, previous breakage, script variables or random
choices. Saved source edits can be applied to reconstructed matching instances.
Audio, particles and physics continue forward in time.

## Editing with a finger

1. Tap **Edit**. The status reads **PAUSED · EDITING**.
2. Drag visible geometry. The native ray selects a real rendered triangle, and
   movement changes its mapped mesh and native collider. A whole drag is one Undo.
3. Use **Look around** to turn the detached camera; the stick and UP/DOWN fly it.
   Switch back to **Move objects** to drag geometry again.
4. Tap **Save & resume** to persist supported edits and continue from the held
   player position. **Resume** alone keeps current/staged edits without writing
   them to disk; use Save when they should survive closing the app.

**More** contains multi-selection, **This piece** (mapped boxes in the selected
segment), **Whole room** (loaded editable boxes and active ordinary bodies in the
current room), optional axis handles, grid snapping, Closer/Farther, Focus,
Reset selected and exact Position/Rotation/Size fields for one object.
Dragging a member of an existing group preserves the group and its spacing.
Direct dragging uses the touched triangle's depth, so a deep room-wide selection
does not pull the touched object away from the finger. Axis handles use the
group's aggregate pivot as usual.

**Replay this level with saved edits** starts the current checkpoint through the
original lifecycle. **Use saved edits on new runs** affects future instances.
**Clear saved edits** clears the sidecar; currently loaded geometry changes back
when reloaded/rebuilt. Reset selected followed by Save removes that object's
record. Undo can restore it before saving again.

## What actually pauses

| State | Player | Physics, scripts, menu animation | Inspection view |
| --- | --- | --- | --- |
| Rails | Automatic plus manual movement | Running | Follows player; look independently |
| Free move | Manual movement | Running | Follows player; look independently |
| Stop | Held | Running | Look/shoot still work |
| Edit / Tools / Explore menu | Held | Paused | Detached while exploring/editing |

**CONFIRMED runtime:** entering Edit, waiting 20 wall-clock seconds and moving
the detached camera held both Game/Level update counters and the player position.
In the delivered APK's test, six resumed updates totaled 0.555224 native seconds
and advanced the player 2.776119 units, matching the initial room's five-unit
pace without catching up to elapsed music time. The new Play path integrates
movement using the native simulation timestep.

Audio continues during a developer freeze. The original music clock can still
affect next-room preparation; the player travel controller no longer follows its
accumulated position error. Stop intentionally leaves physics running. The old
`mode`, `progression_hold` and raw `freeze` commands remain research controls;
mixing them manually can select different semantics from this table.

**Original game controls · new run** deliberately starts a fresh original-camera
run. It disables automatic Play controls for future starts, until that preference
is enabled again. It does not hand a freely moved player back to an old music
position in the middle of a run.

## Fog, menu and advanced details

**Fog during play** and **Fog while editing / in tools** are independent,
remembered preferences. They drive the original patched shader uniforms in the
corresponding context. They do not change content loading. Different material
passes can have different fog implementations; the switch controls only the
shader variants the addon intercepts.

In the homepage, use **Tools → Explore menu**. During a transition the entry is
**Explore transition**. The same stick/look/vertical controls fly an independent
camera while the native scene is held. Resume releases the original transition
animation before automatic Play controls attach at its endpoint.

**Position, rooms & research details** shows actual player/view coordinates,
selection metadata, current/next native rooms, mesh loading and draw-submission
flags, bounds and recent destruction history. Submission is not proof of visible
pixels. It also has XYZ teleport, separate player/camera position bookmarks and
an optional transition-capture button. The menu uses native Scene data rather
than a fabricated gameplay-room list. Menu geometry is explorable, not editable
by the source-box editor.

## Saved format and limits

`files/shdev/controls.json` stores versioned movement/view preferences.
`files/shdev/level-edits.json` stores versioned original-APK-hash-bound edits.
Both use a validated JSON format and atomic private-file replacement. Neither
overwrites packaged game assets, the original profile or quicksave.dat.

An edit identifies a room name, segment source, occurrence within that room and
source box index/ordinal. Authored obstacle bodies additionally identify the
source obstacle definition and its initial native entity ordinal. Transforms are
relative to the segment, so origin rebasing does not corrupt placement. Original
geometry signatures are checked before reapplication. Mismatches are skipped
and reported, rather than moving some other object.

Static boxes and source-associated ordinary bodies can persist. Unowned/transient
bodies without a dependable authored identity are marked **current run only**.
Script motion, joints and physics can change bodies after resuming. An authored
body still spawns at its original definition's streaming threshold: moving it far
along Z does not move that threshold. Repeated/random segment choices are not a
frozen campaign. Absent faces removed by the original mesh baker remain absent.
These are transform overrides, not a complete level rebaker or simulation save.

First-person shots use the original input, inventory, solver and collision code.
Their forward-only cleanup is extended so shots can travel backward or below the
normal corridor. They are retired through the original destructor after 15 native
seconds, at 100 units from the player, when inactive, or above a 256-ball cap.
Original controls retain original projectile cleanup. Ordinary fragments keep
their original lifetime rules.

Diagnostic events now rotate at 8 MiB per file, retaining two older files
(`events.jsonl.1` and `.2`). Oversized logs from older addons are trimmed to their
newest complete records on startup. Samples retain player/camera, room/batch,
counts, memory and timing information while omitting large editor/UI arrays.
Every event carries its PID. Full snapshots remain available separately.

## Verification

**CONFIRMED (2026-09-08):** APK SHA-256
`a02ecf9e92601b98b9c13cd569282e3f116bb0789b77c8c61a00c76fdc3824d1`
passed the APK-bound Android Play/Edit, menu, original-controls, process-restart,
editor and navigation checks. Together with the unchanged desktop editor's
source-bound checks, the validation contains 72 behavior checks, plus the
diagnostic logger's host filesystem checks. The original 2,433 retained game
asset/library entries are byte-identical. See the [measured results](simple_play_experiments.md)
and the local `artifacts/simple-play-validation-report.json`.

Android runtime evidence is from x86_64 processes 26508 and 27131 on the API 30
software emulator. ARM64 compiled and passed static checks; physical-device
execution remains untested. A startup ANR and its explicit Wait action are
preserved; the separate force-stop/reopen test needed no ANR recovery.
